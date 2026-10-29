"""The My Ride K-12 integration."""
import logging
import asyncio
import aiohttp
import json
from datetime import timedelta, datetime
from typing import Dict, Any, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    CONF_DISTRICT_ID,
    DEFAULT_POLL_INTERVAL_ACTIVE,
    DEFAULT_POLL_INTERVAL_PASSIVE,
    STOP_ARRIVAL_RADIUS_METERS,
    EVENT_MYRIDE_TELEMETRY,
    haversine_distance,
    meters_to_miles,
    meters_to_feet,
    get_field,
    get_run_display_name,
    get_time_suffix,
)
from .api import MyRideAPI, MyRideAuthError, MyRideAPIError


_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]


def _async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry, students: list) -> None:
    """Migrate entity IDs to clean _am / _pm suffixes, eliminating _2 collisions."""
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)

        target_map: Dict[str, str] = {}
        for student in students:
            student_id = get_field(student, "studentId")
            first = get_field(student, "firstName", "")
            last = get_field(student, "lastName", "")
            student_name = f"{first} {last}".strip()
            slug = student_name.lower().replace(" ", "_")

            runs = get_field(student, "runInfo", [])
            for run in runs:
                run_id = get_field(run, "runId")
                if student_id is None or run_id is None:
                    continue

                display_name = get_run_display_name(run, runs)
                time_suffix = get_time_suffix(display_name)

                target_map[f"myride_{student_id}_{run_id}_bus_tracker"] = f"device_tracker.{slug}_bus{time_suffix}"
                target_map[f"myride_{student_id}_{run_id}_next_stop"] = f"sensor.{slug}_next_bus_stop{time_suffix}"
                target_map[f"myride_{student_id}_{run_id}_bus_status"] = f"sensor.{slug}_bus_status{time_suffix}"
                target_map[f"myride_{student_id}_{run_id}_distance"] = f"sensor.{slug}_bus_distance_to_next_stop{time_suffix}"

        for reg_entry in entries:
            target_id = target_map.get(reg_entry.unique_id)
            if not target_id:
                continue

            if reg_entry.entity_id != target_id:
                existing = registry.async_get(target_id)
                if existing is not None and existing.entity_id != reg_entry.entity_id:
                    # If the existing entity is also slated for migration to a different ID, move it temporarily
                    if existing.unique_id in target_map and target_map[existing.unique_id] != existing.entity_id:
                        temp_id = f"{existing.entity_id}_migrating"
                        try:
                            registry.async_update_entity(existing.entity_id, new_entity_id=temp_id)
                        except Exception:
                            pass
                    else:
                        _LOGGER.debug(
                            "Target entity ID %s already in use; skipping migration for %s",
                            target_id,
                            reg_entry.entity_id,
                        )
                        continue

                _LOGGER.info(
                    "Migrating entity ID from %s to %s",
                    reg_entry.entity_id,
                    target_id,
                )
                try:
                    registry.async_update_entity(reg_entry.entity_id, new_entity_id=target_id)
                except Exception as err:
                    _LOGGER.warning(
                        "Could not migrate entity ID %s to %s: %s",
                        reg_entry.entity_id,
                        target_id,
                        err,
                    )
    except Exception as err:
        _LOGGER.debug("Entity ID migration skipped: %s", err)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up My Ride K-12 from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    district_id = entry.data[CONF_DISTRICT_ID]

    session = async_get_clientsession(hass)
    api = MyRideAPI(session=session, district_id=district_id)

    # Initialize auth on startup
    try:
        await api.async_login(username, password)
    except MyRideAuthError as err:
        _LOGGER.error("Authentication failed during setup: %s", err)
        return False
    except MyRideAPIError as err:
        _LOGGER.error("API error during setup: %s", err)
        return False

    coordinator = MyRideDataUpdateCoordinator(hass, api, username, password)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Migrate legacy entity IDs (e.g. *_2) to specific _am / _pm suffixes
    students = get_field(coordinator.data, "students", [])
    _async_migrate_entity_ids(hass, entry, students)

    # Start the real-time SignalR WebSocket listener
    coordinator.start_signalr()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.stop_signalr()
    return unload_ok


class MyRideDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator to manage My Ride K-12 data updates."""

    def __init__(self, hass: HomeAssistant, api: MyRideAPI, username: str, password: str) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_PASSIVE),
        )
        self.api = api
        self.username = username
        self.password = password
        self.last_bus_fetch: datetime = dt_util.now() - timedelta(days=1)
        self.buses: Dict[str, Dict[str, Any]] = {}
        self.completed_stops: Dict[int, set] = {}
        self.live_etas: Dict[str, Dict[str, Any]] = {}
        self._last_stop_distance: Dict[str, float] = {}
        self._last_date: Optional[str] = None
        self.signalr_connected = False
        self._signalr_task: Optional[asyncio.Task] = None

    def get_completed_stops(self, run_id: int) -> set:
        """Get the set of completed stop IDs for a run."""
        return self.completed_stops.get(run_id, set())

    def get_stop_distance_trend(self, run_id: int, stop_id: int, current_distance: float) -> Optional[bool]:
        """Check if bus is approaching stop (True) or departing (False)."""
        key = f"{run_id}_{stop_id}"
        prev = self._last_stop_distance.get(key)
        self._last_stop_distance[key] = current_distance
        if prev is None:
            return None
        return current_distance < prev

    def start_signalr(self) -> None:

        """Start the SignalR background task."""
        self._signalr_task = self.hass.async_create_background_task(
            self._async_run_signalr(),
            "myride_signalr"
        )

    async def stop_signalr(self) -> None:
        """Stop the SignalR background task."""
        if self._signalr_task:
            self._signalr_task.cancel()
            try:
                await self._signalr_task
            except asyncio.CancelledError:
                pass
            self._signalr_task = None

    async def _async_run_signalr(self) -> None:
        """Maintain real-time SignalR connection for bus coordinates and ETAs."""
        _LOGGER.info("Starting My Ride K-12 SignalR background task")
        backoff = 1
        
        while True:
            try:
                # 1. Negotiate connection
                session = await self.api._get_session()
                negotiate_url = f"https://myridek12.tylerapi.com/livevehiclehub/negotiate?x-tenant-id={self.api.district_id}"
                headers = self.api._get_headers()
                
                async with session.post(negotiate_url, headers=headers) as resp:
                    if resp.status == 401:
                        _LOGGER.info("Cognito token expired during SignalR negotiation, attempting re-login")
                        await self.api.async_login(self.username, self.password)
                        headers = self.api._get_headers()
                        async with session.post(negotiate_url, headers=headers) as retry_resp:
                            if retry_resp.status != 200:
                                raise MyRideAPIError(f"SignalR negotiation retry failed with status {retry_resp.status}")
                            neg_data = await retry_resp.json(content_type=None)
                    elif resp.status != 200:
                        raise MyRideAPIError(f"SignalR negotiation failed with status {resp.status}")
                    else:
                        neg_data = await resp.json(content_type=None)
                    
                connection_token = neg_data.get("connectionToken") or neg_data.get("connectionId")
                if not connection_token:
                    raise MyRideAPIError("Failed to obtain connection token during negotiation")

                
                # 2. Establish WebSocket connection
                ws_url = f"wss://myridek12.tylerapi.com/livevehiclehub?x-tenant-id={self.api.district_id}&id={connection_token}"
                _LOGGER.info("Connecting to My Ride K-12 live tracking WebSocket")
                
                async with session.ws_connect(ws_url, headers=headers, heartbeat=15) as ws:
                    _LOGGER.info("WebSocket connected, sending handshake")
                    backoff = 1  # Reset reconnect backoff on successful connection
                    self.signalr_connected = True
                    
                    # Send handshake
                    handshake = {"protocol": "json", "version": 1}
                    await ws.send_str(json.dumps(handshake) + "\x1e")
                    
                    # Read messages loop
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            parts = msg.data.split("\x1e")
                            for part in parts:
                                if not part:
                                    continue
                                try:
                                    data = json.loads(part)
                                except Exception:
                                    continue
                                
                                # Handle message type
                                msg_type = data.get("type")
                                if msg_type == 6:  # Ping
                                    # Respond with a ping to keep connection alive
                                    await ws.send_str('{"type":6}\x1e')
                                elif msg_type == 1:  # Invocation (Event)
                                    target = data.get("target")
                                    args = data.get("arguments", [])
                                    if target == "NewLocation" and args:
                                        self._handle_new_location(args[0])
                                    elif target == "NewETA" and args:
                                        self._handle_new_eta(args[0])
                                        
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            _LOGGER.warning("WebSocket connection closed or error occurred")
                            break
                            
            except asyncio.CancelledError:
                _LOGGER.info("SignalR background task cancelled")
                self.signalr_connected = False
                break
            except Exception as err:
                _LOGGER.error("Error in SignalR connection: %s", err)
                self.signalr_connected = False
                
            # Reconnect delay with exponential backoff capped at 60s
            _LOGGER.info("Attempting reconnection in %s seconds...", backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                break
            backoff = min(60, backoff * 2)

    def _handle_new_location(self, bus_status: Dict[str, Any]) -> None:
        """Handle real-time bus location update."""
        asset_unique_id = get_field(bus_status, "assetUniqueId")
        if not asset_unique_id:
            return
            
        _LOGGER.debug("Received live bus location for %s", asset_unique_id)
        self.buses[asset_unique_id] = bus_status
        if self.data is not None:
            self.data["buses"] = list(self.buses.values())

        # Date rollover check: reset completed stops if day changed
        now = dt_util.now()
        today_str = now.date().isoformat()
        if self._last_date != today_str:
            self.completed_stops.clear()
            self._last_stop_distance.clear()
            self._last_date = today_str

        # Proximity stop progression:
        # Check active runs for this vehicle and detect stop arrival
        bus_lat = get_field(bus_status, "latitude")
        bus_lon = get_field(bus_status, "longitude")
        if bus_lat is not None and bus_lon is not None and self.data:
            students = self.data.get("students", [])
            for student in students:
                run_info = get_field(student, "runInfo", [])
                for run in run_info:
                    active_veh = get_field(run, "activeVehicle") or get_field(run, "assetUniqueId")
                    if active_veh != asset_unique_id:
                        continue
                    run_id = get_field(run, "runId")
                    if run_id is None:
                        continue
                    if run_id not in self.completed_stops:
                        self.completed_stops[run_id] = set()

                    stops = get_field(run, "stopsInfo", [])
                    for stop in stops:
                        stop_id = get_field(stop, "stopId")
                        if stop_id is None or stop_id in self.completed_stops[run_id]:
                            continue
                        stop_lat = get_field(stop, "stopLat")
                        stop_lon = get_field(stop, "stopLong")
                        if stop_lat is None or stop_lon is None:
                            continue

                        dist = haversine_distance(bus_lat, bus_lon, stop_lat, stop_lon)
                        self._last_stop_distance[f"{run_id}_{stop_id}"] = dist

                        if dist <= STOP_ARRIVAL_RADIUS_METERS:
                            _LOGGER.info(
                                "Bus %s arrived within %.1fm of stop %s (run %s)",
                                asset_unique_id, dist, stop_id, run_id
                            )
                            self.completed_stops[run_id].add(stop_id)
                            break

        # Fire HA telemetry event if event bus is available
        try:
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                self.hass.bus.async_fire(
                    EVENT_MYRIDE_TELEMETRY,
                    {
                        "vehicle_id": asset_unique_id,
                        "latitude": bus_lat,
                        "longitude": bus_lon,
                        "speed": get_field(bus_status, "speed"),
                        "heading": get_field(bus_status, "heading"),
                        "visible_run_name": get_field(bus_status, "visibleRunName"),
                        "log_time": get_field(bus_status, "logTime"),
                    }
                )
        except Exception as err:
            _LOGGER.debug("Could not fire telemetry event: %s", err)

        # Notify Home Assistant that data has updated
        self.async_update_listeners()

    def _handle_new_eta(self, stop_eta: Dict[str, Any]) -> None:
        """Handle real-time stop ETA update."""
        run_id = get_field(stop_eta, "runId")
        stop_id = get_field(stop_eta, "stopId")
        eta_str = get_field(stop_eta, "eta")
        planned_str = get_field(stop_eta, "plannedTime")
        
        if run_id is None or stop_id is None or not eta_str:
            return
            
        _LOGGER.debug("Received live ETA for run %s stop %s", run_id, stop_id)
        
        # Calculate new eta_minutes
        try:
            eta_dt = dt_util.parse_datetime(eta_str)
            if not eta_dt:
                return
            now = dt_util.now()
            # If naive, localize
            if eta_dt.tzinfo is None:
                eta_dt = eta_dt.replace(tzinfo=now.tzinfo)
            # Calculate difference in minutes
            diff = (eta_dt - now).total_seconds() / 60.0
            eta_minutes = max(0, int(diff))
        except Exception as err:
            _LOGGER.error("Failed to parse live ETA time: %s", err)
            return

        # Store in persistent self.live_etas map so REST polls don't erase it
        eta_key = f"{run_id}_{stop_id}"
        self.live_etas[eta_key] = {
            "eta": eta_str,
            "eta_minutes": eta_minutes,
            "planned_time": planned_str,
        }

        # Update matching stop in memory
        updated = False
        students = self.data.get("students", []) if self.data else []
        for student in students:
            run_info = get_field(student, "runInfo", [])
            for run in run_info:
                if get_field(run, "runId") == run_id:
                    stops = get_field(run, "stopsInfo", [])
                    for stop in stops:
                        if get_field(stop, "stopId") == stop_id:
                            # Update stopTime to the new ETA timestamp
                            stop["stopTime"] = eta_str
                            stop["etaMinutes"] = eta_minutes
                            stop["tylerEta"] = eta_str
                            stop["tylerEtaMinutes"] = eta_minutes
                            updated = True
                            
        if updated:
            # Notify Home Assistant that data has updated
            self.async_update_listeners()

    async def _async_update_data(self) -> Dict[str, Any]:

        """Fetch latest student and bus data dynamically."""
        now = dt_util.now()
        
        try:
            # 1. Fetch students & schedules
            try:
                students = await self.api.async_get_students()
            except MyRideAPIError:
                # Token expired or invalid, attempt self-healing Cognito login
                _LOGGER.info("Session expired or invalid, attempting Cognito re-login")
                await self.api.async_login(self.username, self.password)
                students = await self.api.async_get_students()
                
        except (MyRideAuthError, MyRideAPIError) as err:
            raise UpdateFailed(f"Failed to communicate with My Ride K-12 API: {err}") from err

        # Re-apply any live ETAs from SignalR that are currently stored
        for student in students:
            run_info = get_field(student, "runInfo", [])
            for run in run_info:
                r_id = get_field(run, "runId")
                stops = get_field(run, "stopsInfo", [])
                for stop in stops:
                    s_id = get_field(stop, "stopId")
                    eta_key = f"{r_id}_{s_id}"
                    if eta_key in self.live_etas:
                        live_info = self.live_etas[eta_key]
                        stop["stopTime"] = live_info["eta"]
                        stop["etaMinutes"] = live_info["eta_minutes"]
                        stop["tylerEta"] = live_info["eta"]
                        stop["tylerEtaMinutes"] = live_info["eta_minutes"]


        # 2. Check for active routes
        has_active_run = False
        for student in students:
            run_info = get_field(student, "runInfo", [])
            for run in run_info:
                stops = get_field(run, "stopsInfo", [])
                if not stops:
                    continue

                stop_times = []
                for stop in stops:
                    time_str = get_field(stop, "plannedStopTime") or get_field(stop, "stopTime")
                    if time_str:
                        try:
                            parsed_dt = dt_util.parse_datetime(time_str)
                            if parsed_dt:
                                # Construct timezone-aware stop time for today
                                stop_time_today = datetime(
                                    year=now.year,
                                    month=now.month,
                                    day=now.day,
                                    hour=parsed_dt.hour,
                                    minute=parsed_dt.minute,
                                    second=parsed_dt.second,
                                    microsecond=parsed_dt.microsecond,
                                    tzinfo=now.tzinfo
                                )
                                stop_times.append(stop_time_today)
                        except Exception: # pylint: disable=broad-except
                            pass

                if not stop_times:
                    continue

                start_time = min(stop_times)
                end_time = max(stop_times)

                # Check if running today
                running_days = get_field(run, "runningDays", [])
                is_running_today = False
                today_date_str = now.date().isoformat()

                for day in running_days:
                    if today_date_str in day:
                        is_running_today = True
                        break

                if not running_days:
                    # Fallback to weekday matching (MTWRF)
                    days_str = get_field(run, "days") or ""
                    weekday_map = {0: "M", 1: "T", 2: "W", 3: "R", 4: "F", 5: "S", 6: "U"}
                    current_weekday_char = weekday_map[now.weekday()]
                    if current_weekday_char in days_str:
                        is_running_today = True

                if is_running_today:
                    # Match buffer - start polling 30 mins before, stop 30 mins after
                    start_limit = start_time - timedelta(minutes=30)
                    end_limit = end_time + timedelta(minutes=30)
                    if start_limit <= now <= end_limit:
                        has_active_run = True
                        break
            if has_active_run:
                break

        # 3. Adjust polling interval dynamically
        new_interval = (
            timedelta(seconds=DEFAULT_POLL_INTERVAL_ACTIVE)
            if has_active_run
            else timedelta(seconds=DEFAULT_POLL_INTERVAL_PASSIVE)
        )
        if self.update_interval != new_interval:
            _LOGGER.info("Switching My Ride K-12 poll frequency to %s", new_interval)
            self.update_interval = new_interval

        # 4. Try fetching REST API bus coordinates as a fallback/sync method,
        # but don't fail if the REST endpoint returns 500.
        buses = []
        if has_active_run or (now - self.last_bus_fetch > timedelta(seconds=DEFAULT_POLL_INTERVAL_PASSIVE)):
            try:
                buses = await self.api.async_get_buses()
                self.last_bus_fetch = now
                for bus in buses:
                    uid = get_field(bus, "assetUniqueId")
                    if uid:
                        self.buses[uid] = bus
            except MyRideAPIError as err:
                _LOGGER.debug("Could not fetch active bus locations via REST API (this is normal if district uses WebSocket only): %s", err)
                buses = list(self.buses.values())
        else:
            buses = list(self.buses.values())

        return {
            "students": students,
            "buses": list(self.buses.values()),
            "has_active_run": has_active_run,
        }

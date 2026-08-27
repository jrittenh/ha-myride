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
    get_field,
)
from .api import MyRideAPI, MyRideAuthError, MyRideAPIError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]

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
        self.signalr_connected = False
        self._signalr_task: Optional[asyncio.Task] = None

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
                    if resp.status != 200:
                        raise MyRideAPIError(f"SignalR negotiation failed with status {resp.status}")
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
        self.data["buses"] = list(self.buses.values())
        
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

        # Update matching stop in memory
        updated = False
        students = self.data.get("students", [])
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

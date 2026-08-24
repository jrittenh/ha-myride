"""The My Ride K-12 integration."""
import logging
from datetime import timedelta, datetime
from typing import Dict, Any, List

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
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
        self.last_bus_fetch: datetime = datetime.min.replace(tzinfo=dt_util.UTC)

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
            for run in student.get("RunInfo", []):
                stops = run.get("StopsInfo", [])
                if not stops:
                    continue

                stop_times = []
                for stop in stops:
                    time_str = stop.get("PlannedStopTime") or stop.get("StopTime")
                    if time_str:
                        try:
                            parsed_dt = dt_util.parse_datetime(time_str)
                            if parsed_dt:
                                stop_times.append(parsed_dt)
                        except Exception: # pylint: disable=broad-except
                            pass

                if not stop_times:
                    continue

                start_time = min(stop_times)
                end_time = max(stop_times)

                # Check if running today
                running_days = run.get("RunningDays", [])
                is_running_today = False
                today_date_str = now.date().isoformat()

                for day in running_days:
                    if today_date_str in day:
                        is_running_today = True
                        break

                if not running_days:
                    # Fallback to weekday matching (MTWRF)
                    days_str = run.get("Days") or ""
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

        # 4. Fetch bus locations
        # Poll buses every active interval (30s) when run is active,
        # or fall back to passive interval (15 mins) when idle.
        buses = []
        if has_active_run or (now - self.last_bus_fetch > timedelta(seconds=DEFAULT_POLL_INTERVAL_PASSIVE)):
            try:
                buses = await self.api.async_get_buses()
                self.last_bus_fetch = now
            except MyRideAPIError as err:
                _LOGGER.warning("Could not fetch active bus locations: %s", err)
                # Keep previous data if fetch fails during transient network issues
                buses = self.data.get("buses", []) if self.data else []
        else:
            buses = self.data.get("buses", []) if self.data else []

        return {
            "students": students,
            "buses": buses,
            "has_active_run": has_active_run,
        }

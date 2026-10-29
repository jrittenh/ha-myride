"""Device tracker platform for My Ride K-12 integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import DOMAIN, get_field, DEFAULT_GPS_ACCURACY, get_run_display_name, get_time_suffix
from .__init__ import MyRideDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up My Ride K-12 bus trackers from config entry."""
    coordinator: MyRideDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Clean up obsolete physical bus trackers from Home Assistant's entity registry
    try:
        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        for reg_entry in entries:
            # Purge any legacy device tracker whose unique_id is not a student bus tracker
            if reg_entry.domain == "device_tracker" and not reg_entry.unique_id.endswith("_bus_tracker"):
                _LOGGER.info(
                    "Cleaning up obsolete device tracker from registry: %s (unique_id: %s)",
                    reg_entry.entity_id,
                    reg_entry.unique_id,
                )
                registry.async_remove(reg_entry.entity_id)
    except Exception as err:
        _LOGGER.debug("Could not clean up entity registry: %s", err)

    entities = []
    students = get_field(coordinator.data, "students", [])

    for student in students:
        student_id = get_field(student, "studentId")
        if student_id is None:
            continue
        first_name = get_field(student, "firstName", "")
        last_name = get_field(student, "lastName", "")
        student_name = f"{first_name} {last_name}".strip()

        run_info = get_field(student, "runInfo", [])
        for run in run_info:
            run_id = get_field(run, "runId")
            if run_id is None:
                continue

            # Add dynamic student route tracker (follows vehicle swaps automatically)
            entities.append(
                MyRideStudentBusTracker(coordinator, student_id, student_name, run_id)
            )

    async_add_entities(entities)


def _compute_staleness(log_time_str: Optional[str]) -> tuple[bool, Optional[int]]:
    """Compute whether location telemetry is stale (>30 mins) and age in minutes."""
    if not log_time_str:
        return True, None
    try:
        log_dt = dt_util.parse_datetime(log_time_str)
        if log_dt:
            now = dt_util.now()
            age = now - log_dt
            age_minutes = max(0, int(age.total_seconds() / 60))
            is_stale = age > timedelta(minutes=30)
            return is_stale, age_minutes
    except Exception:
        pass
    return True, None


class MyRideStudentBusTracker(CoordinatorEntity[MyRideDataUpdateCoordinator], TrackerEntity):
    """Device tracker dynamically tracking the bus assigned to a student's route."""

    def __init__(
        self,
        coordinator: MyRideDataUpdateCoordinator,
        student_id: int,
        student_name: str,
        run_id: int,
    ) -> None:
        """Initialize student route bus tracker."""
        super().__init__(coordinator)
        self.student_id = student_id
        self.student_name = student_name
        self.run_id = run_id

    def _get_run(self) -> Optional[Dict[str, Any]]:
        """Retrieve run data from coordinator data."""
        students = get_field(self.coordinator.data, "students", [])
        student = next((s for s in students if get_field(s, "studentId") == self.student_id), None)
        if not student:
            return None
        run_info = get_field(student, "runInfo", [])
        return next((r for r in run_info if get_field(r, "runId") == self.run_id), None)

    def _get_all_runs(self) -> List[Dict[str, Any]]:
        """Retrieve all runs for this student from coordinator data."""
        students = get_field(self.coordinator.data, "students", [])
        student = next((s for s in students if get_field(s, "studentId") == self.student_id), None)
        if not student:
            return []
        return get_field(student, "runInfo", []) or []

    def _get_bus_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve active bus data for this run, dynamically resolving on bus swaps."""
        run = self._get_run()
        if not run:
            return None
        vehicle_id = get_field(run, "activeVehicle") or get_field(run, "assetUniqueId")
        if not vehicle_id:
            return None
        buses = get_field(self.coordinator.data, "buses", [])
        return next((b for b in buses if get_field(b, "assetUniqueId") == vehicle_id), None)

    @property
    def name(self) -> str:
        """Return the name of the tracker."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        suffix = f" ({display_name})" if display_name else ""
        return f"{self.student_name} Bus{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this tracker."""
        return f"myride_{self.student_id}_{self.run_id}_bus_tracker"

    @property
    def suggested_object_id(self) -> str:
        """Return the suggested object ID for this entity."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        time_suffix = get_time_suffix(display_name)
        slug = self.student_name.lower().replace(" ", "_")
        return f"{slug}_bus{time_suffix}"

    @property
    def latitude(self) -> Optional[float]:
        """Return latitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "latitude")
        return None

    @property
    def longitude(self) -> Optional[float]:
        """Return longitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "longitude")
        return None

    @property
    def source_type(self) -> str:
        """Return the source type of the device tracker (GPS)."""
        return "gps"

    @property
    def gps_accuracy(self) -> int:
        """Return the GPS accuracy in meters."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "gpsAccuracy") or DEFAULT_GPS_ACCURACY
        return DEFAULT_GPS_ACCURACY

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return telemetry attributes of the bus, including swap and staleness tracking."""
        attrs: Dict[str, Any] = {}
        run = self._get_run()
        bus = self._get_bus_data()

        vehicle_id = (
            get_field(run, "activeVehicle")
            or get_field(run, "assetUniqueId")
            if run
            else None
        )
        attrs["assigned_vehicle_id"] = vehicle_id
        if run:
            attrs["bus_number"] = get_field(run, "busNumber")
            all_runs = self._get_all_runs()
            attrs["route_name"] = get_run_display_name(run, all_runs) or get_field(run, "runName") or get_field(run, "runDescription")
            attrs["driver_name"] = get_field(run, "driverName") or get_field(run, "rolloutDriverName")

        if not bus:
            attrs["is_stale"] = True
            attrs["location_age_minutes"] = None
            attrs["gps_accuracy"] = DEFAULT_GPS_ACCURACY
            return attrs

        attrs["speed"] = get_field(bus, "speed")
        attrs["heading"] = get_field(bus, "heading")
        log_time_str = get_field(bus, "logTime")
        attrs["last_log_time"] = log_time_str
        attrs["visible_run_name"] = get_field(bus, "visibleRunName")
        attrs["gps_accuracy"] = self.gps_accuracy

        is_stale, age_minutes = _compute_staleness(log_time_str)
        attrs["is_stale"] = is_stale
        attrs["location_age_minutes"] = age_minutes

        return attrs


class MyRideBusTracker(CoordinatorEntity[MyRideDataUpdateCoordinator], TrackerEntity):
    """Device tracker representing a physical school bus (legacy)."""

    def __init__(
        self,
        coordinator: MyRideDataUpdateCoordinator,
        vehicle_id: str
    ) -> None:
        """Initialize bus tracker."""
        super().__init__(coordinator)
        self.vehicle_id = vehicle_id

    def _get_bus_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve bus location data from coordinator data."""
        buses = get_field(self.coordinator.data, "buses", [])
        return next((b for b in buses if get_field(b, "assetUniqueId") == self.vehicle_id), None)

    @property
    def name(self) -> str:
        """Return the name of the tracker."""
        return f"My Ride K-12 Bus {self.vehicle_id}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this tracker."""
        return f"myride_{self.vehicle_id}_tracker"

    @property
    def latitude(self) -> Optional[float]:
        """Return latitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "latitude")
        return None

    @property
    def longitude(self) -> Optional[float]:
        """Return longitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "longitude")
        return None

    @property
    def source_type(self) -> str:
        """Return the source type of the device tracker (GPS)."""
        return "gps"

    @property
    def gps_accuracy(self) -> int:
        """Return the GPS accuracy in meters."""
        bus = self._get_bus_data()
        if bus:
            return get_field(bus, "gpsAccuracy") or DEFAULT_GPS_ACCURACY
        return DEFAULT_GPS_ACCURACY

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return telemetry attributes of the bus."""
        bus = self._get_bus_data()
        attrs: Dict[str, Any] = {}
        if not bus:
            attrs["is_stale"] = True
            attrs["location_age_minutes"] = None
            attrs["gps_accuracy"] = DEFAULT_GPS_ACCURACY
            return attrs

        attrs["speed"] = get_field(bus, "speed")
        attrs["heading"] = get_field(bus, "heading")
        log_time_str = get_field(bus, "logTime")
        attrs["last_log_time"] = log_time_str
        attrs["visible_run_name"] = get_field(bus, "visibleRunName")
        attrs["gps_accuracy"] = self.gps_accuracy

        is_stale, age_minutes = _compute_staleness(log_time_str)
        attrs["is_stale"] = is_stale
        attrs["location_age_minutes"] = age_minutes

        return attrs

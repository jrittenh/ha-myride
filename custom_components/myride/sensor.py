"""Sensor platform for My Ride K-12 integration."""
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, get_field
from .__init__ import MyRideDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Map EtaStatus enum from .NET decompiled code
# 0 = NoStatus, 1 = NotActive, 2 = OnTime, 3 = Early, 4 = Late, 5 = Completed, 6 = VehiclePastStop, 7 = NoVehicleLocation
STATUS_MAPPING = {
    0: "No Status",
    1: "Not Active",
    2: "On Time",
    3: "Early",
    4: "Late",
    5: "Completed",
    6: "Vehicle Past Stop",
    7: "No Vehicle Location"
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up My Ride K-12 sensors from config entry."""
    coordinator: MyRideDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
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

            entities.append(MyRideNextStopSensor(coordinator, student_id, student_name, run_id))
            entities.append(MyRideBusStatusSensor(coordinator, student_id, student_name, run_id))

    async_add_entities(entities)


class MyRideBaseSensor(CoordinatorEntity[MyRideDataUpdateCoordinator], SensorEntity):
    """Base class for My Ride K-12 sensors."""

    def __init__(
        self,
        coordinator: MyRideDataUpdateCoordinator,
        student_id: int,
        student_name: str,
        run_id: int
    ) -> None:
        """Initialize base sensor."""
        super().__init__(coordinator)
        self.student_id = student_id
        self.student_name = student_name
        self.run_id = run_id

    def _get_student(self) -> Optional[Dict[str, Any]]:
        """Retrieve student record from coordinator data."""
        students = get_field(self.coordinator.data, "students", [])
        return next((s for s in students if get_field(s, "studentId") == self.student_id), None)

    def _get_run(self) -> Optional[Dict[str, Any]]:
        """Retrieve run record from student."""
        student = self._get_student()
        if not student:
            return None
        run_info = get_field(student, "runInfo", [])
        return next((r for r in run_info if get_field(r, "runId") == self.run_id), None)


class MyRideNextStopSensor(MyRideBaseSensor):
    """Sensor reporting the next stop name and ETA for a student route."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        run = self._get_run()
        run_name = get_field(run, "runName") if run else None
        suffix = f" ({run_name})" if run_name else ""
        return f"{self.student_name} Next Bus Stop{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this sensor."""
        return f"myride_{self.student_id}_{self.run_id}_next_stop"

    @property
    def state(self) -> Optional[str]:
        """Return the next stop name."""
        run = self._get_run()
        if not run:
            return None
            
        stops = get_field(run, "stopsInfo", [])
        if not stops:
            return "No Stops"

        # Find the next incomplete stop, or default to first
        first_stop = stops[0]
        return get_field(first_stop, "locationName") or get_field(first_stop, "stopDescription") or get_field(first_stop, "stopAddressFull")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return metadata for the next stop."""
        run = self._get_run()
        attrs = {}
        if not run:
            return attrs

        stops = get_field(run, "stopsInfo", [])
        if stops:
            first_stop = stops[0]
            attrs["planned_time"] = get_field(first_stop, "plannedStopTime") or get_field(first_stop, "stopTime")
            attrs["eta_minutes"] = get_field(first_stop, "etaMinutes", 0)
            attrs["stop_address"] = get_field(first_stop, "stopAddressFull")
            attrs["stop_id"] = get_field(first_stop, "stopId")
            
        attrs["bus_number"] = get_field(run, "busNumber")
        attrs["route_name"] = get_field(run, "runName") or get_field(run, "runDescription")
        
        return attrs


class MyRideBusStatusSensor(MyRideBaseSensor):
    """Sensor reporting the bus delay / status (On Time, Late, etc.)."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        run = self._get_run()
        run_name = get_field(run, "runName") if run else None
        suffix = f" ({run_name})" if run_name else ""
        return f"{self.student_name} Bus Status{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this sensor."""
        return f"myride_{self.student_id}_{self.run_id}_bus_status"

    @property
    def state(self) -> Optional[str]:
        """Return the mapped status."""
        run = self._get_run()
        if not run:
            return "Unknown"
        status_code = get_field(run, "vehicleStatus", 0)
        return STATUS_MAPPING.get(status_code, "Unknown")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return metadata for the bus status."""
        run = self._get_run()
        attrs = {}
        if not run:
            return attrs

        attrs["bus_number"] = get_field(run, "busNumber")
        attrs["driver_name"] = get_field(run, "driverName") or get_field(run, "rolloutDriverName")
        
        return attrs

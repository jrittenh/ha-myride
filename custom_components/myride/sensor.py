"""Sensor platform for My Ride K-12 integration."""
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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

    students = coordinator.data.get("students", [])
    for student in students:
        student_id = student.get("StudentId")
        student_name = f"{student.get('FirstName', '')} {student.get('LastName', '')}".strip()
        
        for run in student.get("RunInfo", []):
            run_id = run.get("RunId")
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
        students = self.coordinator.data.get("students", [])
        return next((s for s in students if s.get("StudentId") == self.student_id), None)

    def _get_run(self) -> Optional[Dict[str, Any]]:
        """Retrieve run record from student."""
        student = self._get_student()
        if not student:
            return None
        return next((r for r in student.get("RunInfo", []) if r.get("RunId") == self.run_id), None)


class MyRideNextStopSensor(MyRideBaseSensor):
    """Sensor reporting the next stop name and ETA for a student route."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.student_name} Next Bus Stop"

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
            
        stops = run.get("StopsInfo", [])
        if not stops:
            return "No Stops"

        # Find the next incomplete stop, or default to first
        # In this API, StopsInfo is chronological.
        # Let's return the first stop's name for simplicity or parse
        first_stop = stops[0]
        return first_stop.get("LocationName") or first_stop.get("StopDescription") or first_stop.get("StopAddressFull")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return metadata for the next stop."""
        run = self._get_run()
        attrs = {}
        if not run:
            return attrs

        stops = run.get("StopsInfo", [])
        if stops:
            first_stop = stops[0]
            attrs["planned_time"] = first_stop.get("PlannedStopTime") or first_stop.get("StopTime")
            attrs["eta_minutes"] = first_stop.get("EtaMinutes", 0)
            attrs["stop_address"] = first_stop.get("StopAddressFull")
            attrs["stop_id"] = first_stop.get("StopId")
            
        attrs["bus_number"] = run.get("BusNumber")
        attrs["route_name"] = run.get("RunName") or run.get("RunDescription")
        
        return attrs


class MyRideBusStatusSensor(MyRideBaseSensor):
    """Sensor reporting the bus delay / status (On Time, Late, etc.)."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.student_name} Bus Status"

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
        status_code = run.get("VehicleStatus", 0)
        return STATUS_MAPPING.get(status_code, "Unknown")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return metadata for the bus status."""
        run = self._get_run()
        attrs = {}
        if not run:
            return attrs

        attrs["bus_number"] = run.get("BusNumber")
        attrs["driver_name"] = run.get("DriverName") or run.get("RolloutDriverName")
        
        return attrs

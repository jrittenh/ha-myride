"""Device tracker platform for My Ride K-12 integration."""
import logging
from typing import Any, Dict, Optional

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .__init__ import MyRideDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up My Ride K-12 bus trackers from config entry."""
    coordinator: MyRideDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    students = coordinator.data.get("students", [])
    tracked_vehicles = set()

    for student in students:
        student_id = student.get("StudentId")
        for run in student.get("RunInfo", []):
            run_id = run.get("RunId")
            vehicle_id = run.get("ActiveVehicle")
            
            if not vehicle_id or not run_id:
                continue

            # Avoid adding duplicate trackers for the same vehicle across different students
            key = (student_id, run_id, vehicle_id)
            if key not in tracked_vehicles:
                entities.append(MyRideBusTracker(coordinator, student_id, run_id, vehicle_id))
                tracked_vehicles.add(key)

    async_add_entities(entities)


class MyRideBusTracker(CoordinatorEntity[MyRideDataUpdateCoordinator], TrackerEntity):
    """Device tracker representing a school bus."""

    def __init__(
        self,
        coordinator: MyRideDataUpdateCoordinator,
        student_id: int,
        run_id: int,
        vehicle_id: str
    ) -> None:
        """Initialize bus tracker."""
        super().__init__(coordinator)
        self.student_id = student_id
        self.run_id = run_id
        self.vehicle_id = vehicle_id

    def _get_bus_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve bus location data from coordinator data."""
        buses = self.coordinator.data.get("buses", [])
        return next((b for b in buses if b.get("AssetUniqueId") == self.vehicle_id), None)

    @property
    def name(self) -> str:
        """Return the name of the tracker."""
        return f"My Ride K-12 Bus {self.vehicle_id}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this tracker."""
        return f"myride_{self.student_id}_{self.run_id}_{self.vehicle_id}_tracker"

    @property
    def latitude(self) -> Optional[float]:
        """Return latitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return bus.get("Latitude")
        return None

    @property
    def longitude(self) -> Optional[float]:
        """Return longitude value of the bus."""
        bus = self._get_bus_data()
        if bus:
            return bus.get("Longitude")
        return None

    @property
    def source_type(self) -> str:
        """Return the source type of the device tracker (GPS)."""
        return "gps"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return telemetry attributes of the bus."""
        bus = self._get_bus_data()
        attrs = {}
        if not bus:
            return attrs

        attrs["speed"] = bus.get("Speed")
        attrs["heading"] = bus.get("Heading")
        attrs["last_log_time"] = bus.get("LogTime")
        attrs["visible_run_name"] = bus.get("VisibleRunName")
        
        return attrs

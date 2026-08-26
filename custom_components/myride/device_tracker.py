"""Device tracker platform for My Ride K-12 integration."""
import logging
from typing import Any, Dict, Optional

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, get_field
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

    students = get_field(coordinator.data, "students", [])
    tracked_vehicles = set()

    for student in students:
        run_info = get_field(student, "runInfo", [])
        for run in run_info:
            vehicle_id = get_field(run, "activeVehicle")
            if not vehicle_id:
                continue

            # Deduplicate by vehicle_id so we only register one tracker per physical bus
            if vehicle_id not in tracked_vehicles:
                entities.append(MyRideBusTracker(coordinator, vehicle_id))
                tracked_vehicles.add(vehicle_id)

    async_add_entities(entities)


class MyRideBusTracker(CoordinatorEntity[MyRideDataUpdateCoordinator], TrackerEntity):
    """Device tracker representing a school bus."""

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
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return telemetry attributes of the bus."""
        bus = self._get_bus_data()
        attrs = {}
        if not bus:
            return attrs

        attrs["speed"] = get_field(bus, "speed")
        attrs["heading"] = get_field(bus, "heading")
        attrs["last_log_time"] = get_field(bus, "logTime")
        attrs["visible_run_name"] = get_field(bus, "visibleRunName")
        
        return attrs

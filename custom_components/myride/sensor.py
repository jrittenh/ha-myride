"""Sensor platform for My Ride K-12 integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    get_field,
    get_run_display_name,
    get_time_suffix,
    haversine_distance,
    meters_to_miles,
    meters_to_feet,
)
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
            entities.append(MyRideDistanceSensor(coordinator, student_id, student_name, run_id))

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

    def _get_all_runs(self) -> List[Dict[str, Any]]:
        """Retrieve all runs for this student from coordinator data."""
        student = self._get_student()
        if not student:
            return []
        return get_field(student, "runInfo", []) or []

    def _get_bus_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve bus location data from coordinator data."""
        run = self._get_run()
        if not run:
            return None
        vehicle_id = get_field(run, "activeVehicle") or get_field(run, "assetUniqueId")
        if not vehicle_id:
            return None
        buses = get_field(self.coordinator.data, "buses", [])
        return next((b for b in buses if get_field(b, "assetUniqueId") == vehicle_id), None)

    def _get_upcoming_stops(self, run: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filter stops to only include upcoming stops based on proximity completion and schedule."""
        stops = get_field(run, "stopsInfo", [])
        if not stops:
            return []

        completed = self.coordinator.get_completed_stops(self.run_id)
        # Filter out stops marked completed by proximity arrival
        uncompleted = [s for s in stops if get_field(s, "stopId") not in completed]
        if not uncompleted and completed:
            # All stops in this run were reached/completed
            return []

        # If bus has live GPS and is active, return remaining uncompleted stops in sequence order
        bus = self._get_bus_data()
        if bus and get_field(bus, "latitude") is not None:
            return uncompleted

        # Fallback when bus is not active or hasn't started:
        # filter out stops that are far in the past (> 45 mins past planned time)
        now = dt_util.now()
        upcoming = []
        for stop in uncompleted:
            time_str = get_field(stop, "plannedStopTime") or get_field(stop, "stopTime")
            if not time_str:
                upcoming.append(stop)
                continue
            try:
                parsed_dt = dt_util.parse_datetime(time_str)
                if parsed_dt:
                    stop_dt = datetime(
                        year=now.year,
                        month=now.month,
                        day=now.day,
                        hour=parsed_dt.hour,
                        minute=parsed_dt.minute,
                        second=parsed_dt.second,
                        microsecond=parsed_dt.microsecond,
                        tzinfo=now.tzinfo
                    )
                    if stop_dt >= now - timedelta(minutes=45):
                        upcoming.append(stop)
            except Exception:
                upcoming.append(stop)

        return upcoming if upcoming else uncompleted


class MyRideNextStopSensor(MyRideBaseSensor):
    """Sensor reporting the next stop name and ETA for a student route."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        suffix = f" ({display_name})" if display_name else ""
        return f"{self.student_name} Next Bus Stop{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this sensor."""
        return f"myride_{self.student_id}_{self.run_id}_next_stop"

    @property
    def suggested_object_id(self) -> str:
        """Return the suggested object ID for this entity."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        time_suffix = get_time_suffix(display_name)
        slug = self.student_name.lower().replace(" ", "_")
        return f"{slug}_next_bus_stop{time_suffix}"

    @property
    def state(self) -> Optional[str]:
        """Return the next stop name or completion status."""
        run = self._get_run()
        if not run:
            return None
            
        stops = self._get_upcoming_stops(run)
        if not stops:
            completed = self.coordinator.get_completed_stops(self.run_id)
            if completed:
                return "Completed"
            return "No Stops"

        first_stop = stops[0]
        return get_field(first_stop, "locationName") or get_field(first_stop, "stopDescription") or get_field(first_stop, "stopAddressFull")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return metadata and telemetry for the next stop."""
        run = self._get_run()
        attrs = {}
        if not run:
            return attrs

        stops = self._get_upcoming_stops(run)
        bus = self._get_bus_data()
        completed = self.coordinator.get_completed_stops(self.run_id)

        attrs["stops_completed_prior"] = len(completed)
        attrs["stops_remaining"] = len(stops)

        if stops:
            first_stop = stops[0]
            stop_id = get_field(first_stop, "stopId")
            attrs["planned_time"] = get_field(first_stop, "plannedStopTime") or get_field(first_stop, "stopTime")
            attrs["tyler_eta"] = get_field(first_stop, "tylerEta") or get_field(first_stop, "stopTime")
            eta_mins = get_field(first_stop, "tylerEtaMinutes") or get_field(first_stop, "etaMinutes", 0)
            attrs["eta_minutes"] = eta_mins
            attrs["tyler_eta_minutes"] = eta_mins
            attrs["stop_address"] = get_field(first_stop, "stopAddressFull")

            attrs["stop_id"] = stop_id
            attrs["stop_lat"] = get_field(first_stop, "stopLat")
            attrs["stop_lon"] = get_field(first_stop, "stopLong")

            # Calculate live distance if bus coordinates and stop coordinates are available
            if bus:
                bus_lat = get_field(bus, "latitude")
                bus_lon = get_field(bus, "longitude")
                stop_lat = get_field(first_stop, "stopLat")
                stop_lon = get_field(first_stop, "stopLong")
                if bus_lat is not None and bus_lon is not None and stop_lat is not None and stop_lon is not None:
                    dist_m = haversine_distance(bus_lat, bus_lon, stop_lat, stop_lon)
                    attrs["distance_to_stop_meters"] = round(dist_m, 1)
                    attrs["distance_to_stop_miles"] = round(meters_to_miles(dist_m), 2)
                    attrs["distance_to_stop_feet"] = int(meters_to_feet(dist_m))
                    if stop_id is not None:
                        attrs["is_approaching"] = self.coordinator.get_stop_distance_trend(
                            self.run_id, stop_id, dist_m
                        )
                    attrs["bus_speed"] = get_field(bus, "speed")
                    attrs["bus_heading"] = get_field(bus, "heading")

        attrs["bus_number"] = get_field(run, "busNumber")
        all_runs = self._get_all_runs()
        attrs["route_name"] = get_run_display_name(run, all_runs) or get_field(run, "runName") or get_field(run, "runDescription")
        attrs["active_vehicle"] = get_field(run, "activeVehicle") or get_field(run, "assetUniqueId")
        
        return attrs


class MyRideBusStatusSensor(MyRideBaseSensor):
    """Sensor reporting the bus delay / status (On Time, Late, etc.)."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        suffix = f" ({display_name})" if display_name else ""
        return f"{self.student_name} Bus Status{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this sensor."""
        return f"myride_{self.student_id}_{self.run_id}_bus_status"

    @property
    def suggested_object_id(self) -> str:
        """Return the suggested object ID for this entity."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        time_suffix = get_time_suffix(display_name)
        slug = self.student_name.lower().replace(" ", "_")
        return f"{slug}_bus_status{time_suffix}"

    @property
    def state(self) -> Optional[str]:
        """Return the mapped status."""
        run = self._get_run()
        if not run:
            return "Unknown"
        stops = self._get_upcoming_stops(run)
        completed = self.coordinator.get_completed_stops(self.run_id)
        if not stops and completed:
            return "Completed"
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


class MyRideDistanceSensor(MyRideBaseSensor):
    """Sensor reporting the distance from the bus to the next stop in miles."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        suffix = f" ({display_name})" if display_name else ""
        return f"{self.student_name} Bus Distance to Next Stop{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this sensor."""
        return f"myride_{self.student_id}_{self.run_id}_distance"

    @property
    def suggested_object_id(self) -> str:
        """Return the suggested object ID for this entity."""
        run = self._get_run()
        all_runs = self._get_all_runs()
        display_name = get_run_display_name(run, all_runs) if run else ""
        time_suffix = get_time_suffix(display_name)
        slug = self.student_name.lower().replace(" ", "_")
        return f"{slug}_bus_distance_to_next_stop{time_suffix}"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "mi"

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "mi"

    @property
    def state(self) -> Optional[float]:
        """Return the distance to the next stop in miles."""
        bus = self._get_bus_data()
        run = self._get_run()
        if not bus or not run:
            return None

        stops = self._get_upcoming_stops(run)
        if not stops:
            return None

        first_stop = stops[0]
        bus_lat = get_field(bus, "latitude")
        bus_lon = get_field(bus, "longitude")
        stop_lat = get_field(first_stop, "stopLat")
        stop_lon = get_field(first_stop, "stopLong")
        if bus_lat is None or bus_lon is None or stop_lat is None or stop_lon is None:
            return None

        dist_m = haversine_distance(bus_lat, bus_lon, stop_lat, stop_lon)
        return round(meters_to_miles(dist_m), 2)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra attributes for distance."""
        attrs = {}
        bus = self._get_bus_data()
        run = self._get_run()
        if not bus or not run:
            return attrs

        stops = self._get_upcoming_stops(run)
        if not stops:
            return attrs

        first_stop = stops[0]
        stop_id = get_field(first_stop, "stopId")
        bus_lat = get_field(bus, "latitude")
        bus_lon = get_field(bus, "longitude")
        stop_lat = get_field(first_stop, "stopLat")
        stop_lon = get_field(first_stop, "stopLong")
        if bus_lat is not None and bus_lon is not None and stop_lat is not None and stop_lon is not None:
            dist_m = haversine_distance(bus_lat, bus_lon, stop_lat, stop_lon)
            attrs["distance_meters"] = round(dist_m, 1)
            attrs["distance_feet"] = int(meters_to_feet(dist_m))
            if stop_id is not None:
                attrs["is_approaching"] = self.coordinator.get_stop_distance_trend(
                    self.run_id, stop_id, dist_m
                )
        attrs["next_stop"] = get_field(first_stop, "locationName") or get_field(first_stop, "stopDescription")
        return attrs


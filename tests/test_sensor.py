import pytest
from unittest.mock import MagicMock
from custom_components.myride.sensor import (
    MyRideNextStopSensor,
    MyRideBusStatusSensor,
    MyRideDistanceSensor,
)

def create_mock_coordinator(student_data, bus_data=None, completed_stops=None):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.data = {
        "students": student_data,
        "buses": bus_data or [],
        "has_active_run": False
    }
    completed_map = completed_stops or {}
    coordinator.get_completed_stops = MagicMock(side_effect=lambda run_id: completed_map.get(run_id, set()))
    coordinator.get_stop_distance_trend = MagicMock(return_value=True)
    return coordinator

@pytest.mark.asyncio
async def test_sensors_state_mapping():
    """Test My Ride K-12 sensors parse API payload and report correct states and attributes."""
    student_data = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 999,
                    "RunName": "Route 10 AM",
                    "BusNumber": "Bus 42",
                    "RolloutBusNumber": "Bus 42",
                    "AssetUniqueId": "VEHICLE42",
                    "DriverName": "John Driver",
                    "VehicleStatus": 2, # OnTime
                    "StopsInfo": [
                        {
                            "StopId": 888,
                            "StopDescription": "Corner of 5th and Main",
                            "StopLat": 34.0522,
                            "StopLong": -118.2437,
                            "PlannedStopTime": "2026-08-24T10:00:00Z",
                            "StopTime": "2026-08-24T10:00:00Z",
                            "EtaMinutes": 5
                        }
                    ]
                }
            ]
        }
    ]
    
    coordinator = create_mock_coordinator(student_data)
    
    # 1. Test Next Stop Sensor
    next_stop_sensor = MyRideNextStopSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    assert next_stop_sensor.name == "Jane Doe Next Bus Stop (Route 10 AM)"
    assert next_stop_sensor.state == "Corner of 5th and Main"
    assert next_stop_sensor.extra_state_attributes["planned_time"] == "2026-08-24T10:00:00Z"
    assert next_stop_sensor.extra_state_attributes["eta_minutes"] == 5
    assert next_stop_sensor.extra_state_attributes["tyler_eta_minutes"] == 5
    assert next_stop_sensor.extra_state_attributes["bus_number"] == "Bus 42"
    assert next_stop_sensor.extra_state_attributes["route_name"] == "Route 10 AM"

    # 2. Test Bus Status Sensor
    bus_status_sensor = MyRideBusStatusSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    assert bus_status_sensor.name == "Jane Doe Bus Status (Route 10 AM)"
    assert bus_status_sensor.state == "On Time" # Mapped from 2 (OnTime)
    assert bus_status_sensor.extra_state_attributes["driver_name"] == "John Driver"
    assert bus_status_sensor.extra_state_attributes["bus_number"] == "Bus 42"

@pytest.mark.asyncio
async def test_distance_sensor_and_telemetry_attributes():
    """Test MyRideDistanceSensor and NextStopSensor calculate distance and proximity attributes."""
    student_data = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 999,
                    "RunName": "Route 10 AM",
                    "AssetUniqueId": "VEHICLE42",
                    "ActiveVehicle": "VEHICLE42",
                    "StopsInfo": [
                        {
                            "StopId": 888,
                            "StopDescription": "Corner of 5th and Main",
                            "StopLat": 34.0522,
                            "StopLong": -118.2437,
                        }
                    ]
                }
            ]
        }
    ]
    # Bus coordinates located ~93 meters away
    bus_data = [
        {
            "AssetUniqueId": "VEHICLE42",
            "Latitude": 34.0530,
            "Longitude": -118.2440,
            "Speed": 15,
            "Heading": 90,
        }
    ]

    coordinator = create_mock_coordinator(student_data, bus_data)

    dist_sensor = MyRideDistanceSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    assert dist_sensor.name == "Jane Doe Bus Distance to Next Stop (Route 10 AM)"
    assert dist_sensor.unit_of_measurement == "mi"
    assert dist_sensor.state is not None
    assert dist_sensor.state < 0.1  # ~93m is ~0.06 miles
    assert dist_sensor.extra_state_attributes["distance_meters"] > 80
    assert dist_sensor.extra_state_attributes["distance_feet"] > 250
    assert dist_sensor.extra_state_attributes["is_approaching"] is True

    next_stop_sensor = MyRideNextStopSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    attrs = next_stop_sensor.extra_state_attributes
    assert attrs["distance_to_stop_meters"] > 80
    assert attrs["is_approaching"] is True
    assert attrs["bus_speed"] == 15
    assert attrs["bus_heading"] == 90

@pytest.mark.asyncio
async def test_proximity_stop_advancement():
    """Test that stops advance when marked completed, and status transitions to Completed when all done."""
    student_data = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 999,
                    "RunName": "Route 10 AM",
                    "AssetUniqueId": "VEHICLE42",
                    "ActiveVehicle": "VEHICLE42",
                    "StopsInfo": [
                        {
                            "StopId": 101,
                            "StopDescription": "Stop 1",
                            "StopLat": 34.0522,
                            "StopLong": -118.2437,
                        },
                        {
                            "StopId": 102,
                            "StopDescription": "Stop 2",
                            "StopLat": 34.0600,
                            "StopLong": -118.2500,
                        }
                    ]
                }
            ]
        }
    ]

    # Case 1: Stop 1 completed -> advances to Stop 2
    coordinator = create_mock_coordinator(student_data, completed_stops={999: {101}})
    sensor = MyRideNextStopSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    assert sensor.state == "Stop 2"
    assert sensor.extra_state_attributes["stops_completed_prior"] == 1
    assert sensor.extra_state_attributes["stops_remaining"] == 1

    # Case 2: Both stops completed -> reports "Completed"
    coordinator_all_done = create_mock_coordinator(student_data, completed_stops={999: {101, 102}})
    sensor_done = MyRideNextStopSensor(coordinator_all_done, student_id=111, student_name="Jane Doe", run_id=999)
    assert sensor_done.state == "Completed"

    status_sensor = MyRideBusStatusSensor(coordinator_all_done, student_id=111, student_name="Jane Doe", run_id=999)
    assert status_sensor.state == "Completed"

@pytest.mark.asyncio
async def test_sensors_am_pm_fallback_naming():
    """Test that sensors append (AM) or (PM) when runName is blank."""
    student_data = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 101,
                    "RunName": "",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T07:15:00Z"}],
                },
                {
                    "RunId": 102,
                    "RunName": None,
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T14:45:00Z"}],
                }
            ]
        }
    ]
    coordinator = create_mock_coordinator(student_data)
    next_stop_am = MyRideNextStopSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=101)
    status_am = MyRideBusStatusSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=101)
    dist_am = MyRideDistanceSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=101)

    assert next_stop_am.name == "Jane Doe Next Bus Stop (AM)"
    assert status_am.name == "Jane Doe Bus Status (AM)"
    assert dist_am.name == "Jane Doe Bus Distance to Next Stop (AM)"

    next_stop_pm = MyRideNextStopSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=102)
    assert next_stop_pm.name == "Jane Doe Next Bus Stop (PM)"


@pytest.mark.asyncio
async def test_sensors_with_embedded_am_route_name():
    """Test sensor naming and suggested_object_id for route names containing embedded 'am'."""
    student_data = [
        {
            "StudentId": 555,
            "FirstName": "Pat",
            "LastName": "Lee",
            "RunInfo": [
                {
                    "RunId": 501,
                    "RunName": "Campus",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T07:30:00Z"}],
                },
                {
                    "RunId": 502,
                    "RunName": "Campus",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T15:00:00Z"}],
                },
            ],
        }
    ]
    coordinator = MagicMock()
    coordinator.data = {"students": student_data, "buses": [], "has_active_run": False}
    coordinator.get_completed_stops.return_value = set()

    sensor_am = MyRideNextStopSensor(coordinator, student_id=555, student_name="Pat Lee", run_id=501)
    sensor_pm = MyRideNextStopSensor(coordinator, student_id=555, student_name="Pat Lee", run_id=502)

    assert sensor_am.name == "Pat Lee Next Bus Stop (Campus AM)"
    assert sensor_am.suggested_object_id == "pat_lee_next_bus_stop_am"

    assert sensor_pm.name == "Pat Lee Next Bus Stop (Campus PM)"
    assert sensor_pm.suggested_object_id == "pat_lee_next_bus_stop_pm"




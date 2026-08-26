import pytest
from unittest.mock import MagicMock
from custom_components.myride.sensor import MyRideNextStopSensor, MyRideBusStatusSensor

def create_mock_coordinator(student_data):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.data = {
        "students": student_data,
        "buses": [],
        "has_active_run": False
    }
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
    assert next_stop_sensor.extra_state_attributes["bus_number"] == "Bus 42"
    assert next_stop_sensor.extra_state_attributes["route_name"] == "Route 10 AM"

    # 2. Test Bus Status Sensor
    # EtaStatus mapping in .NET decompiled:
    # 0 = NoStatus, 1 = NotActive, 2 = OnTime, 3 = Early, 4 = Late, 5 = Completed, 6 = VehiclePastStop, 7 = NoVehicleLocation
    bus_status_sensor = MyRideBusStatusSensor(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    assert bus_status_sensor.name == "Jane Doe Bus Status (Route 10 AM)"
    assert bus_status_sensor.state == "On Time" # Mapped from 2 (OnTime)
    assert bus_status_sensor.extra_state_attributes["driver_name"] == "John Driver"
    assert bus_status_sensor.extra_state_attributes["bus_number"] == "Bus 42"

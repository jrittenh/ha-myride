import pytest
from unittest.mock import MagicMock
from custom_components.myride.device_tracker import MyRideBusTracker

def create_mock_coordinator(student_data, bus_data):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.data = {
        "students": student_data,
        "buses": bus_data,
        "has_active_run": True
    }
    return coordinator

@pytest.mark.asyncio
async def test_device_tracker_states():
    """Test My Ride K-12 device tracker parses coordinates and telemetry correctly."""
    student_data = [
        {
            "StudentId": 111,
            "RunInfo": [
                {
                    "RunId": 999,
                    "RunName": "Route 10 AM",
                    "BusNumber": "Bus 42",
                    "AssetUniqueId": "VEHICLE42",
                    "ActiveVehicle": "VEHICLE42"
                }
            ]
        }
    ]
    
    bus_data = [
        {
            "AssetUniqueId": "VEHICLE42",
            "Latitude": 34.0530,
            "Longitude": -118.2440,
            "Heading": 180,
            "Speed": 25,
            "VisibleRunName": "Route 10 AM",
            "LogTime": "2026-08-24T07:32:00Z"
        }
    ]
    
    coordinator = create_mock_coordinator(student_data, bus_data)
    
    tracker = MyRideBusTracker(coordinator, vehicle_id="VEHICLE42")
    
    assert tracker.name == "My Ride K-12 Bus VEHICLE42"
    assert tracker.latitude == 34.0530
    assert tracker.longitude == -118.2440
    assert tracker.source_type == "gps"
    assert tracker.extra_state_attributes["speed"] == 25
    assert tracker.extra_state_attributes["heading"] == 180
    assert tracker.extra_state_attributes["last_log_time"] == "2026-08-24T07:32:00Z"

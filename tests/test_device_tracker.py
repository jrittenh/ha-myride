import pytest
from unittest.mock import MagicMock
from custom_components.myride.device_tracker import (
    MyRideBusTracker,
    MyRideStudentBusTracker,
    async_setup_entry,
)

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
    """Test My Ride K-12 physical bus tracker parses coordinates and telemetry correctly."""
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
    assert tracker.gps_accuracy == 15
    assert tracker.extra_state_attributes["gps_accuracy"] == 15
    assert tracker.extra_state_attributes["speed"] == 25
    assert tracker.extra_state_attributes["heading"] == 180
    assert tracker.extra_state_attributes["last_log_time"] == "2026-08-24T07:32:00Z"
    assert "is_stale" in tracker.extra_state_attributes

@pytest.mark.asyncio
async def test_student_bus_tracker_states():
    """Test MyRideStudentBusTracker associates with student route and reports telemetry."""
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
                    "ActiveVehicle": "VEHICLE42",
                    "DriverName": "John Driver",
                }
            ]
        }
    ]
    
    bus_data = [
        {
            "AssetUniqueId": "VEHICLE42",
            "Latitude": 34.0530,
            "Longitude": -118.2440,
            "Heading": 90,
            "Speed": 20,
            "VisibleRunName": "Route 10 AM",
            "LogTime": "2026-08-24T07:32:00Z"
        }
    ]
    
    coordinator = create_mock_coordinator(student_data, bus_data)
    tracker = MyRideStudentBusTracker(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    
    assert tracker.name == "Jane Doe Bus (Route 10 AM)"
    assert tracker.unique_id == "myride_111_999_bus_tracker"
    assert tracker.latitude == 34.0530
    assert tracker.longitude == -118.2440
    assert tracker.source_type == "gps"
    assert tracker.extra_state_attributes["assigned_vehicle_id"] == "VEHICLE42"
    assert tracker.extra_state_attributes["bus_number"] == "Bus 42"
    assert tracker.extra_state_attributes["driver_name"] == "John Driver"
    assert tracker.extra_state_attributes["route_name"] == "Route 10 AM"
    assert tracker.extra_state_attributes["speed"] == 20

@pytest.mark.asyncio
async def test_student_bus_tracker_bus_swap():
    """Test MyRideStudentBusTracker dynamically follows a substitute bus when a swap occurs."""
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
                    "ActiveVehicle": "SUB_BUS99",  # Swapped from VEHICLE42 to SUB_BUS99
                }
            ]
        }
    ]
    
    bus_data = [
        {
            "AssetUniqueId": "VEHICLE42",
            "Latitude": 34.0100,  # Old bus parked at depot
            "Longitude": -118.2100,
            "LogTime": "2026-08-24T06:00:00Z",
        },
        {
            "AssetUniqueId": "SUB_BUS99",
            "Latitude": 34.0555,  # Substitute bus actively on route
            "Longitude": -118.2455,
            "LogTime": "2026-08-24T07:35:00Z",
        }
    ]
    
    coordinator = create_mock_coordinator(student_data, bus_data)
    tracker = MyRideStudentBusTracker(coordinator, student_id=111, student_name="Jane Doe", run_id=999)
    
    # Verify tracker automatically routes to SUB_BUS99 coordinates
    assert tracker.latitude == 34.0555
    assert tracker.longitude == -118.2455
    assert tracker.extra_state_attributes["assigned_vehicle_id"] == "SUB_BUS99"

@pytest.mark.asyncio
async def test_device_tracker_async_setup_entry():
    """Test async_setup_entry registers both student route trackers and bus trackers."""
    student_data = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 999,
                    "RunName": "Route 10 AM",
                    "ActiveVehicle": "VEHICLE42",
                }
            ]
        }
    ]
    coordinator = create_mock_coordinator(student_data, [])
    mock_hass = MagicMock()
    mock_hass.data = {"myride": {"test_entry": coordinator}}
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    
    added_entities = []
    def async_add_entities(entities):
        added_entities.extend(entities)
        
    await async_setup_entry(mock_hass, mock_entry, async_add_entities)
    
    # Expect 1 student bus tracker and 1 physical vehicle tracker
    assert len(added_entities) == 2
    assert any(isinstance(e, MyRideStudentBusTracker) for e in added_entities)
    assert any(isinstance(e, MyRideBusTracker) for e in added_entities)

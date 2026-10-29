import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from custom_components.myride import MyRideDataUpdateCoordinator
from custom_components.myride.api import MyRideAPIError, MyRideAuthError
import homeassistant.util.dt as dt_util

@pytest.mark.asyncio
async def test_coordinator_passive_polling():
    """Test coordinator updates data and switches to passive interval when no active run is present."""
    mock_api = MagicMock()
    mock_api.async_get_students = AsyncMock(return_value=[
        {
            "StudentId": 111,
            "RunInfo": [
                {
                    "RunId": 999,
                    "Days": "MTWRF",
                    "RunningDays": [],
                    "StopsInfo": [
                        {
                            # Route is at 10 AM, but we'll mock current time to be 2 PM (inactive)
                            "StopTime": "2026-08-24T10:00:00Z", 
                        }
                    ]
                }
            ]
        }
    ])
    mock_api.async_get_buses = AsyncMock(return_value=[])
    
    mock_now = datetime(2026, 8, 24, 14, 0, 0, tzinfo=dt_util.UTC) # 2:00 PM
    with patch("homeassistant.util.dt.now", return_value=mock_now):
        coordinator = MyRideDataUpdateCoordinator(MagicMock(), mock_api, "test@example.com", "password")
        data = await coordinator._async_update_data()
        
        assert data["has_active_run"] is False
        assert coordinator.update_interval == timedelta(seconds=900)
        mock_api.async_get_buses.assert_called_once() # Fetched on startup/passive update

@pytest.mark.asyncio
async def test_coordinator_active_polling():
    """Test coordinator switches to active interval when an active run is detected right now."""
    mock_api = MagicMock()
    mock_api.async_get_students = AsyncMock(return_value=[
        {
            "StudentId": 111,
            "RunInfo": [
                {
                    "RunId": 999,
                    "Days": "MTWRF",
                    "RunningDays": ["2026-08-24T00:00:00Z"],
                    "StopsInfo": [
                        {
                            # Route is at 10:00 AM, current time is 9:45 AM (active)
                            "PlannedStopTime": "2026-08-24T10:00:00Z", 
                        }
                    ]
                }
            ]
        }
    ])
    mock_api.async_get_buses = AsyncMock(return_value=[{"AssetUniqueId": "BUS42"}])
    
    mock_now = datetime(2026, 8, 24, 9, 45, 0, tzinfo=dt_util.UTC) # 9:45 AM
    with patch("homeassistant.util.dt.now", return_value=mock_now):
        coordinator = MyRideDataUpdateCoordinator(MagicMock(), mock_api, "test@example.com", "password")
        data = await coordinator._async_update_data()
        
        assert data["has_active_run"] is True
        assert coordinator.update_interval == timedelta(seconds=30)
        mock_api.async_get_buses.assert_called_once()

@pytest.mark.asyncio
async def test_coordinator_self_healing():
    """Test coordinator attempts Cognito re-login if student API call fails with API error."""
    mock_api = MagicMock()
    # First call fails, second call succeeds after login
    mock_api.async_get_students = AsyncMock(side_effect=[
        MyRideAPIError("Unauthorized token"),
        [{"StudentId": 111, "RunInfo": []}]
    ])
    mock_api.async_login = AsyncMock()
    mock_api.async_get_buses = AsyncMock(return_value=[])
    
    coordinator = MyRideDataUpdateCoordinator(MagicMock(), mock_api, "test@example.com", "password")
    data = await coordinator._async_update_data()
    
    assert len(data["students"]) == 1
    mock_api.async_login.assert_called_once_with("test@example.com", "password")
    assert mock_api.async_get_students.call_count == 2

@pytest.mark.asyncio
async def test_coordinator_handle_new_location_proximity_and_event():
    """Test _handle_new_location marks stop completed on arrival within 150m and fires telemetry event."""
    mock_api = MagicMock()
    mock_hass = MagicMock()
    mock_hass.bus = MagicMock()

    coordinator = MyRideDataUpdateCoordinator(mock_hass, mock_api, "test@example.com", "password")
    coordinator.data = {
        "students": [
            {
                "StudentId": 111,
                "RunInfo": [
                    {
                        "RunId": 999,
                        "ActiveVehicle": "BUS42",
                        "StopsInfo": [
                            {
                                "StopId": 501,
                                "StopLat": 34.0522,
                                "StopLong": -118.2437,
                            }
                        ]
                    }
                ]
            }
        ],
        "buses": [],
        "has_active_run": True
    }

    # Location ~93 meters from stop 501 (within 150m threshold)
    bus_payload = {
        "AssetUniqueId": "BUS42",
        "Latitude": 34.0530,
        "Longitude": -118.2440,
        "Speed": 20,
        "Heading": 180,
        "VisibleRunName": "Route 10 AM",
        "LogTime": "2026-08-24T10:00:00Z"
    }

    coordinator._handle_new_location(bus_payload)

    # 1. Verify stop was added to completed_stops
    assert 501 in coordinator.get_completed_stops(999)

    # 2. Verify telemetry event was fired
    mock_hass.bus.async_fire.assert_called_once()
    event_name, event_data = mock_hass.bus.async_fire.call_args[0]
    assert event_name == "myride_telemetry_updated"
    assert event_data["vehicle_id"] == "BUS42"
    assert event_data["latitude"] == 34.0530
    assert event_data["longitude"] == -118.2440
    assert event_data["speed"] == 20

@pytest.mark.asyncio
async def test_coordinator_live_eta_preservation():
    """Test coordinator preserves live SignalR ETA across subsequent REST polls."""
    mock_api = MagicMock()
    # REST API returns static stop without live ETA
    mock_api.async_get_students = AsyncMock(return_value=[
        {
            "StudentId": 111,
            "RunInfo": [
                {
                    "RunId": 999,
                    "ActiveVehicle": "BUS42",
                    "Days": "MTWRF",
                    "RunningDays": [],
                    "StopsInfo": [
                        {
                            "StopId": 501,
                            "StopTime": "2026-08-24T08:00:00Z",
                            "PlannedStopTime": "2026-08-24T08:00:00Z",
                        }
                    ]
                }
            ]
        }
    ])
    mock_api.async_get_buses = AsyncMock(return_value=[])

    coordinator = MyRideDataUpdateCoordinator(MagicMock(), mock_api, "test@example.com", "password")
    coordinator.data = {"students": [], "buses": [], "has_active_run": False}

    # Simulate live ETA arrival over SignalR
    mock_now = datetime(2026, 8, 24, 7, 50, 0, tzinfo=dt_util.UTC)
    with patch("homeassistant.util.dt.now", return_value=mock_now):
        coordinator._handle_new_eta({
            "RunId": 999,
            "StopId": 501,
            "Eta": "2026-08-24T08:05:00Z",
            "PlannedTime": "2026-08-24T08:00:00Z",
        })

        # REST poll runs
        data = await coordinator._async_update_data()

        # Stop should retain live ETA rather than being overwritten by static REST data
        stop = data["students"][0]["RunInfo"][0]["StopsInfo"][0]
        assert stop["stopTime"] == "2026-08-24T08:05:00Z"
        assert stop["tylerEta"] == "2026-08-24T08:05:00Z"
        assert stop["etaMinutes"] == 15

@pytest.mark.asyncio
async def test_async_migrate_entity_ids():
    """Test _async_migrate_entity_ids renames collision _2 and unadorned entity IDs to _am and _pm."""
    from custom_components.myride.__init__ import _async_migrate_entity_ids
    from homeassistant.helpers import entity_registry as er

    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"

    students = [
        {
            "StudentId": 111,
            "FirstName": "Jane",
            "LastName": "Doe",
            "RunInfo": [
                {
                    "RunId": 101,
                    "RunName": "",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T07:30:00Z"}],
                },
                {
                    "RunId": 102,
                    "RunName": "",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T15:00:00Z"}],
                }
            ]
        }
    ]

    mock_reg = MagicMock()
    er.async_get.return_value = mock_reg

    # Existing entries with legacy names and _2 collision
    am_tracker = MagicMock()
    am_tracker.unique_id = "myride_111_101_bus_tracker"
    am_tracker.entity_id = "device_tracker.jane_doe_bus"

    pm_tracker = MagicMock()
    pm_tracker.unique_id = "myride_111_102_bus_tracker"
    pm_tracker.entity_id = "device_tracker.jane_doe_bus_2"

    er.async_entries_for_config_entry.return_value = [am_tracker, pm_tracker]
    mock_reg.async_get.return_value = None  # target IDs not in use

    _async_migrate_entity_ids(mock_hass, mock_entry, students)

    mock_reg.async_update_entity.assert_any_call("device_tracker.jane_doe_bus", new_entity_id="device_tracker.jane_doe_bus_am")
    mock_reg.async_update_entity.assert_any_call("device_tracker.jane_doe_bus_2", new_entity_id="device_tracker.jane_doe_bus_pm")


@pytest.mark.asyncio
async def test_async_migrate_entity_ids_route_name_with_am_word():
    """Test _async_migrate_entity_ids does not name a PM route _am just because name contains 'am'."""
    from custom_components.myride.__init__ import _async_migrate_entity_ids
    from homeassistant.helpers import entity_registry as er

    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"

    students = [
        {
            "StudentId": 222,
            "FirstName": "Alex",
            "LastName": "Smith",
            "RunInfo": [
                {
                    "RunId": 201,
                    "RunName": "Campus",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T07:45:00Z"}],
                },
                {
                    "RunId": 202,
                    "RunName": "Campus",
                    "StopsInfo": [{"plannedStopTime": "2026-10-28T15:15:00Z"}],
                }
            ]
        }
    ]

    mock_reg = MagicMock()
    er.async_get.return_value = mock_reg

    # Existing entries with legacy names
    am_tracker = MagicMock()
    am_tracker.unique_id = "myride_222_201_bus_tracker"
    am_tracker.entity_id = "device_tracker.alex_smith_bus"

    pm_tracker = MagicMock()
    pm_tracker.unique_id = "myride_222_202_bus_tracker"
    pm_tracker.entity_id = "device_tracker.alex_smith_bus_2"

    er.async_entries_for_config_entry.return_value = [am_tracker, pm_tracker]
    mock_reg.async_get.return_value = None

    _async_migrate_entity_ids(mock_hass, mock_entry, students)

    mock_reg.async_update_entity.assert_any_call("device_tracker.alex_smith_bus", new_entity_id="device_tracker.alex_smith_bus_am")
    mock_reg.async_update_entity.assert_any_call("device_tracker.alex_smith_bus_2", new_entity_id="device_tracker.alex_smith_bus_pm")




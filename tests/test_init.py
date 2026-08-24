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

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from custom_components.myride.api import MyRideAuthError, MyRideAPIError
from custom_components.myride.config_flow import MyRideConfigFlow

def create_flow():
    flow = MyRideConfigFlow()
    flow.hass = MagicMock()
    return flow

@pytest.mark.asyncio
async def test_user_step_init():
    """Test user step shows username/password form on initialization."""
    flow = create_flow()
    result = await flow.async_step_user()
    
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {}

@pytest.mark.asyncio
@patch("custom_components.myride.config_flow.MyRideAPI")
async def test_user_step_success_single_district(mock_api_class):
    """Test user step successfully registers single district immediately."""
    mock_api = MagicMock()
    mock_api.async_login = AsyncMock(return_value=["district-123"])
    mock_api_class.return_value = mock_api
    
    flow = create_flow()
    user_input = {"username": "test@example.com", "password": "password123"}
    
    result = await flow.async_step_user(user_input)
    
    assert result["type"] == "create_entry"
    assert result["title"] == "My Ride K-12 (district-123)"
    assert result["data"]["username"] == "test@example.com"
    assert result["data"]["password"] == "password123"
    assert result["data"]["district_id"] == "district-123"
    assert result["data"]["districts"] == ["district-123"]

@pytest.mark.asyncio
@patch("custom_components.myride.config_flow.MyRideAPI")
async def test_user_step_success_multiple_districts(mock_api_class):
    """Test user step with multiple districts shows district select form next."""
    mock_api = MagicMock()
    mock_api.async_login = AsyncMock(return_value=["district-1", "district-2"])
    mock_api_class.return_value = mock_api
    
    flow = create_flow()
    user_input = {"username": "test@example.com", "password": "password123"}
    
    result = await flow.async_step_user(user_input)
    
    assert result["type"] == "form"
    assert result["step_id"] == "select_district"
    assert flow._districts == ["district-1", "district-2"]
    
    # Test step_select_district selection
    select_result = await flow.async_step_select_district({"district_id": "district-2"})
    assert select_result["type"] == "create_entry"
    assert select_result["title"] == "My Ride K-12 (district-2)"
    assert select_result["data"]["district_id"] == "district-2"
    assert select_result["data"]["districts"] == ["district-1", "district-2"]

@pytest.mark.asyncio
@patch("custom_components.myride.config_flow.MyRideAPI")
async def test_user_step_auth_error(mock_api_class):
    """Test user step shows invalid_auth error on bad credentials."""
    mock_api = MagicMock()
    mock_api.async_login = AsyncMock(side_effect=MyRideAuthError("Incorrect password"))
    mock_api_class.return_value = mock_api
    
    flow = create_flow()
    user_input = {"username": "test@example.com", "password": "wrong-password"}
    
    result = await flow.async_step_user(user_input)
    
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}

@pytest.mark.asyncio
@patch("custom_components.myride.config_flow.MyRideAPI")
async def test_user_step_api_error(mock_api_class):
    """Test user step shows cannot_connect error on API problems."""
    mock_api = MagicMock()
    mock_api.async_login = AsyncMock(side_effect=MyRideAPIError("Network down"))
    mock_api_class.return_value = mock_api
    
    flow = create_flow()
    user_input = {"username": "test@example.com", "password": "password123"}
    
    result = await flow.async_step_user(user_input)
    
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}

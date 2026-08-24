import pytest
import jwt
import aiohttp
from unittest.mock import AsyncMock, MagicMock
from custom_components.myride.api import MyRideAPI, MyRideAuthError, MyRideAPIError

# Helper to generate mock token
def make_mock_token(groups):
    payload = {
        "cognito:groups": groups,
        "exp": 1999999999, # Far future
        "username": "test_user"
    }
    return jwt.encode(payload, "secret-long-enough-for-jwt-recommendations-32bytes", algorithm="HS256")

class MockResponse:
    def __init__(self, status, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self, *args, **kwargs):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.mark.asyncio
async def test_login_success():
    mock_token = make_mock_token(["district-12345"])
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.closed = False
    
    mock_session.post.return_value = MockResponse(
        status=200,
        json_data={
            "AuthenticationResult": {
                "AccessToken": "mock-access-token",
                "IdToken": mock_token,
                "RefreshToken": "mock-refresh-token",
                "ExpiresIn": 3600
            }
        }
    )
    
    api = MyRideAPI(session=mock_session)
    districts = await api.async_login("test@example.com", "password123")
    
    assert len(districts) == 1
    assert districts[0] == "district-12345"
    assert api.access_token == "mock-access-token"
    assert api.id_token == mock_token
    assert api.refresh_token == "mock-refresh-token"
    mock_session.post.assert_called_once()

@pytest.mark.asyncio
async def test_login_failure():
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.closed = False
    mock_session.post.return_value = MockResponse(
        status=400,
        json_data={
            "__type": "NotAuthorizedException",
            "message": "Incorrect username or password."
        }
    )
    
    api = MyRideAPI(session=mock_session)
    with pytest.raises(MyRideAuthError) as exc_info:
        await api.async_login("test@example.com", "wrong-password")
    assert "Incorrect username or password" in str(exc_info.value)
    mock_session.post.assert_called_once()

@pytest.mark.asyncio
async def test_get_students():
    mock_token = make_mock_token(["district-12345"])
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.closed = False
    
    mock_session.get.return_value = MockResponse(
        status=200,
        json_data=[
            {
                "StudentId": 111,
                "FirstName": "Jane",
                "LastName": "Doe",
                "UniqueId": "STU111",
                "RunInfo": [
                    {
                        "RunId": 999,
                        "RunName": "Route 10 AM",
                        "BusNumber": "Bus 42",
                        "AssetUniqueId": "VEHICLE42",
                        "StopsInfo": [
                            {
                                "StopId": 888,
                                "StopDescription": "Corner of 5th and Main",
                                "StopLat": 34.0522,
                                "StopLong": -118.2437,
                                "StopTime": "2026-08-24T07:30:00Z",
                                "StopLat": 34.0522,
                                "StopLong": -118.2437,
                                "StopTime": "2026-08-24T07:30:00Z",
                                "EtaMinutes": 5
                            }
                        ]
                    }
                ]
            }
        ]
    )
    
    api = MyRideAPI(session=mock_session, access_token="mock-token", id_token=mock_token, district_id="district-12345")
    students = await api.async_get_students()
    
    assert len(students) == 1
    student = students[0]
    assert student["StudentId"] == 111
    assert student["FirstName"] == "Jane"
    assert len(student["RunInfo"]) == 1
    
    run = student["RunInfo"][0]
    assert run["RunName"] == "Route 10 AM"
    assert run["ActiveVehicle"] == "VEHICLE42"
    assert len(run["StopsInfo"]) == 1
    mock_session.get.assert_called_once()

@pytest.mark.asyncio
async def test_get_buses():
    mock_token = make_mock_token(["district-12345"])
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.closed = False
    
    mock_session.get.return_value = MockResponse(
        status=200,
        json_data=[
            {
                "AssetId": 777,
                "AssetUniqueId": "VEHICLE42",
                "Latitude": 34.0530,
                "Longitude": -118.2440,
                "Heading": 180,
                "Speed": 25,
                "VisibleRunName": "Route 10 AM",
                "LogTime": "2026-08-24T07:32:00Z"
            }
        ]
    )
    
    api = MyRideAPI(session=mock_session, access_token="mock-token", id_token=mock_token, district_id="district-12345")
    buses = await api.async_get_buses()
    
    assert len(buses) == 1
    bus = buses[0]
    assert bus["AssetUniqueId"] == "VEHICLE42"
    assert bus["Latitude"] == 34.0530
    assert bus["Longitude"] == -118.2440
    assert bus["Heading"] == 180
    assert bus["Speed"] == 25
    mock_session.get.assert_called_once()

import logging
import jwt
import aiohttp
from typing import List, Dict, Any, Optional

_LOGGER = logging.getLogger(__name__)

COGNITO_URL = "https://cognito-idp.us-east-1.amazonaws.com/"
API_BASE_URL = "https://myridek12.tylerapi.com"
CLIENT_ID = "3c5382gsq7g13djnejo98p2d98"

class MyRideAuthError(Exception):
    """Exception raised when authentication fails."""
    pass

class MyRideAPIError(Exception):
    """Exception raised when API calls fail."""
    pass

class MyRideAPI:
    """API client wrapper for My Ride K-12."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        access_token: Optional[str] = None,
        id_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        district_id: Optional[str] = None
    ) -> None:
        self._session = session
        self.access_token = access_token
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.district_id = district_id

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_login(self, username: str, password: str) -> List[str]:
        """Log in via Cognito USER_PASSWORD_AUTH and return list of district IDs."""
        session = await self._get_session()
        
        headers = {
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "Content-Type": "application/x-amz-json-1.1",
            "User-Agent": "myridek12"
        }
        
        payload = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": CLIENT_ID,
            "AuthParameters": {
                "USERNAME": username,
                "PASSWORD": password
            }
        }
        
        _LOGGER.info("Attempting login to My Ride K-12 Cognito user pool")
        
        try:
            async with session.post(COGNITO_URL, json=payload, headers=headers) as resp:
                resp_json = await resp.json(content_type=None)
                
                if resp.status != 200:
                    error_type = resp_json.get("__type")
                    msg = resp_json.get("message", "Unknown auth error")
                    _LOGGER.warning("Authentication failed with status %s: %s", resp.status, error_type)
                    if error_type == "NotAuthorizedException":
                        raise MyRideAuthError(msg)
                    raise MyRideAPIError(f"Cognito auth failed: {msg}")
                
                auth_result = resp_json.get("AuthenticationResult", {})
                self.access_token = auth_result.get("AccessToken")
                self.id_token = auth_result.get("IdToken")
                self.refresh_token = auth_result.get("RefreshToken")
                
                # Parse groups/districts from the ID Token claims securely (no signature check)
                try:
                    claims = jwt.decode(self.id_token, options={"verify_signature": False})
                    districts = claims.get("cognito:groups", [])
                    _LOGGER.info("Authentication successful. Linked districts count: %s", len(districts))
                    return districts
                except Exception as token_err:
                    _LOGGER.error("Failed to decode Cognito ID token: %s", token_err)
                    raise MyRideAPIError("Failed to parse linked districts from token claims.")
                    
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during login request: %s", err)
            raise MyRideAPIError(f"Network error during authentication: {err}")

    def _get_headers(self) -> Dict[str, str]:
        """Build headers required by My Ride K-12 APIs."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "x-device-type": "browser",
            "x-client-version": "2026.3.35.0",
            "User-Agent": "myridek12"
        }
        if self.district_id:
            headers["x-tenant-id"] = self.district_id
        return headers

    async def async_get_students(self) -> List[Dict[str, Any]]:
        """Fetch linked students and their schedules."""
        if not self.access_token or not self.district_id:
            raise MyRideAPIError("Missing active session or selected district ID")
            
        session = await self._get_session()
        headers = self._get_headers()
        url = f"{API_BASE_URL}/api/student"
        
        _LOGGER.info("Fetching student details from My Ride K-12 API")
        
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    msg = await resp.text()
                    _LOGGER.error("Failed to fetch students. Status: %s", resp.status)
                    raise MyRideAPIError(f"API Error fetching students: {msg}")
                
                data = await resp.json(content_type=None)
                
                # Post-process models to add convenience properties matching standard schema
                # e.g., mapping RolloutBusNumber ?? AssetUniqueId to ActiveVehicle
                for student in data:
                    for run in student.get("RunInfo", []):
                        rollout = run.get("RolloutBusNumber")
                        asset = run.get("AssetUniqueId")
                        run["ActiveVehicle"] = rollout if rollout else asset
                
                return data
                
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error fetching students: %s", err)
            raise MyRideAPIError(f"Network error: {err}")

    async def async_get_buses(self) -> List[Dict[str, Any]]:
        """Fetch bus coordinates and statuses for the selected district."""
        if not self.access_token or not self.district_id:
            raise MyRideAPIError("Missing active session or selected district ID")
            
        session = await self._get_session()
        headers = self._get_headers()
        url = f"{API_BASE_URL}/api/bus"
        
        _LOGGER.info("Fetching bus coordinates from My Ride K-12 API")
        
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    msg = await resp.text()
                    _LOGGER.error("Failed to fetch buses. Status: %s", resp.status)
                    raise MyRideAPIError(f"API Error fetching buses: {msg}")
                
                return await resp.json(content_type=None)
                
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error fetching buses: %s", err)
            raise MyRideAPIError(f"Network error: {err}")

    async def async_close(self) -> None:
        """Close the active ClientSession."""
        if self._session and not self._session.closed:
            await self._session.close()

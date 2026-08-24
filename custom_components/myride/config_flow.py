"""Config flow for My Ride K-12 integration."""
from typing import Any, Dict, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_DISTRICT_ID, CONF_DISTRICTS
from .api import MyRideAPI, MyRideAuthError, MyRideAPIError

class MyRideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Ride K-12."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._districts: Optional[list] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle the initial step (username and password)."""
        errors = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            # Standard HA HTTP client session
            session = async_get_clientsession(self.hass)
            api = MyRideAPI(session=session)

            try:
                # Login and retrieve linked districts
                districts = await api.async_login(self._username, self._password)
                self._districts = districts

                if not districts:
                    errors["base"] = "no_districts"
                elif len(districts) == 1:
                    # If only 1 district, finish immediately
                    district_id = districts[0]
                    return self.async_create_entry(
                        title=f"My Ride K-12 ({district_id})",
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_DISTRICT_ID: district_id,
                            CONF_DISTRICTS: districts
                        }
                    )
                else:
                    # Redirect to district selection
                    return await self.async_step_select_district()

            except MyRideAuthError:
                errors["base"] = "invalid_auth"
            except MyRideAPIError:
                errors["base"] = "cannot_connect"
            except Exception: # pylint: disable=broad-except
                errors["base"] = "unknown"

        # Show forms schema
        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_select_district(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle selecting district when user is linked to multiple."""
        errors = {}

        if user_input is not None:
            district_id = user_input[CONF_DISTRICT_ID]
            return self.async_create_entry(
                title=f"My Ride K-12 ({district_id})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_DISTRICT_ID: district_id,
                    CONF_DISTRICTS: self._districts
                }
            )

        data_schema = vol.Schema({
            vol.Required(CONF_DISTRICT_ID): vol.In(self._districts)
        })

        return self.async_show_form(
            step_id="select_district",
            data_schema=data_schema,
            errors=errors
        )

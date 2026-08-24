import sys
from unittest.mock import MagicMock, AsyncMock

# Stub out the homeassistant hierarchy to allow tests to run without the full HA package.
class MockConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def __init__(self):
        self.hass = MagicMock()
        self.context = {}

    def async_show_form(self, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders or {},
        }

    def async_create_entry(self, title, data):
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
        }

# Define and register mocks
ha_config_entries = MagicMock()
ha_config_entries.ConfigFlow = MockConfigFlow

ha_helpers = MagicMock()
ha_helpers.aiohttp_client = MagicMock()
ha_helpers.update_coordinator = MagicMock()

ha_const = MagicMock()
ha_const.CONF_USERNAME = "username"
ha_const.CONF_PASSWORD = "password"

# Set up main homeassistant mock
ha_mock = MagicMock()
ha_mock.config_entries = ha_config_entries
ha_mock.helpers = ha_helpers
ha_mock.const = ha_const

# Register all modules
sys.modules["homeassistant"] = ha_mock
sys.modules["homeassistant.config_entries"] = ha_config_entries
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = ha_helpers
sys.modules["homeassistant.helpers.aiohttp_client"] = ha_helpers.aiohttp_client
sys.modules["homeassistant.helpers.update_coordinator"] = ha_helpers.update_coordinator
sys.modules["homeassistant.const"] = ha_const
sys.modules["homeassistant.exceptions"] = MagicMock()

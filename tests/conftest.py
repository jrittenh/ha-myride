import sys
from datetime import datetime, timezone
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

# Define homeassistant.util.dt mock
class MockDtUtil:
    UTC = timezone.utc

    def now(self) -> datetime:
        return datetime.now(self.UTC)

    def parse_datetime(self, time_str: str) -> datetime:
        if time_str.endswith("Z"):
            time_str = time_str[:-1] + "+00:00"
        return datetime.fromisoformat(time_str)

# Define a real class for DataUpdateCoordinator to avoid subclassing MagicMock
class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

    @classmethod
    def __class_getitem__(cls, item):
        return cls

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

# Define mock entities for subclassing (keeping them separate to avoid MRO conflicts)
class MockCoordinatorEntity:
    def __init__(self, coordinator, context=None):
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self._attr_unique_id = None
        self._attr_name = None

    @classmethod
    def __class_getitem__(cls, item):
        return cls

class MockSensorEntity:
    pass

class MockTrackerEntity:
    pass

# Define and register mocks
ha_config_entries = MagicMock()
ha_config_entries.ConfigFlow = MockConfigFlow

ha_helpers = MagicMock()
ha_helpers.aiohttp_client = MagicMock()
ha_helpers.update_coordinator = MagicMock()
ha_helpers.update_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
ha_helpers.update_coordinator.CoordinatorEntity = MockCoordinatorEntity
ha_helpers.entity_platform = MagicMock()

ha_const = MagicMock()
ha_const.CONF_USERNAME = "username"
ha_const.CONF_PASSWORD = "password"

# Set up main homeassistant mock tree to resolve attribute lookup paths correctly
ha_dt_util = MockDtUtil()
ha_util = MagicMock()
ha_util.dt = ha_dt_util

ha_mock = MagicMock()
ha_mock.config_entries = ha_config_entries
ha_mock.helpers = ha_helpers
ha_mock.const = ha_const
ha_mock.util = ha_util

# Set up sensor and tracker submodules
ha_sensor = MagicMock()
ha_sensor.SensorEntity = MockSensorEntity

ha_tracker = MagicMock()
ha_tracker.TrackerEntity = MockTrackerEntity

# Register all modules
sys.modules["homeassistant"] = ha_mock
sys.modules["homeassistant.config_entries"] = ha_config_entries
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = ha_helpers
sys.modules["homeassistant.helpers.aiohttp_client"] = ha_helpers.aiohttp_client
sys.modules["homeassistant.helpers.update_coordinator"] = ha_helpers.update_coordinator
sys.modules["homeassistant.helpers.entity_platform"] = ha_helpers.entity_platform
sys.modules["homeassistant.const"] = ha_const
sys.modules["homeassistant.exceptions"] = MagicMock()

# Register util and util.dt
sys.modules["homeassistant.util"] = ha_util
sys.modules["homeassistant.util.dt"] = ha_dt_util

# Register platforms
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = ha_sensor
sys.modules["homeassistant.components.device_tracker"] = ha_tracker
sys.modules["homeassistant.components.device_tracker.config_entry"] = ha_tracker

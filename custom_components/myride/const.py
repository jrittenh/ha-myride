"""Constants for the My Ride K-12 integration."""
from typing import Any

DOMAIN = "myride"

CONF_DISTRICT_ID = "district_id"
CONF_DISTRICTS = "districts"
CONF_REFRESH_TOKEN = "refresh_token"

# Polling intervals in seconds
DEFAULT_POLL_INTERVAL_ACTIVE = 30
DEFAULT_POLL_INTERVAL_PASSIVE = 900

def get_field(d: Any, key: str, default: Any = None) -> Any:
    """Get field from dict supporting both camelCase and PascalCase."""
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    if not key:
        return default
    # Check camelCase
    camel = key[0].lower() + key[1:]
    if camel in d:
        return d[camel]
    # Check PascalCase
    pascal = key[0].upper() + key[1:]
    if pascal in d:
        return d[pascal]
    return default

"""Constants for the My Ride K-12 integration."""
from typing import Any

DOMAIN = "myride"

CONF_DISTRICT_ID = "district_id"
CONF_DISTRICTS = "districts"
CONF_REFRESH_TOKEN = "refresh_token"

# Polling intervals in seconds
DEFAULT_POLL_INTERVAL_ACTIVE = 30
DEFAULT_POLL_INTERVAL_PASSIVE = 900

# Proximity and GPS thresholds
DEFAULT_GPS_ACCURACY = 15  # meters
STOP_ARRIVAL_RADIUS_METERS = 150.0  # meters
EVENT_MYRIDE_TELEMETRY = "myride_telemetry_updated"

import math

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two GPS points on Earth in meters."""
    radius_earth_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_earth_m * c

def meters_to_miles(meters: float) -> float:
    """Convert meters to miles."""
    return meters * 0.000621371

def meters_to_feet(meters: float) -> float:
    """Convert meters to feet."""
    return meters * 3.28084

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


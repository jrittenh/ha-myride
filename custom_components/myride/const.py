"""Constants for the My Ride K-12 integration."""
from typing import Any, Dict, Optional
import math
import homeassistant.util.dt as dt_util

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


def get_run_display_name(run: Any) -> str:
    """Return a descriptive label for a run, guaranteeing AM/PM distinction."""
    if not isinstance(run, dict):
        return ""

    # 1. Check for explicit name or description
    name = (
        get_field(run, "runName")
        or get_field(run, "runDescription")
        or get_field(run, "description")
        or ""
    )
    name = str(name).strip()

    # If name already explicitly contains AM, PM, Morning, Afternoon, etc.
    lower_name = name.lower()
    has_am_pm = any(
        k in lower_name
        for k in (
            " am", " pm", "(am)", "(pm)", "am ", "pm ",
            "morning", "afternoon", "pickup", "pick up",
            "dropoff", "drop off"
        )
    )

    # 2. Inspect stops to determine AM vs PM by planned schedule
    time_hint = ""
    stops = get_field(run, "stopsInfo", [])
    if isinstance(stops, list):
        for stop in stops:
            time_str = get_field(stop, "plannedStopTime") or get_field(stop, "stopTime")
            if time_str:
                try:
                    dt = dt_util.parse_datetime(str(time_str))
                    if dt:
                        time_hint = "AM" if dt.hour < 12 else "PM"
                        break
                except Exception:
                    pass
                # Handle raw "07:35:00" or similar time format
                time_s = str(time_str)
                if ":" in time_s:
                    try:
                        hour = int(time_s.split(":")[0].split("T")[-1])
                        time_hint = "AM" if hour < 12 else "PM"
                        break
                    except Exception:
                        pass

    # 3. Check runType if provided
    if not time_hint:
        run_type = str(get_field(run, "runType") or "").upper()
        if "AM" in run_type or run_type == "1":
            time_hint = "AM"
        elif "PM" in run_type or run_type == "2":
            time_hint = "PM"

    if name:
        if has_am_pm or not time_hint:
            return name
        return f"{name} {time_hint}"

    if time_hint:
        return time_hint

    run_id = get_field(run, "runId")
    return f"Route {run_id}" if run_id is not None else ""

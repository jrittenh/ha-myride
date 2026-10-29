"""Constants for the My Ride K-12 integration."""
from typing import Any, Dict, List, Optional
import math
import re
from datetime import datetime
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


def get_time_suffix(display_name: str) -> str:
    """Return entity ID suffix ('_am', '_pm', or cleaned name) from display name."""
    if not display_name:
        return ""
    # Use word boundaries so words containing 'am' (e.g. 'campus', 'program', 'oakham') don't falsely match
    is_am = bool(re.search(r"\b(am|morning|pickup)\b", display_name, re.IGNORECASE))
    is_pm = bool(re.search(r"\b(pm|afternoon|dropoff)\b", display_name, re.IGNORECASE))

    if is_am and not is_pm:
        return "_am"
    if is_pm and not is_am:
        return "_pm"
    if re.search(r"\b(pm)\b", display_name, re.IGNORECASE):
        return "_pm"
    if re.search(r"\b(am)\b", display_name, re.IGNORECASE):
        return "_am"

    cleaned = re.sub(r"[^\w\s-]", "", display_name).strip().lower()
    cleaned = re.sub(r"[-\s]+", "_", cleaned)
    return f"_{cleaned}" if cleaned else ""


def _extract_earliest_stop_time(run: Any) -> Optional[int]:
    """Extract earliest stop planned time in minutes from midnight (wall-clock)."""
    stops = get_field(run, "stopsInfo", [])
    if not isinstance(stops, list):
        return None
    earliest_mins: Optional[int] = None
    for stop in stops:
        time_str = get_field(stop, "plannedStopTime") or get_field(stop, "stopTime")
        if not time_str:
            continue
        try:
            dt = dt_util.parse_datetime(str(time_str))
            if dt:
                mins = dt.hour * 60 + dt.minute
                if earliest_mins is None or mins < earliest_mins:
                    earliest_mins = mins
                continue
        except Exception:
            pass

        time_s = str(time_str)
        if ":" in time_s:
            try:
                parts = time_s.split("T")[-1].split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                mins = hour * 60 + minute
                if earliest_mins is None or mins < earliest_mins:
                    earliest_mins = mins
            except Exception:
                pass
    return earliest_mins


def get_run_display_name(run: Any, all_runs: Optional[List[Any]] = None) -> str:
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

    # Check if name already explicitly contains AM, PM, Morning, Afternoon, etc. using word boundaries
    has_am = bool(re.search(r"\b(am|morning|pickup)\b", name, re.IGNORECASE))
    has_pm = bool(re.search(r"\b(pm|afternoon|dropoff)\b", name, re.IGNORECASE))
    has_explicit_label = has_am or has_pm

    # 2. Determine time hint (AM vs PM)
    time_hint = ""
    current_mins = _extract_earliest_stop_time(run)

    # 2a. Relative comparison if multiple runs exist for this student
    if all_runs and isinstance(all_runs, list) and len(all_runs) >= 2:
        current_id = get_field(run, "runId")
        other_runs = [
            r for r in all_runs
            if isinstance(r, dict) and (get_field(r, "runId") != current_id or r is not run)
        ]
        if other_runs:
            other_run = other_runs[0]
            other_mins = _extract_earliest_stop_time(other_run)
            if current_mins is not None and other_mins is not None and current_mins != other_mins:
                time_hint = "AM" if current_mins < other_mins else "PM"
            elif current_mins is not None and other_mins is None:
                time_hint = "AM" if current_mins < 12 * 60 else "PM"
            elif current_mins is None and other_mins is not None:
                time_hint = "PM" if other_mins < 12 * 60 else "AM"

    # 2b. Standalone schedule inspection if time_hint not yet resolved
    if not time_hint and current_mins is not None:
        time_hint = "AM" if current_mins < 12 * 60 else "PM"

    # 2c. Check runType if stops schedule did not resolve
    if not time_hint:
        run_type = str(get_field(run, "runType") or "").upper()
        if "AM" in run_type or run_type == "1":
            time_hint = "AM"
        elif "PM" in run_type or run_type == "2":
            time_hint = "PM"

    if name:
        if has_explicit_label or not time_hint:
            return name
        return f"{name} {time_hint}"

    if time_hint:
        return time_hint

    run_id = get_field(run, "runId")
    return f"Route {run_id}" if run_id is not None else ""

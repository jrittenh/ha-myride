from custom_components.myride.const import (
    haversine_distance,
    meters_to_miles,
    meters_to_feet,
    get_run_display_name,
    get_time_suffix,
)

def test_basic():
    assert True

def test_haversine_distance():
    # Distance between same points is 0
    assert haversine_distance(34.0522, -118.2437, 34.0522, -118.2437) == 0.0

    # Distance between nearby coordinates (~93 meters)
    dist = haversine_distance(34.0522, -118.2437, 34.0530, -118.2440)
    assert 90.0 < dist < 100.0

    # Unit conversions
    assert round(meters_to_miles(1609.34), 2) == 1.00
    assert int(meters_to_feet(100.0)) == 328

def test_get_run_display_name():
    # 1. Explicit runName with AM/PM preserved
    assert get_run_display_name({"runName": "Route 10 AM"}) == "Route 10 AM"
    assert get_run_display_name({"runName": "Elementary PM Dropoff"}) == "Elementary PM Dropoff"

    # 2. Blank runName with AM stops (< 12:00)
    run_am = {
        "runName": "",
        "stopsInfo": [{"plannedStopTime": "2026-10-28T07:35:00Z"}]
    }
    assert get_run_display_name(run_am) == "AM"

    # 3. Blank runName with PM stops (>= 12:00)
    run_pm = {
        "runName": None,
        "stopsInfo": [{"plannedStopTime": "2026-10-28T15:15:00Z"}]
    }
    assert get_run_display_name(run_pm) == "PM"

    # 4. Route name without AM/PM gets suffix from stops
    run_generic = {
        "runName": "Route 19",
        "stopsInfo": [{"plannedStopTime": "2026-10-28T07:45:00Z"}]
    }
    assert get_run_display_name(run_generic) == "Route 19 AM"

    # 5. Fallback to runId if no times
    assert get_run_display_name({"runId": 42}) == "Route 42"

    # 6. Relative run comparison when all_runs is provided
    run1 = {
        "runId": 101,
        "runName": "Campus",
        "stopsInfo": [{"plannedStopTime": "2026-10-28T08:15:00Z"}],
    }
    run2 = {
        "runId": 102,
        "runName": "Campus",
        "stopsInfo": [{"plannedStopTime": "2026-10-28T15:15:00Z"}],
    }
    all_runs = [run1, run2]
    assert get_run_display_name(run1, all_runs) == "Campus AM"
    assert get_run_display_name(run2, all_runs) == "Campus PM"


def test_get_time_suffix():
    """Test get_time_suffix extracts correct entity suffix without false AM matches."""
    # Words containing 'am' (e.g. campus, program, oakham) must NOT trigger '_am'
    assert get_time_suffix("Campus PM") == "_pm"
    assert get_time_suffix("Campus (PM)") == "_pm"
    assert get_time_suffix("Elementary Program (PM)") == "_pm"
    assert get_time_suffix("Oakham PM") == "_pm"
    assert get_time_suffix("Durham PM") == "_pm"
    assert get_time_suffix("William PM") == "_pm"
    assert get_time_suffix("Graham PM") == "_pm"
    assert get_time_suffix("STEAM PM") == "_pm"
    assert get_time_suffix("Campus AM") == "_am"
    assert get_time_suffix("Campus (AM)") == "_am"
    assert get_time_suffix("Program AM") == "_am"
    assert get_time_suffix("AM") == "_am"
    assert get_time_suffix("PM") == "_pm"
    assert get_time_suffix("Morning") == "_am"
    assert get_time_suffix("Afternoon") == "_pm"
    assert get_time_suffix("Pickup") == "_am"
    assert get_time_suffix("Dropoff") == "_pm"
    assert get_time_suffix("Route 42") == "_route_42"
    assert get_time_suffix("") == ""

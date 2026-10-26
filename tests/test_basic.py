from custom_components.myride.const import haversine_distance, meters_to_miles, meters_to_feet

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


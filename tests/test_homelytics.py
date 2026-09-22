import pytest
from unittest.mock import MagicMock
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from Homelytics_US import (
    land_to_sqft_us,
    acres_to_sqft,
    get_location_confidence_us,
    find_location_sequentially as find_location_sequentially_us,
    compute_deterministic_estimate_us,
)
from Homelytics_PK import (
    land_to_sqft_pk,
    marla_to_sqft,
    kanal_to_sqft,
    detect_society_premium,
    find_location_sequentially as find_location_sequentially_pk,
    compute_deterministic_estimate,
)

# ---------------------------------------------------------------------------
# Unit tests for land conversion
# ---------------------------------------------------------------------------
def test_land_to_sqft_us_conversion():
    assert land_to_sqft_us(1.0, "Acres") == 43560.0
    assert land_to_sqft_us(2.5, "Acres") == 2.5 * 43560.0
    assert land_to_sqft_us(5000, "Sq Ft") == 5000
    assert land_to_sqft_us(0, "Acres") == 0.0

def test_land_to_sqft_pk_conversion():
    assert land_to_sqft_pk(10, "Marla") == 10 * 272.25
    assert land_to_sqft_pk(2, "Kanal") == 2 * 5445.0
    assert land_to_sqft_pk(2250, "Sq Ft") == 2250
    assert land_to_sqft_pk(0, "Marla") == 0

# ---------------------------------------------------------------------------
# Unit tests for detect_society_premium
# ---------------------------------------------------------------------------
def test_detect_society_premium_known_societies():
    society, premium = detect_society_premium("House 123, DHA Phase 5, Lahore")
    assert society == "DHA"
    assert premium == 0.35

    society, premium = detect_society_premium("Sector F-7/2, Islamabad")
    assert society == "F-7"
    assert premium == 0.25

def test_detect_society_premium_unknown():
    society, premium = detect_society_premium("123 Random Road, City")
    assert society is None
    assert premium == 0.0

def test_detect_society_premium_missing_or_invalid_address():
    # Test for missing/None/empty address
    assert detect_society_premium(None) == (None, 0.0)
    assert detect_society_premium("") == (None, 0.0)
    assert detect_society_premium("   ") == (None, 0.0)
    assert detect_society_premium(12345) == (None, 0.0)

# ---------------------------------------------------------------------------
# Unit tests for get_location_confidence_us
# ---------------------------------------------------------------------------
def test_get_location_confidence_us_missing_or_none():
    conf, note = get_location_confidence_us(None, "123 Main St")
    assert conf == "Low"
    assert "could not be geocoded" in note

    mock_loc_invalid = MagicMock()
    mock_loc_invalid.raw = "invalid_not_dict"
    conf, note = get_location_confidence_us(mock_loc_invalid, "123 Main St")
    assert conf == "Low"

def test_get_location_confidence_us_levels():
    # High score (3/3)
    mock_loc_high = MagicMock()
    mock_loc_high.raw = {'address': {'road': 'Main St', 'postcode': '90210', 'city': 'Beverly Hills'}}
    conf, _ = get_location_confidence_us(mock_loc_high, "123 Main St")
    assert conf == "High"

    # Medium score (2/3)
    mock_loc_med = MagicMock()
    mock_loc_med.raw = {'address': {'postcode': '90210', 'city': 'Beverly Hills'}}
    conf, _ = get_location_confidence_us(mock_loc_med, "Beverly Hills, CA")
    assert conf == "Medium"

    # Low score (1/3)
    mock_loc_low = MagicMock()
    mock_loc_low.raw = {'address': {'state': 'California'}}
    conf, _ = get_location_confidence_us(mock_loc_low, "California")
    assert conf == "Low"

# ---------------------------------------------------------------------------
# Unit tests for find_location_sequentially
# ---------------------------------------------------------------------------
def test_find_location_sequentially_us_missing_address():
    assert find_location_sequentially_us(MagicMock(), None) is None
    assert find_location_sequentially_us(MagicMock(), "") is None
    assert find_location_sequentially_us(MagicMock(), "   ") is None

def test_find_location_sequentially_pk_missing_address():
    assert find_location_sequentially_pk(MagicMock(), None) is None
    assert find_location_sequentially_pk(MagicMock(), "") is None

def test_find_location_sequentially_error_handling():
    mock_geolocator = MagicMock()
    mock_geolocator.geocode.side_effect = GeocoderTimedOut("Timed out")

    # Should handle Exception gracefully and return None instead of crashing
    loc_us = find_location_sequentially_us(mock_geolocator, "123 Test St, CA")
    assert loc_us is None

    loc_pk = find_location_sequentially_pk(mock_geolocator, "DHA Phase 5, Lahore")
    assert loc_pk is None

def test_find_location_sequentially_success():
    mock_geolocator = MagicMock()
    expected_loc = MagicMock()
    mock_geolocator.geocode.return_value = expected_loc

    assert find_location_sequentially_us(mock_geolocator, "123 Main St, CA") == expected_loc
    assert find_location_sequentially_pk(mock_geolocator, "House 10, Lahore") == expected_loc

# ---------------------------------------------------------------------------
# Unit tests for compute_deterministic_estimate
# ---------------------------------------------------------------------------
def test_compute_deterministic_estimate_us_valid():
    low, high, sqft_price = compute_deterministic_estimate_us(
        state="California",
        property_type="Single-Family Home",
        sq_ft=2000,
        land_sqft=0,
        condition="Good",
        year_built_category="Recent (3-10 yrs)",
        hoa=False
    )
    assert low is not None and high is not None and sqft_price is not None
    assert low < high

def test_compute_deterministic_estimate_us_negative_or_invalid():
    # Negative sq_ft should return None, None, None safely
    low, high, price = compute_deterministic_estimate_us(
        state="California",
        property_type="Single-Family Home",
        sq_ft=-500,
        land_sqft=0,
        condition="Good",
        year_built_category="Recent (3-10 yrs)",
        hoa=False
    )
    assert low is None and high is None and price is None

def test_compute_deterministic_estimate_pk_valid():
    low, high, sqft_price = compute_deterministic_estimate(
        city="Lahore",
        property_type="House",
        sq_ft=2250,
        land_sqft=0,
        condition="Good",
        year_built_category="Recent (3-10 yrs)",
        society_premium=0.35
    )
    assert low is not None and high is not None and sqft_price is not None
    assert low < high

def test_compute_deterministic_estimate_pk_negative_or_invalid():
    low, high, price = compute_deterministic_estimate(
        city="Lahore",
        property_type="House",
        sq_ft=-100,
        land_sqft=0,
        condition="Good",
        year_built_category="Recent (3-10 yrs)",
        society_premium=0.35
    )
    assert low is None and high is None and price is None

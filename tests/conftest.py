"""Pytest configuration and fixtures for the Chicago crash data pipeline tests."""
import pytest
import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.config import settings


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_crash_record():
    """Sample crash record for testing."""
    return {
        "crash_record_id": "TEST123",
        "crash_date": "2024-01-01T12:30:00.000",
        "latitude": "41.8781",
        "longitude": "-87.6298",
        "injuries_total": "2",
        "injuries_fatal": "0",
        "injuries_incapacitating": "1", 
        "injuries_non_incapacitating": "1",
        "injuries_reported_not_evident": "0",
        "injuries_no_indication": "0",
        "injuries_unknown": "0",
        "posted_speed_limit": "30",
        "street_no": "100",
        "lane_cnt": None,
        "traffic_control_device": "TRAFFIC SIGNAL",
        "device_condition": "FUNCTIONING PROPERLY",
        "weather_condition": "CLEAR",
        "lighting_condition": "DAYLIGHT",
        "street_direction": "N",
        "street_name": "MICHIGAN AVE",
        "crash_type": "INJURY AND / OR TOW DUE TO CRASH",
        "damage": "$1,501 - $5,000",
        "prim_contributory_cause": "FOLLOWING TOO CLOSELY",
        "sec_contributory_cause": "UNABLE TO DETERMINE",
        "date_police_notified": "2024-01-01T12:35:00.000"
    }


@pytest.fixture
def sample_person_record():
    """Sample person record for testing."""
    return {
        "crash_record_id": "TEST123",
        "person_id": "PERSON001",
        "person_type": "DRIVER",
        "age": "35",
        "sex": "M",
        "safety_equipment": "SAFETY BELT USED",
        "injury_classification": "INCAPACITATING INJURY",
        "hospital": "NORTHWESTERN MEMORIAL",
        "bac_result": "NEGATIVE",
        "bac_result_value": None
    }


@pytest.fixture
def sample_vehicle_record():
    """Sample vehicle record for testing."""
    return {
        "crash_record_id": "TEST123",
        "unit_no": "1",
        "vehicle_year": "2020",
        "make": "TOYOTA",
        "model": "CAMRY",
        "vehicle_type": "PASSENGER",
        "num_passengers": "1",
        "occupant_cnt": "1",
        "travel_direction": "N",
        "maneuver": "STRAIGHT AHEAD"
    }


@pytest.fixture
def invalid_crash_record():
    """Invalid crash record for testing validation."""
    return {
        "crash_record_id": None,  # Missing required field
        "crash_date": "invalid-date",  # Invalid format
        "latitude": "50.0",  # Outside Chicago bounds
        "longitude": "-95.0",  # Outside Chicago bounds
        "injuries_total": "not-a-number",  # Invalid integer
        "posted_speed_limit": "-10"  # Negative speed limit
    }


@pytest.fixture
def chicago_bounds():
    """Chicago geographic bounds for testing."""
    return {
        "min_latitude": settings.validation.min_latitude,
        "max_latitude": settings.validation.max_latitude,
        "min_longitude": settings.validation.min_longitude,
        "max_longitude": settings.validation.max_longitude
    }
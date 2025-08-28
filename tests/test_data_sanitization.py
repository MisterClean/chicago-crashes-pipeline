"""Tests for data sanitization functionality."""
import pytest
from datetime import datetime
from validators.data_sanitizer import DataSanitizer


class TestDataSanitizer:
    """Test data sanitization and cleaning."""
    
    @pytest.fixture
    def sanitizer(self):
        """Create a DataSanitizer instance."""
        return DataSanitizer()
    
    def test_sanitize_crash_record(self, sanitizer, sample_crash_record):
        """Test crash record sanitization."""
        result = sanitizer.sanitize_crash_record(sample_crash_record)
        
        # Check required fields are present
        assert result["crash_record_id"] == "TEST123"
        assert isinstance(result["crash_date"], datetime)
        
        # Check numeric conversions
        assert result["latitude"] == 41.8781
        assert result["longitude"] == -87.6298
        assert result["injuries_total"] == 2
        assert result["injuries_fatal"] == 0
        
        # Check string cleaning
        assert result["street_name"] == "MICHIGAN AVE"
        assert result["traffic_control_device"] == "TRAFFIC SIGNAL"
    
    def test_sanitize_person_record(self, sanitizer, sample_person_record):
        """Test person record sanitization."""
        result = sanitizer.sanitize_person_record(sample_person_record)
        
        assert result["crash_record_id"] == "TEST123"
        assert result["person_id"] == "PERSON001"
        assert result["age"] == 35
        assert result["sex"] == "M"
        assert result["person_type"] == "DRIVER"
    
    def test_sanitize_vehicle_record(self, sanitizer, sample_vehicle_record):
        """Test vehicle record sanitization."""
        result = sanitizer.sanitize_vehicle_record(sample_vehicle_record)
        
        assert result["crash_record_id"] == "TEST123"
        assert result["unit_no"] == "1"
        assert result["vehicle_year"] == 2020
        assert result["make"] == "TOYOTA"
        assert result["model"] == "CAMRY"
        assert result["num_passengers"] == 1
    
    def test_clean_string_operations(self, sanitizer):
        """Test string cleaning operations."""
        # Test whitespace removal
        assert sanitizer._clean_string("  TEST  ") == "TEST"
        
        # Test null value handling
        assert sanitizer._clean_string(None) is None
        assert sanitizer._clean_string("") is None
        assert sanitizer._clean_string("NULL") is None
        assert sanitizer._clean_string("N/A") is None
        
        # Test extra whitespace removal
        assert sanitizer._clean_string("MULTI   SPACE   STRING") == "MULTI SPACE STRING"
        
        # Test length truncation
        assert sanitizer._clean_string("A" * 200, max_length=10) == "A" * 10
    
    def test_clean_integer_operations(self, sanitizer):
        """Test integer cleaning operations."""
        assert sanitizer._clean_integer("123") == 123
        assert sanitizer._clean_integer("123.0") == 123
        assert sanitizer._clean_integer(123.7) == 123
        assert sanitizer._clean_integer(None) is None
        assert sanitizer._clean_integer("") is None
        assert sanitizer._clean_integer("invalid") is None
        assert sanitizer._clean_integer("NULL") is None
    
    def test_clean_float_operations(self, sanitizer):
        """Test float cleaning operations."""
        assert sanitizer._clean_float("123.45") == 123.45
        assert sanitizer._clean_float("123") == 123.0
        assert sanitizer._clean_float(123.45) == 123.45
        assert sanitizer._clean_float(None) is None
        assert sanitizer._clean_float("") is None
        assert sanitizer._clean_float("invalid") is None
    
    def test_parse_datetime_operations(self, sanitizer):
        """Test datetime parsing operations."""
        # Test various datetime formats
        iso_format = "2024-01-01T12:30:00.000"
        iso_simple = "2024-01-01T12:30:00"
        space_format = "2024-01-01 12:30:00"
        date_only = "2024-01-01"
        
        result_iso = sanitizer._parse_datetime(iso_format)
        result_simple = sanitizer._parse_datetime(iso_simple)
        result_space = sanitizer._parse_datetime(space_format)
        result_date = sanitizer._parse_datetime(date_only)
        
        assert isinstance(result_iso, datetime)
        assert isinstance(result_simple, datetime)
        assert isinstance(result_space, datetime)
        assert isinstance(result_date, datetime)
        
        assert result_iso.year == 2024
        assert result_iso.month == 1
        assert result_iso.day == 1
        
        # Test invalid datetime
        assert sanitizer._parse_datetime("invalid-date") is None
        assert sanitizer._parse_datetime(None) is None
    
    def test_coordinate_validation(self, sanitizer, chicago_bounds):
        """Test coordinate validation within Chicago bounds."""
        # Valid Chicago coordinates
        valid_lat = 41.8781
        valid_lon = -87.6298
        
        assert sanitizer._clean_coordinate(valid_lat, "latitude") == valid_lat
        assert sanitizer._clean_coordinate(valid_lon, "longitude") == valid_lon
        
        # Invalid coordinates (outside Chicago)
        invalid_lat = 50.0  # Too far north
        invalid_lon = -95.0  # Too far west
        
        assert sanitizer._clean_coordinate(invalid_lat, "latitude") is None
        assert sanitizer._clean_coordinate(invalid_lon, "longitude") is None
    
    def test_age_validation(self, sanitizer):
        """Test age validation."""
        assert sanitizer._clean_age("25") == 25
        assert sanitizer._clean_age("0") == 0
        assert sanitizer._clean_age("120") == 120
        
        # Invalid ages
        assert sanitizer._clean_age("-5") is None
        assert sanitizer._clean_age("150") is None
        assert sanitizer._clean_age("invalid") is None
    
    def test_vehicle_year_validation(self, sanitizer):
        """Test vehicle year validation."""
        assert sanitizer._clean_vehicle_year("2020") == 2020
        assert sanitizer._clean_vehicle_year("1950") == 1950
        
        # Invalid years
        assert sanitizer._clean_vehicle_year("1800") is None  # Too old
        assert sanitizer._clean_vehicle_year("2030") is None  # Too new
        assert sanitizer._clean_vehicle_year("invalid") is None
    
    def test_remove_duplicates(self, sanitizer):
        """Test duplicate record removal."""
        records = [
            {"crash_record_id": "TEST1", "data": "first"},
            {"crash_record_id": "TEST2", "data": "second"},
            {"crash_record_id": "TEST1", "data": "duplicate"},  # Duplicate
            {"crash_record_id": "TEST3", "data": "third"}
        ]
        
        unique_records = sanitizer.remove_duplicates(records, "crash_record_id")
        
        assert len(unique_records) == 3
        record_ids = [r["crash_record_id"] for r in unique_records]
        assert "TEST1" in record_ids
        assert "TEST2" in record_ids 
        assert "TEST3" in record_ids
        
        # First occurrence should be kept
        test1_record = next(r for r in unique_records if r["crash_record_id"] == "TEST1")
        assert test1_record["data"] == "first"
    
    def test_handle_missing_data(self, sanitizer):
        """Test handling of records with missing data."""
        incomplete_record = {
            "crash_record_id": "TEST123",
            "crash_date": None,
            "latitude": "",
            "longitude": "N/A",
            "injuries_total": None
        }
        
        result = sanitizer.sanitize_crash_record(incomplete_record)
        
        assert result["crash_record_id"] == "TEST123"
        assert result["crash_date"] is None
        assert result["latitude"] is None
        assert result["longitude"] is None
        assert result["injuries_total"] is None
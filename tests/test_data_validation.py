"""Tests for data validation functionality."""
import pytest

from validators.crash_validator import CrashValidator


class TestCrashValidator:
    """Test crash data validation."""

    @pytest.fixture
    def validator(self):
        """Create a CrashValidator instance."""
        return CrashValidator()

    def test_validate_valid_crash_record(self, validator, sample_crash_record):
        """Test validation of a valid crash record."""
        result = validator.validate_crash_record(sample_crash_record)

        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert isinstance(result["warnings"], list)

    def test_validate_invalid_crash_record(self, validator, invalid_crash_record):
        """Test validation of an invalid crash record."""
        result = validator.validate_crash_record(invalid_crash_record)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

        # Should have error for missing crash_record_id
        error_messages = " ".join(result["errors"])
        assert "crash_record_id" in error_messages.lower()

    def test_coordinate_validation_warnings(self, validator):
        """Test coordinate validation generates warnings."""
        # Record with coordinates outside Chicago bounds
        out_of_bounds_record = {
            "crash_record_id": "TEST123",
            "crash_date": "2024-01-01T12:30:00.000",
            "latitude": "50.0",  # Outside Chicago
            "longitude": "-95.0",  # Outside Chicago
        }

        result = validator.validate_crash_record(out_of_bounds_record)

        # Should be valid but with warnings
        assert result["valid"] is True
        assert len(result["warnings"]) >= 2  # One for lat, one for lon

        warning_text = " ".join(result["warnings"]).lower()
        assert "latitude" in warning_text
        assert "longitude" in warning_text
        assert "chicago bounds" in warning_text

    def test_required_fields_validation(self, validator):
        """Test required fields validation."""
        # Record missing required fields
        incomplete_record = {
            "latitude": "41.8781",
            "longitude": "-87.6298"
            # Missing crash_record_id and crash_date
        }

        result = validator.validate_crash_record(incomplete_record)

        assert result["valid"] is False
        assert len(result["errors"]) >= 2  # At least crash_record_id and crash_date

        error_text = " ".join(result["errors"]).lower()
        assert "crash_record_id" in error_text
        assert "crash_date" in error_text

    def test_batch_validation(
        self, validator, sample_crash_record, invalid_crash_record
    ):
        """Test batch validation of multiple records."""
        records = [
            sample_crash_record,
            invalid_crash_record,
            sample_crash_record.copy(),  # Another valid record
        ]

        summary = validator.validate_batch(records)

        assert summary["total_records"] == 3
        assert summary["valid_records"] == 2
        assert summary["invalid_records"] == 1
        assert summary["total_errors"] > 0
        assert summary["total_warnings"] >= 0

    def test_empty_batch_validation(self, validator):
        """Test validation of empty batch."""
        summary = validator.validate_batch([])

        assert summary["total_records"] == 0
        assert summary["valid_records"] == 0
        assert summary["invalid_records"] == 0
        assert summary["total_errors"] == 0
        assert summary["total_warnings"] == 0

    def test_coordinate_bounds_precision(self, validator):
        """Test coordinate validation with boundary precision."""
        from utils.config import settings

        # Test coordinates exactly at the boundaries
        boundary_record = {
            "crash_record_id": "BOUNDARY_TEST",
            "crash_date": "2024-01-01T12:30:00.000",
            "latitude": str(settings.validation.min_latitude),  # Exactly at min
            "longitude": str(settings.validation.min_longitude),  # Exactly at min
        }

        result = validator.validate_crash_record(boundary_record)

        # Should be valid (boundaries are inclusive)
        assert result["valid"] is True

        # Test slightly outside boundaries
        outside_record = boundary_record.copy()
        outside_record["latitude"] = str(settings.validation.min_latitude - 0.001)

        result_outside = validator.validate_crash_record(outside_record)

        # Should still be valid but with warning
        assert result_outside["valid"] is True
        assert len(result_outside["warnings"]) > 0

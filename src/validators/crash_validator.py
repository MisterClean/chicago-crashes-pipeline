"""Validation logic for crash data records."""

from typing import Any

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CrashValidator:
    """Validates crash data records for completeness and consistency."""

    def __init__(self):
        """Initialize crash validator."""
        self.validation_settings = settings.validation

    def validate_crash_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Validate a crash record and return validation results.

        Args:
            record: Crash record to validate

        Returns:
            Validation results with errors and warnings
        """
        results: dict[str, Any] = {"valid": True, "errors": [], "warnings": []}

        # Check required fields
        required_fields = self.validation_settings.required_fields.get("crashes", [])
        for field in required_fields:
            if not record.get(field):
                results["errors"].append(f"Missing required field: {field}")
                results["valid"] = False

        # Validate coordinates
        if record.get("latitude") and record.get("longitude"):
            lat = float(record["latitude"]) if record["latitude"] else None
            lon = float(record["longitude"]) if record["longitude"] else None

            if lat and (
                lat < self.validation_settings.min_latitude
                or lat > self.validation_settings.max_latitude
            ):
                results["warnings"].append(f"Latitude {lat} outside Chicago bounds")

            if lon and (
                lon < self.validation_settings.min_longitude
                or lon > self.validation_settings.max_longitude
            ):
                results["warnings"].append(f"Longitude {lon} outside Chicago bounds")

        return results

    def validate_batch(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate a batch of records.

        Args:
            records: List of records to validate

        Returns:
            Batch validation summary
        """
        summary = {
            "total_records": len(records),
            "valid_records": 0,
            "invalid_records": 0,
            "total_errors": 0,
            "total_warnings": 0,
        }

        for record in records:
            result = self.validate_crash_record(record)
            if result["valid"]:
                summary["valid_records"] += 1
            else:
                summary["invalid_records"] += 1

            summary["total_errors"] += len(result["errors"])
            summary["total_warnings"] += len(result["warnings"])

        return summary

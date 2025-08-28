"""Data sanitization and cleaning utilities."""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)


class DataSanitizer:
    """Sanitizes and cleans raw data from Chicago Open Data Portal."""
    
    def __init__(self):
        """Initialize data sanitizer."""
        self.validation_settings = settings.validation
    
    def sanitize_crash_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize a crash record.
        
        Args:
            record: Raw crash record from API
            
        Returns:
            Sanitized record
        """
        sanitized = {}
        
        # Handle required fields
        sanitized['crash_record_id'] = self._clean_string(
            record.get('crash_record_id')
        )
        
        # Parse crash date
        sanitized['crash_date'] = self._parse_datetime(
            record.get('crash_date')
        )
        
        # Handle coordinates
        sanitized['latitude'] = self._clean_coordinate(
            record.get('latitude'),
            coord_type='latitude'
        )
        sanitized['longitude'] = self._clean_coordinate(
            record.get('longitude'),
            coord_type='longitude'
        )
        
        # Handle integer fields
        integer_fields = [
            'injuries_total', 'injuries_fatal', 'injuries_incapacitating',
            'injuries_non_incapacitating', 'injuries_reported_not_evident',
            'injuries_no_indication', 'injuries_unknown', 'posted_speed_limit',
            'street_no', 'lane_cnt'
        ]
        
        for field in integer_fields:
            sanitized[field] = self._clean_integer(record.get(field))
        
        # Handle string fields
        string_fields = [
            'crash_date_est_i', 'traffic_control_device', 'device_condition',
            'weather_condition', 'lighting_condition', 'street_direction',
            'street_name', 'crash_type', 'damage', 'prim_contributory_cause',
            'sec_contributory_cause', 'work_zone_i', 'work_zone_type',
            'workers_present_i', 'hit_and_run_i', 'dooring_i', 
            'intersection_related_i', 'not_right_of_way_i', 'alignment',
            'roadway_surface_cond', 'road_defect', 'report_type',
            'most_severe_injury', 'beat_of_occurrence', 'photos_taken_i',
            'statements_taken_i'
        ]
        
        for field in string_fields:
            sanitized[field] = self._clean_string(record.get(field))
        
        # Handle datetime fields
        datetime_fields = ['date_police_notified']
        for field in datetime_fields:
            sanitized[field] = self._parse_datetime(record.get(field))
        
        return sanitized
    
    def sanitize_person_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize a person record.
        
        Args:
            record: Raw person record from API
            
        Returns:
            Sanitized record
        """
        sanitized = {}
        
        # Required fields
        sanitized['crash_record_id'] = self._clean_string(
            record.get('crash_record_id')
        )
        sanitized['person_id'] = self._clean_string(
            record.get('person_id')
        )
        
        # Age validation
        sanitized['age'] = self._clean_age(record.get('age'))
        
        # String fields
        string_fields = [
            'person_type', 'sex', 'safety_equipment', 'airbag_deployed',
            'ejection', 'injury_classification', 'hospital', 'ems_agency',
            'ems_unit', 'drivers_license_state', 'drivers_license_class',
            'physical_condition', 'pedpedal_action', 'pedpedal_visibility',
            'pedpedal_location', 'bac_result', 'cell_phone_use'
        ]
        
        for field in string_fields:
            sanitized[field] = self._clean_string(record.get(field))
        
        # BAC value
        sanitized['bac_result_value'] = self._clean_float(
            record.get('bac_result_value')
        )
        
        # Area injury indicators
        for i in range(13):
            field = f'area_{i:02d}_i'
            sanitized[field] = self._clean_string(record.get(field))
        
        return sanitized
    
    def sanitize_vehicle_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize a vehicle record.
        
        Args:
            record: Raw vehicle record from API
            
        Returns:
            Sanitized record
        """
        sanitized = {}
        
        # Required fields
        sanitized['crash_record_id'] = self._clean_string(
            record.get('crash_record_id')
        )
        sanitized['unit_no'] = self._clean_string(
            record.get('unit_no')
        )
        
        # Vehicle year validation
        sanitized['vehicle_year'] = self._clean_vehicle_year(
            record.get('vehicle_year')
        )
        
        # Integer fields
        integer_fields = ['num_passengers', 'occupant_cnt']
        for field in integer_fields:
            sanitized[field] = self._clean_integer(record.get(field))
        
        # String fields
        string_fields = [
            'unit_type', 'vehicle_id', 'cmv_id', 'make', 'model',
            'lic_plate_state', 'vehicle_defect', 'vehicle_type',
            'vehicle_use', 'travel_direction', 'maneuver', 'towed_i',
            'fire_i', 'hazmat_placard_i', 'hazmat_name', 'hazmat_present_i',
            'first_contact_point'
        ]
        
        for field in string_fields:
            sanitized[field] = self._clean_string(record.get(field))
        
        return sanitized
    
    def sanitize_fatality_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize a fatality record.
        
        Args:
            record: Raw fatality record from API
            
        Returns:
            Sanitized record
        """
        sanitized = {}
        
        # Required fields
        sanitized['person_id'] = self._clean_string(
            record.get('person_id')
        )
        
        # Optional RD number (may link to crash_record_id)
        sanitized['rd_no'] = self._clean_string(
            record.get('rd_no')
        )
        
        # Parse crash date
        sanitized['crash_date'] = self._parse_datetime(
            record.get('crash_date')
        )
        
        # Handle coordinates
        sanitized['latitude'] = self._clean_coordinate(
            record.get('latitude'),
            coord_type='latitude'
        )
        sanitized['longitude'] = self._clean_coordinate(
            record.get('longitude'),
            coord_type='longitude'
        )
        
        # Text fields
        text_fields = ['crash_location', 'crash_circumstances', 'geocoded_column']
        for field in text_fields:
            sanitized[field] = self._clean_text(record.get(field))
        
        # Victim type
        sanitized['victim'] = self._clean_string(record.get('victim'))
        
        return sanitized
    
    def remove_duplicates(
        self,
        records: List[Dict[str, Any]],
        key_field: str
    ) -> List[Dict[str, Any]]:
        """Remove duplicate records based on key field.
        
        Args:
            records: List of records
            key_field: Field to use for deduplication
            
        Returns:
            Deduplicated list of records
        """
        seen_keys = set()
        unique_records = []
        duplicates_count = 0
        
        for record in records:
            key_value = record.get(key_field)
            if key_value and key_value not in seen_keys:
                seen_keys.add(key_value)
                unique_records.append(record)
            else:
                duplicates_count += 1
        
        if duplicates_count > 0:
            logger.warning("Removed duplicate records",
                         duplicates=duplicates_count,
                         key_field=key_field,
                         unique_records=len(unique_records))
        
        return unique_records
    
    def _clean_string(self, value: Any, max_length: Optional[int] = None) -> Optional[str]:
        """Clean and validate string value.
        
        Args:
            value: Raw value
            max_length: Maximum length to truncate to
            
        Returns:
            Cleaned string or None
        """
        if value is None or value == '':
            return None
        
        # Convert to string and strip whitespace
        cleaned = str(value).strip()
        
        if not cleaned:
            return None
        
        # Handle common null values
        if cleaned.upper() in ['NULL', 'N/A', 'UNKNOWN', 'UNK']:
            return None
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Truncate if needed
        if max_length and len(cleaned) > max_length:
            cleaned = cleaned[:max_length]
            logger.debug("Truncated string", 
                        original_length=len(str(value)),
                        truncated_length=len(cleaned))
        
        return cleaned
    
    def _clean_text(self, value: Any) -> Optional[str]:
        """Clean text field (longer strings).
        
        Args:
            value: Raw value
            
        Returns:
            Cleaned text or None
        """
        return self._clean_string(value)
    
    def _clean_integer(self, value: Any) -> Optional[int]:
        """Clean and validate integer value.
        
        Args:
            value: Raw value
            
        Returns:
            Cleaned integer or None
        """
        if value is None or value == '':
            return None
        
        try:
            # Handle string numbers
            if isinstance(value, str):
                value = value.strip()
                if not value or value.upper() in ['NULL', 'N/A']:
                    return None
            
            # Convert to integer
            return int(float(value))  # Handle "1.0" strings
        except (ValueError, TypeError):
            logger.debug("Invalid integer value", value=value)
            return None
    
    def _clean_float(self, value: Any) -> Optional[float]:
        """Clean and validate float value.
        
        Args:
            value: Raw value
            
        Returns:
            Cleaned float or None
        """
        if value is None or value == '':
            return None
        
        try:
            # Handle string numbers
            if isinstance(value, str):
                value = value.strip()
                if not value or value.upper() in ['NULL', 'N/A']:
                    return None
            
            return float(value)
        except (ValueError, TypeError):
            logger.debug("Invalid float value", value=value)
            return None
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime value from various formats.
        
        Args:
            value: Raw datetime value
            
        Returns:
            Parsed datetime or None
        """
        if not value:
            return None
        
        if isinstance(value, datetime):
            return value
        
        # Common datetime formats in Chicago data
        formats = [
            '%Y-%m-%dT%H:%M:%S.%f',  # ISO with microseconds
            '%Y-%m-%dT%H:%M:%S',     # ISO without microseconds
            '%Y-%m-%d %H:%M:%S',     # Space separated
            '%Y-%m-%d',              # Date only
            '%m/%d/%Y %H:%M:%S %p',  # US format with AM/PM
            '%m/%d/%Y'               # US date only
        ]
        
        value_str = str(value).strip()
        
        for fmt in formats:
            try:
                return datetime.strptime(value_str, fmt)
            except ValueError:
                continue
        
        logger.debug("Could not parse datetime", value=value)
        return None
    
    def _clean_coordinate(
        self,
        value: Any,
        coord_type: str
    ) -> Optional[float]:
        """Clean and validate coordinate value.
        
        Args:
            value: Raw coordinate value
            coord_type: 'latitude' or 'longitude'
            
        Returns:
            Cleaned coordinate or None
        """
        coord = self._clean_float(value)
        
        if coord is None:
            return None
        
        # Validate bounds for Chicago area
        if coord_type == 'latitude':
            if not (self.validation_settings.min_latitude <= coord <= self.validation_settings.max_latitude):
                logger.debug("Latitude out of bounds", 
                           latitude=coord,
                           bounds=(self.validation_settings.min_latitude,
                                 self.validation_settings.max_latitude))
                return None
        
        elif coord_type == 'longitude':
            if not (self.validation_settings.min_longitude <= coord <= self.validation_settings.max_longitude):
                logger.debug("Longitude out of bounds",
                           longitude=coord,
                           bounds=(self.validation_settings.min_longitude,
                                 self.validation_settings.max_longitude))
                return None
        
        return coord
    
    def _clean_age(self, value: Any) -> Optional[int]:
        """Clean and validate age value.
        
        Args:
            value: Raw age value
            
        Returns:
            Cleaned age or None
        """
        age = self._clean_integer(value)
        
        if age is None:
            return None
        
        # Validate age range
        if not (self.validation_settings.min_age <= age <= self.validation_settings.max_age):
            logger.debug("Age out of valid range",
                       age=age,
                       range=(self.validation_settings.min_age,
                             self.validation_settings.max_age))
            return None
        
        return age
    
    def _clean_vehicle_year(self, value: Any) -> Optional[int]:
        """Clean and validate vehicle year.
        
        Args:
            value: Raw vehicle year value
            
        Returns:
            Cleaned vehicle year or None
        """
        year = self._clean_integer(value)
        
        if year is None:
            return None
        
        # Validate year range
        if not (self.validation_settings.min_vehicle_year <= year <= self.validation_settings.max_vehicle_year):
            logger.debug("Vehicle year out of valid range",
                       year=year,
                       range=(self.validation_settings.min_vehicle_year,
                             self.validation_settings.max_vehicle_year))
            return None
        
        return year
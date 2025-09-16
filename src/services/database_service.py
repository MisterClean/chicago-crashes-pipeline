"""Database service for managing crash data persistence with upsert functionality."""
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from geoalchemy2.elements import WKTElement
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from models.base import SessionLocal, get_db
from models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from utils.logging import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Service for database operations with upsert functionality."""
    
    def __init__(self):
        self.session_factory = SessionLocal
    
    def _create_geometry(self, latitude: float, longitude: float) -> WKTElement:
        """Create PostGIS geometry from coordinates."""
        if latitude and longitude:
            return WKTElement(f'POINT({longitude} {latitude})', srid=4326)
        return None
    
    def _needs_update(self, existing_record, new_data: Dict[str, Any], last_modified_field: str = None) -> bool:
        """Check if record needs updating based on modification time or data changes."""
        
        # If source has a last modified field, use it
        if last_modified_field and last_modified_field in new_data:
            source_modified = self._parse_datetime(new_data[last_modified_field])
            if source_modified and hasattr(existing_record, 'updated_at'):
                return source_modified > existing_record.updated_at
        
        # For Chicago data, check specific fields that indicate updates
        # Crash data often gets updated with investigation results
        update_indicators = [
            'prim_contributory_cause',
            'sec_contributory_cause', 
            'most_severe_injury',
            'injuries_total',
            'injuries_fatal',
            'damage',
            'report_type'
        ]
        
        for field in update_indicators:
            if field in new_data:
                existing_value = getattr(existing_record, field, None)
                new_value = new_data.get(field)
                
                # Convert to comparable types
                if existing_value != new_value:
                    logger.debug(f"Field {field} changed: '{existing_value}' -> '{new_value}'")
                    return True
        
        return False
    
    def insert_crash_records(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> Dict[str, int]:
        """Upsert crash records into the database in batches."""
        total_inserted = 0
        total_updated = 0  
        total_skipped = 0
        
        # Process records in batches to avoid memory/timeout issues
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(records)-1)//batch_size + 1} ({len(batch)} records)")
            
            result = self._insert_crash_batch(batch)
            total_inserted += result["inserted"]
            total_updated += result["updated"]
            total_skipped += result["skipped"]
        
        return {
            "inserted": total_inserted,
            "updated": total_updated,
            "skipped": total_skipped
        }
    
    def _insert_crash_batch(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Insert a single batch of crash records."""
        db = self.session_factory()
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        
        try:
            for record in records:
                crash_id = record.get('crash_record_id')
                if not crash_id:
                    logger.warning("Skipping record without crash_record_id")
                    skipped_count += 1
                    continue
                
                # Check if record already exists
                existing = db.query(Crash).filter(
                    Crash.crash_record_id == crash_id
                ).first()
                
                if existing:
                    # Check if update is needed
                    if self._needs_update(existing, record):
                        self._update_crash_record(existing, record, db)
                        updated_count += 1
                    else:
                        skipped_count += 1
                        continue
                else:
                    # Insert new record
                    crash = self._create_crash_record(record)
                    db.add(crash)
                    inserted_count += 1
            
            # Commit all changes
            db.commit()
            logger.info(f"Crash records - Inserted: {inserted_count}, Updated: {updated_count}, Skipped: {skipped_count}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error with crash records: {str(e)}")
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Unexpected error with crash records: {str(e)}")
            raise
        finally:
            db.close()
        
        return {
            'inserted': inserted_count,
            'updated': updated_count,
            'skipped': skipped_count
        }
    
    def _create_crash_record(self, record: Dict[str, Any]) -> Crash:
        """Create a new Crash object from record data."""
        # Create geometry from coordinates
        geometry = None
        lat = record.get('latitude')
        lng = record.get('longitude')
        if lat and lng:
            geometry = self._create_geometry(float(lat), float(lng))
        
        return Crash(
            crash_record_id=record.get('crash_record_id'),
            crash_date=self._parse_datetime(record.get('crash_date')),
            crash_date_est_i=record.get('crash_date_est_i'),
            posted_speed_limit=self._parse_int(record.get('posted_speed_limit')),
            traffic_control_device=record.get('traffic_control_device'),
            device_condition=record.get('device_condition'),
            weather_condition=record.get('weather_condition'),
            lighting_condition=record.get('lighting_condition'),
            street_no=record.get('street_no'),
            street_direction=record.get('street_direction'),
            street_name=record.get('street_name'),
            sec_contributory_cause=record.get('sec_contributory_cause'),
            crash_type=record.get('crash_type'),
            latitude=self._parse_float(lat),
            longitude=self._parse_float(lng),
            geometry=geometry,
            beat_of_occurrence=record.get('beat_of_occurrence'),
            photos_taken_i=record.get('photos_taken_i'),
            statements_taken_i=record.get('statements_taken_i'),
            damage=record.get('damage'),
            date_police_notified=self._parse_datetime(record.get('date_police_notified')),
            prim_contributory_cause=record.get('prim_contributory_cause'),
            work_zone_i=record.get('work_zone_i'),
            work_zone_type=record.get('work_zone_type'),
            workers_present_i=record.get('workers_present_i'),
            injuries_total=self._parse_int(record.get('injuries_total'), 0),
            injuries_fatal=self._parse_int(record.get('injuries_fatal'), 0),
            injuries_incapacitating=self._parse_int(record.get('injuries_incapacitating'), 0),
            injuries_non_incapacitating=self._parse_int(record.get('injuries_non_incapacitating'), 0),
            injuries_reported_not_evident=self._parse_int(record.get('injuries_reported_not_evident'), 0),
            injuries_no_indication=self._parse_int(record.get('injuries_no_indication'), 0),
            injuries_unknown=self._parse_int(record.get('injuries_unknown'), 0),
            hit_and_run_i=record.get('hit_and_run_i'),
            dooring_i=record.get('dooring_i'),
            intersection_related_i=record.get('intersection_related_i'),
            not_right_of_way_i=record.get('not_right_of_way_i'),
            lane_cnt=self._parse_int(record.get('lane_cnt')),
            alignment=record.get('alignment'),
            roadway_surface_cond=record.get('roadway_surface_cond'),
            road_defect=record.get('road_defect'),
            report_type=record.get('report_type'),
            most_severe_injury=record.get('most_severe_injury')
        )
    
    def _update_crash_record(self, existing: Crash, record: Dict[str, Any], db: Session):
        """Update an existing crash record with new data."""
        # Update all fields that might change
        existing.crash_date_est_i = record.get('crash_date_est_i')
        existing.posted_speed_limit = self._parse_int(record.get('posted_speed_limit'))
        existing.traffic_control_device = record.get('traffic_control_device')
        existing.device_condition = record.get('device_condition')
        existing.weather_condition = record.get('weather_condition')
        existing.lighting_condition = record.get('lighting_condition')
        existing.damage = record.get('damage')
        existing.date_police_notified = self._parse_datetime(record.get('date_police_notified'))
        existing.prim_contributory_cause = record.get('prim_contributory_cause')
        existing.sec_contributory_cause = record.get('sec_contributory_cause')
        existing.work_zone_i = record.get('work_zone_i')
        existing.work_zone_type = record.get('work_zone_type')
        existing.workers_present_i = record.get('workers_present_i')
        
        # Update injury counts
        existing.injuries_total = self._parse_int(record.get('injuries_total'), 0)
        existing.injuries_fatal = self._parse_int(record.get('injuries_fatal'), 0)
        existing.injuries_incapacitating = self._parse_int(record.get('injuries_incapacitating'), 0)
        existing.injuries_non_incapacitating = self._parse_int(record.get('injuries_non_incapacitating'), 0)
        existing.injuries_reported_not_evident = self._parse_int(record.get('injuries_reported_not_evident'), 0)
        existing.injuries_no_indication = self._parse_int(record.get('injuries_no_indication'), 0)
        existing.injuries_unknown = self._parse_int(record.get('injuries_unknown'), 0)
        
        # Update other fields that might change during investigation
        existing.hit_and_run_i = record.get('hit_and_run_i')
        existing.dooring_i = record.get('dooring_i')
        existing.intersection_related_i = record.get('intersection_related_i')
        existing.not_right_of_way_i = record.get('not_right_of_way_i')
        existing.report_type = record.get('report_type')
        existing.most_severe_injury = record.get('most_severe_injury')
        existing.photos_taken_i = record.get('photos_taken_i')
        existing.statements_taken_i = record.get('statements_taken_i')
        
        # Update coordinates if they changed (rare but possible)
        lat = record.get('latitude')
        lng = record.get('longitude')
        if lat and lng:
            existing.latitude = self._parse_float(lat)
            existing.longitude = self._parse_float(lng)
            existing.geometry = self._create_geometry(float(lat), float(lng))
        
        # SQLAlchemy will automatically update the updated_at timestamp via TimestampMixin
        logger.debug(f"Updated crash record {existing.crash_record_id[:10]}...")
    
    def insert_person_records(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Upsert person records into the database."""
        db = self.session_factory()
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        
        try:
            for record in records:
                crash_id = record.get('crash_record_id')
                person_id = record.get('person_id')
                
                if not crash_id or not person_id:
                    skipped_count += 1
                    continue
                
                existing = db.query(CrashPerson).filter(
                    CrashPerson.crash_record_id == crash_id,
                    CrashPerson.person_id == person_id
                ).first()
                
                if existing:
                    if self._needs_update(existing, record):
                        self._update_person_record(existing, record, db)
                        updated_count += 1
                    else:
                        skipped_count += 1
                else:
                    person = self._create_person_record(record)
                    db.add(person)
                    inserted_count += 1
            
            db.commit()
            logger.info(f"Person records - Inserted: {inserted_count}, Updated: {updated_count}, Skipped: {skipped_count}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error with person records: {str(e)}")
            raise
        finally:
            db.close()
        
        return {
            'inserted': inserted_count,
            'updated': updated_count,
            'skipped': skipped_count
        }
    
    def _create_person_record(self, record: Dict[str, Any]) -> CrashPerson:
        """Create a new CrashPerson object from record data."""
        return CrashPerson(
            crash_record_id=record.get('crash_record_id'),
            person_id=record.get('person_id'),
            crash_date=self._parse_datetime(record.get('crash_date')),
            vehicle_id=record.get('vehicle_id'),
            person_type=record.get('person_type'),
            age=self._parse_int(record.get('age')),
            sex=record.get('sex'),
            safety_equipment=record.get('safety_equipment'),
            airbag_deployed=record.get('airbag_deployed'),
            ejection=record.get('ejection'),
            injury_classification=record.get('injury_classification'),
            hospital=record.get('hospital'),
            ems_agency=record.get('ems_agency'),
            ems_unit=record.get('ems_unit'),
            drivers_license_state=record.get('drivers_license_state'),
            drivers_license_class=record.get('drivers_license_class'),
            driver_action=record.get('driver_action'),
            driver_vision=record.get('driver_vision'),
            physical_condition=record.get('physical_condition'),
            pedpedal_action=record.get('pedpedal_action'),
            pedpedal_visibility=record.get('pedpedal_visibility'),
            pedpedal_location=record.get('pedpedal_location'),
            bac_result=record.get('bac_result'),
            bac_result_value=self._parse_float(record.get('bac_result_value')),
            cell_phone_use=record.get('cell_phone_use')
        )
    
    def _update_person_record(self, existing: CrashPerson, record: Dict[str, Any], db: Session):
        """Update an existing person record with new data."""
        existing.crash_date = self._parse_datetime(record.get('crash_date'))
        existing.vehicle_id = record.get('vehicle_id')
        existing.injury_classification = record.get('injury_classification')
        existing.hospital = record.get('hospital')
        existing.ems_agency = record.get('ems_agency')
        existing.ems_unit = record.get('ems_unit')
        existing.driver_action = record.get('driver_action')
        existing.driver_vision = record.get('driver_vision')
        existing.physical_condition = record.get('physical_condition')
        existing.bac_result = record.get('bac_result')
        existing.bac_result_value = self._parse_float(record.get('bac_result_value'))
        existing.cell_phone_use = record.get('cell_phone_use')
    
    # Similar upsert methods for vehicles and fatalities...
    def insert_vehicle_records(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Upsert vehicle records into the database."""
        db = self.session_factory()
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        
        try:
            for record in records:
                crash_unit_id = record.get('crash_unit_id')
                
                if not crash_unit_id:
                    logger.warning("Skipping vehicle record without crash_unit_id")
                    skipped_count += 1
                    continue
                
                existing = db.query(CrashVehicle).filter(
                    CrashVehicle.crash_unit_id == crash_unit_id
                ).first()
                
                if existing:
                    if self._needs_update(existing, record):
                        self._update_vehicle_record(existing, record, db)
                        updated_count += 1
                    else:
                        skipped_count += 1
                else:
                    vehicle = self._create_vehicle_record(record)
                    db.add(vehicle)
                    inserted_count += 1
            
            db.commit()
            logger.info(f"Vehicle records - Inserted: {inserted_count}, Updated: {updated_count}, Skipped: {skipped_count}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error with vehicle records: {str(e)}")
            raise
        finally:
            db.close()
        
        return {
            'inserted': inserted_count,
            'updated': updated_count,
            'skipped': skipped_count
        }
    
    def _create_vehicle_record(self, record: Dict[str, Any]) -> CrashVehicle:
        """Create a new CrashVehicle object from record data."""
        return CrashVehicle(
            crash_unit_id=record.get('crash_unit_id'),
            crash_record_id=record.get('crash_record_id'),
            unit_no=record.get('unit_no'),
            crash_date=self._parse_datetime(record.get('crash_date')),
            unit_type=record.get('unit_type'),
            num_passengers=self._parse_int(record.get('num_passengers')),
            vehicle_id=record.get('vehicle_id'),
            cmv_id=record.get('cmv_id'),
            make=record.get('make'),
            model=record.get('model'),
            lic_plate_state=record.get('lic_plate_state'),
            vehicle_year=self._parse_int(record.get('vehicle_year')),
            vehicle_defect=record.get('vehicle_defect'),
            vehicle_type=record.get('vehicle_type'),
            vehicle_use=record.get('vehicle_use'),
            travel_direction=record.get('travel_direction'),
            maneuver=record.get('maneuver'),
            towed_i=record.get('towed_i'),
            fire_i=record.get('fire_i'),
            hazmat_placard_i=record.get('hazmat_placard_i'),
            hazmat_name=record.get('hazmat_name'),
            hazmat_present_i=record.get('hazmat_present_i'),
            occupant_cnt=self._parse_int(record.get('occupant_cnt')),
            first_contact_point=record.get('first_contact_point')
        )
    
    def _update_vehicle_record(self, existing: CrashVehicle, record: Dict[str, Any], db: Session):
        """Update an existing vehicle record with new data."""
        existing.crash_date = self._parse_datetime(record.get('crash_date'))
        existing.vehicle_defect = record.get('vehicle_defect')
        existing.towed_i = record.get('towed_i')
        existing.fire_i = record.get('fire_i')
        existing.hazmat_placard_i = record.get('hazmat_placard_i')
        existing.hazmat_name = record.get('hazmat_name')
        existing.hazmat_present_i = record.get('hazmat_present_i')
        existing.occupant_cnt = self._parse_int(record.get('occupant_cnt'))
        existing.first_contact_point = record.get('first_contact_point')
    
    def insert_fatality_records(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Upsert fatality records into the database."""
        db = self.session_factory()
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        
        try:
            for record in records:
                person_id = record.get('person_id')
                if not person_id:
                    skipped_count += 1
                    continue
                
                existing = db.query(VisionZeroFatality).filter(
                    VisionZeroFatality.person_id == person_id
                ).first()
                
                if existing:
                    if self._needs_update(existing, record):
                        self._update_fatality_record(existing, record, db)
                        updated_count += 1
                    else:
                        skipped_count += 1
                else:
                    fatality = self._create_fatality_record(record)
                    db.add(fatality)
                    inserted_count += 1
            
            db.commit()
            logger.info(f"Fatality records - Inserted: {inserted_count}, Updated: {updated_count}, Skipped: {skipped_count}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error with fatality records: {str(e)}")
            raise
        finally:
            db.close()
        
        return {
            'inserted': inserted_count,
            'updated': updated_count,
            'skipped': skipped_count
        }
    
    def _create_fatality_record(self, record: Dict[str, Any]) -> VisionZeroFatality:
        """Create a new VisionZeroFatality object from record data."""
        # Create geometry from coordinates
        geometry = None
        lat = record.get('latitude')
        lng = record.get('longitude')
        if lat and lng:
            geometry = self._create_geometry(float(lat), float(lng))
        
        return VisionZeroFatality(
            person_id=record.get('person_id'),
            rd_no=record.get('rd_no'),
            crash_date=self._parse_datetime(record.get('crash_date')),
            crash_location=record.get('crash_location'),
            victim=record.get('victim'),
            crash_circumstances=record.get('crash_circumstances'),
            longitude=self._parse_float(lng),
            latitude=self._parse_float(lat),
            geometry=geometry,
            geocoded_column=record.get('geocoded_column')
        )
    
    def _update_fatality_record(self, existing: VisionZeroFatality, record: Dict[str, Any], db: Session):
        """Update an existing fatality record with new data."""
        existing.crash_circumstances = record.get('crash_circumstances')
        existing.geocoded_column = record.get('geocoded_column')
        
        # Update coordinates if they changed
        lat = record.get('latitude')
        lng = record.get('longitude')
        if lat and lng:
            existing.latitude = self._parse_float(lat)
            existing.longitude = self._parse_float(lng)
            existing.geometry = self._create_geometry(float(lat), float(lng))
    
    def get_record_counts(self) -> Dict[str, int]:
        """Get current record counts for all tables."""
        db = self.session_factory()
        try:
            # Use table-aligned keys so API consumers can display counts without
            # guessing the mapping between logical names and actual tables.
            counts = {
                'crashes': db.query(Crash).count(),
                'crash_people': db.query(CrashPerson).count(),
                'crash_vehicles': db.query(CrashVehicle).count(),
                'vision_zero_fatalities': db.query(VisionZeroFatality).count()
            }
            return counts
        except Exception as e:
            logger.error(f"Error getting record counts: {str(e)}")
            return {}
        finally:
            db.close()
    
    def _parse_datetime(self, value: Any) -> datetime:
        """Parse datetime from various formats."""
        if not value:
            return None
        
        if isinstance(value, datetime):
            return value
        
        if isinstance(value, str):
            # Handle ISO format
            try:
                return datetime.fromisoformat(value.replace('T', ' ').replace('Z', ''))
            except ValueError:
                pass
            
            # Handle other common formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y']:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        
        return None
    
    def _parse_int(self, value: Any, default: int = None) -> int:
        """Parse integer from various formats."""
        if value is None or value == '':
            return default
        
        try:
            return int(float(value))  # Handle strings like "1.0"
        except (ValueError, TypeError):
            return default
    
    def _parse_float(self, value: Any) -> float:
        """Parse float from various formats."""
        if value is None or value == '':
            return None
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

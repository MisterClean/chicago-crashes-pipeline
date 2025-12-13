"""Models for crash data from Chicago Open Data Portal."""
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class Crash(Base, TimestampMixin):
    """Main crash record from Traffic Crashes - Crashes dataset."""

    __tablename__ = "crashes"

    # Primary key
    crash_record_id = Column(String(128), primary_key=True)

    # Basic crash information
    crash_date = Column(DateTime, nullable=False, index=True)
    crash_date_est_i = Column(String(1))  # Y/N indicator if date is estimated

    # Location information
    posted_speed_limit = Column(Integer)
    traffic_control_device = Column(String(50))
    device_condition = Column(String(50))
    weather_condition = Column(String(50))
    lighting_condition = Column(String(50))

    # Street information
    street_no = Column(String(10))
    street_direction = Column(String(5))
    street_name = Column(String(100))

    # Cross street
    sec_contributory_cause = Column(String(100))
    street_direction_2 = Column(String(5))
    street_name_2 = Column(String(100))

    # Crash characteristics
    crash_type = Column(String(100))
    crash_record_id_original = Column(String(128))
    crash_date_original = Column(DateTime)

    # Location coordinates
    latitude = Column(Float, index=True)
    longitude = Column(Float, index=True)
    geometry = Column(Geometry("POINT", srid=4326), index=True)

    # Beat and location codes
    beat_of_occurrence = Column(String(10))
    photos_taken_i = Column(String(1))
    statements_taken_i = Column(String(1))

    # Damage and injuries
    damage = Column(String(50))
    date_police_notified = Column(DateTime)
    prim_contributory_cause = Column(String(100))
    sec_contributory_cause = Column(String(100))

    # Work zone information
    work_zone_i = Column(String(1))
    work_zone_type = Column(String(50))
    workers_present_i = Column(String(1))

    # Injury totals
    injuries_total = Column(Integer, default=0)
    injuries_fatal = Column(Integer, default=0)
    injuries_incapacitating = Column(Integer, default=0)
    injuries_non_incapacitating = Column(Integer, default=0)
    injuries_reported_not_evident = Column(Integer, default=0)
    injuries_no_indication = Column(Integer, default=0)
    injuries_unknown = Column(Integer, default=0)

    # Hit and run
    hit_and_run_i = Column(String(1))

    # Dooring related
    dooring_i = Column(String(1))

    # Intersection related
    intersection_related_i = Column(String(1))
    not_right_of_way_i = Column(String(1))

    # Lane information
    lane_cnt = Column(Integer)
    alignment = Column(String(50))
    roadway_surface_cond = Column(String(50))
    road_defect = Column(String(50))

    # Report information
    report_type = Column(String(50))

    # Most severe injury
    most_severe_injury = Column(String(50))

    # Relationships
    people = relationship("CrashPerson", back_populates="crash")
    vehicles = relationship("CrashVehicle", back_populates="crash")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_crashes_date_location", "crash_date", "latitude", "longitude"),
        Index("ix_crashes_beat", "beat_of_occurrence"),
        Index("ix_crashes_injuries", "injuries_total"),
        Index("ix_crashes_fatal", "injuries_fatal"),
        Index("ix_crashes_hit_run", "hit_and_run_i"),
    )


class CrashPerson(Base, TimestampMixin):
    """Person-level data from Traffic Crashes - People dataset."""

    __tablename__ = "crash_people"

    # Composite primary key
    crash_record_id = Column(
        String(128), ForeignKey("crashes.crash_record_id"), primary_key=True
    )
    person_id = Column(String(128), primary_key=True)

    # Basic information
    crash_date = Column(DateTime)
    vehicle_id = Column(String(20))

    # Person demographics
    person_type = Column(String(50))  # DRIVER, PASSENGER, PEDESTRIAN, etc.
    age = Column(Integer)
    sex = Column(String(10))

    # Safety equipment
    safety_equipment = Column(String(100))
    airbag_deployed = Column(String(50))
    ejection = Column(String(50))

    # Injury information
    injury_classification = Column(String(50))
    hospital = Column(String(100))
    ems_agency = Column(String(50))
    ems_unit = Column(String(50))  # Increased from 20 to 50
    area_00_i = Column(String(1))
    area_01_i = Column(String(1))
    area_02_i = Column(String(1))
    area_03_i = Column(String(1))
    area_04_i = Column(String(1))
    area_05_i = Column(String(1))
    area_06_i = Column(String(1))
    area_07_i = Column(String(1))
    area_08_i = Column(String(1))
    area_09_i = Column(String(1))
    area_10_i = Column(String(1))
    area_11_i = Column(String(1))
    area_12_i = Column(String(1))

    # Driver information (if applicable)
    drivers_license_state = Column(String(10))
    drivers_license_class = Column(String(50))  # Increased from 20 to 50
    driver_action = Column(String(100))  # New field
    driver_vision = Column(String(50))  # New field

    # Physical condition
    physical_condition = Column(String(50))

    # Pedestrian information
    pedpedal_action = Column(String(100))
    pedpedal_visibility = Column(String(50))
    pedpedal_location = Column(String(100))
    bac_result = Column(String(50))  # Increased from 20 to 50
    bac_result_value = Column(Float)

    # Cell phone usage
    cell_phone_use = Column(String(50))

    # Relationship
    crash = relationship("Crash", back_populates="people")

    # Indexes
    __table_args__ = (
        Index("ix_people_person_type", "person_type"),
        Index("ix_people_injury", "injury_classification"),
        Index("ix_people_age", "age"),
    )


class CrashVehicle(Base, TimestampMixin):
    """Vehicle/unit data from Traffic Crashes - Vehicles dataset."""

    __tablename__ = "crash_vehicles"

    # Primary key - CRASH_UNIT_ID is unique identifier for each vehicle record
    crash_unit_id = Column(String(20), primary_key=True)

    # Foreign key to crashes table
    crash_record_id = Column(
        String(128), ForeignKey("crashes.crash_record_id"), nullable=False, index=True
    )
    unit_no = Column(String(10))

    # Basic information
    crash_date = Column(DateTime)

    # Unit information
    unit_type = Column(String(50))
    num_passengers = Column(Integer)

    # Vehicle information
    vehicle_id = Column(String(50))
    cmv_id = Column(String(50))
    make = Column(String(100))  # Increased from 50 to 100
    model = Column(String(100))  # Increased from 50 to 100
    lic_plate_state = Column(String(10))
    vehicle_year = Column(Integer)
    vehicle_defect = Column(String(100))
    vehicle_type = Column(String(100))  # Increased from 50 to 100
    vehicle_use = Column(String(50))
    travel_direction = Column(String(10))  # Increased from 5 to 10
    maneuver = Column(String(100))  # Keep at 100 for longer maneuver descriptions
    towed_i = Column(String(1))
    fire_i = Column(String(1))

    # Commercial vehicle information
    hazmat_placard_i = Column(String(1))
    hazmat_name = Column(String(100))
    hazmat_present_i = Column(String(1))

    # Occupant counts by injury type
    occupant_cnt = Column(Integer)

    # First harmful event
    first_contact_point = Column(String(50))

    # Relationship
    crash = relationship("Crash", back_populates="vehicles")

    # Indexes
    __table_args__ = (
        Index("ix_vehicles_type", "vehicle_type"),
        Index("ix_vehicles_year", "vehicle_year"),
        Index("ix_vehicles_make", "make"),
    )


class VisionZeroFatality(Base, TimestampMixin):
    """Fatality records from Vision Zero Chicago Traffic Fatalities dataset."""

    __tablename__ = "vision_zero_fatalities"

    # Primary key
    person_id = Column(String(128), primary_key=True)

    # Crash information
    rd_no = Column(String(50), index=True)  # Links to crash_record_id potentially
    crash_date = Column(DateTime, nullable=False, index=True)
    crash_location = Column(Text)

    # Victim information
    victim = Column(String(50))  # PEDESTRIAN, CYCLIST, DRIVER, etc.
    crash_circumstances = Column(Text)

    # Location
    longitude = Column(Float)
    latitude = Column(Float)
    geometry = Column(Geometry("POINT", srid=4326), index=True)

    # Additional fields that may be present
    geocoded_column = Column(Text)

    # Indexes
    __table_args__ = (
        Index("ix_fatalities_date", "crash_date"),
        Index("ix_fatalities_victim", "victim"),
        Index("ix_fatalities_rd_no", "rd_no"),
    )

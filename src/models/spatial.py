"""Spatial models for geographic boundaries and reference data."""
from geoalchemy2 import Geometry
from sqlalchemy import Column, Integer, String, Float, Text

from .base import Base, TimestampMixin


class Ward(Base, TimestampMixin):
    """Chicago ward boundaries."""
    
    __tablename__ = "wards"
    
    ward = Column(Integer, primary_key=True)
    ward_name = Column(String(100))
    alderman = Column(String(100))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Additional fields that might be present
    area_num_1 = Column(String(10))
    shape_area = Column(Float)
    shape_len = Column(Float)


class CommunityArea(Base, TimestampMixin):
    """Chicago community area boundaries."""
    
    __tablename__ = "community_areas"
    
    area_numbe = Column(Integer, primary_key=True)  # Matches shapefile field name
    community = Column(String(100))
    area_num_1 = Column(String(10))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Area measurements
    shape_area = Column(Float)
    shape_len = Column(Float)


class CensusTract(Base, TimestampMixin):
    """Census tract boundaries."""
    
    __tablename__ = "census_tracts"
    
    tractce10 = Column(String(10), primary_key=True)
    geoid10 = Column(String(20), index=True)
    name10 = Column(String(100))
    namelsad10 = Column(String(100))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Area measurements
    aland10 = Column(Float)  # Land area
    awater10 = Column(Float)  # Water area


class PoliceBeat(Base, TimestampMixin):
    """Chicago police beat boundaries."""
    
    __tablename__ = "police_beats"
    
    beat_num = Column(String(10), primary_key=True)
    beat = Column(String(10))
    district = Column(String(10), index=True)
    sector = Column(String(10))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Area measurements
    shape_area = Column(Float)
    shape_len = Column(Float)


class HouseDistrict(Base, TimestampMixin):
    """Illinois House district boundaries."""
    
    __tablename__ = "house_districts"
    
    district = Column(String(10), primary_key=True)
    rep_name = Column(String(100))
    party = Column(String(20))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Additional fields
    population = Column(Integer)
    shape_area = Column(Float)
    shape_len = Column(Float)


class SenateDistrict(Base, TimestampMixin):
    """Illinois Senate district boundaries."""
    
    __tablename__ = "senate_districts"
    
    district = Column(String(10), primary_key=True)
    senator_name = Column(String(100))
    party = Column(String(20))
    geometry = Column(Geometry('MULTIPOLYGON', srid=4326), index=True)
    
    # Additional fields
    population = Column(Integer)
    shape_area = Column(Float)
    shape_len = Column(Float)
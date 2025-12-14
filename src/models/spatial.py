"""Spatial models for geographic boundaries and reference data."""

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class Ward(Base, TimestampMixin):
    """Chicago ward boundaries."""

    __tablename__ = "wards"

    ward = Column(Integer, primary_key=True)
    ward_name = Column(String(100))
    alderman = Column(String(100))
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

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
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

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
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

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
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

    # Area measurements
    shape_area = Column(Float)
    shape_len = Column(Float)


class HouseDistrict(Base, TimestampMixin):
    """Illinois House district boundaries."""

    __tablename__ = "house_districts"

    district = Column(String(10), primary_key=True)
    rep_name = Column(String(100))
    party = Column(String(20))
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

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
    geometry = Column(Geometry("MULTIPOLYGON", srid=4326), index=True)

    # Additional fields
    population = Column(Integer)
    shape_area = Column(Float)
    shape_len = Column(Float)


class SpatialLayer(Base, TimestampMixin):
    """User-managed GeoJSON layer metadata."""

    __tablename__ = "spatial_layers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), unique=True, nullable=False)
    slug = Column(String(160), unique=True, nullable=False)
    description = Column(Text)
    geometry_type = Column(String(64), nullable=False)
    srid = Column(Integer, default=4326, nullable=False)
    feature_count = Column(Integer, default=0, nullable=False)
    original_filename = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)

    features = relationship(
        "SpatialLayerFeature",
        back_populates="layer",
        cascade="all, delete-orphan",
    )


class SpatialLayerFeature(Base, TimestampMixin):
    """Individual GeoJSON feature stored in PostGIS."""

    __tablename__ = "spatial_layer_features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    layer_id = Column(
        Integer,
        ForeignKey("spatial_layers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    properties = Column(JSONB, default=dict, nullable=False)
    geometry = Column(Geometry("GEOMETRY", srid=4326), nullable=False, index=True)

    layer = relationship("SpatialLayer", back_populates="features")

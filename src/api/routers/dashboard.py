"""Dashboard API endpoints for the Chicago Crash Dashboard frontend."""

import csv
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime, time, timedelta
from typing import Any, Iterable, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.models.base import get_db
from src.models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Chicago timezone - all crash data from the Chicago Data Portal is in local Chicago time
CHICAGO_TZ = ZoneInfo("America/Chicago")

# FHWA Crash Cost Constants (2024$)
# Source: https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf
# KABCO Person-Injury Unit Costs
# Note: "No Indication of Injury" (O) has $0 person cost to avoid double-counting with vehicle damage
KABCO_COSTS = {
    # injury_classification: (economic, qaly, comprehensive)
    "FATAL": (1_606_644, 9_651_851, 11_258_495),  # K
    "INCAPACITATING INJURY": (172_179, 917_345, 1_089_524),  # A
    "NONINCAPACITATING INJURY": (44_490, 180_107, 224_597),  # B
    "REPORTED, NOT EVIDENT": (25_933, 85_348, 111_281),  # C
    "NO INDICATION OF INJURY": (0, 0, 0),  # O - vehicle damage captured separately
}

# Vehicle unit costs (FHWA "O" classification costs applied per vehicle)
# These represent property damage and related costs for crashes without injuries
VEHICLE_ECONOMIC_COST = 6_269
VEHICLE_QALY_COST = 3_927

# Mapping from injury_classification values to KABCO keys
INJURY_TO_KABCO = {
    "FATAL": "FATAL",
    "INCAPACITATING INJURY": "INCAPACITATING INJURY",
    "NONINCAPACITATING INJURY": "NONINCAPACITATING INJURY",
    "REPORTED, NOT EVIDENT": "REPORTED, NOT EVIDENT",
    "NO INDICATION OF INJURY": "NO INDICATION OF INJURY",
}

# Human-readable labels for KABCO classifications
KABCO_LABELS = {
    "FATAL": "Fatal (K)",
    "INCAPACITATING INJURY": "Incapacitating (A)",
    "NONINCAPACITATING INJURY": "Non-incapacitating (B)",
    "REPORTED, NOT EVIDENT": "Possible Injury (C)",
    "NO INDICATION OF INJURY": "No Indication (O)",
}


def now_chicago() -> datetime:
    """Get current time in Chicago timezone as a naive datetime.

    The crash data is stored as naive timestamps in Chicago local time,
    so we need to compare against Chicago time, not UTC or server time.
    """
    return datetime.now(CHICAGO_TZ).replace(tzinfo=None)


def normalize_end_date(end_date: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize end_date to end of day (23:59:59.999999).

    When users select a date like 2024-01-31, they expect it to include
    all crashes on that day. FastAPI parses date strings to midnight,
    so we need to extend to end of day for inclusive filtering.
    """
    if end_date is None:
        return None
    # If time is midnight (default from date-only input), extend to end of day
    if end_date.time() == time(0, 0, 0):
        return datetime.combine(end_date.date(), time(23, 59, 59, 999999))
    return end_date


def _build_location_report_filters(
    request: "LocationReportRequest",
    db: Session,
) -> tuple[str, dict, dict]:
    has_radius_query = all([
        request.latitude is not None,
        request.longitude is not None,
        request.radius_feet is not None,
    ])
    has_polygon_query = request.polygon is not None and len(request.polygon) >= 3
    has_place_query = request.place_type is not None and request.place_id is not None

    if not has_radius_query and not has_polygon_query and not has_place_query:
        raise HTTPException(
            status_code=400,
            detail="Must provide either (latitude, longitude, radius_feet), polygon coordinates, or (place_type, place_id)",
        )

    if has_place_query:
        place_geometry_result = _get_place_geometry(
            db, request.place_type, request.place_id
        )
        if not place_geometry_result:
            raise HTTPException(
                status_code=404,
                detail=f"Place not found: {request.place_type}/{request.place_id}",
            )

        place_name, place_geometry = place_geometry_result

        spatial_filter_template = """
            ST_Contains(
                ST_SetSRID(ST_GeomFromGeoJSON(:place_geojson), 4326),
                {geometry_column}
            )
        """
        spatial_params = {"place_geojson": json.dumps(place_geometry)}

        query_area_geojson = {
            "type": "Feature",
            "geometry": place_geometry,
            "properties": {
                "type": "place",
                "place_type": request.place_type,
                "place_id": request.place_id,
                "name": place_name,
            },
        }
    elif has_radius_query:
        radius_meters = request.radius_feet * 0.3048

        spatial_filter_template = """
            ST_DWithin(
                {geometry_column}::geography,
                ST_SetSRID(ST_MakePoint(:center_lng, :center_lat), 4326)::geography,
                :radius_meters
            )
        """
        spatial_params = {
            "center_lat": request.latitude,
            "center_lng": request.longitude,
            "radius_meters": radius_meters,
        }

        query_area_sql = text("""
            SELECT ST_AsGeoJSON(
                ST_Buffer(
                    ST_SetSRID(ST_MakePoint(:center_lng, :center_lat), 4326)::geography,
                    :radius_meters
                )::geometry
            ) AS geojson
        """)
        area_result = db.execute(query_area_sql, spatial_params).fetchone()
        query_area_geojson = {
            "type": "Feature",
            "geometry": json.loads(area_result.geojson) if area_result else None,
            "properties": {
                "type": "radius",
                "center": [request.longitude, request.latitude],
                "radius_feet": request.radius_feet,
            },
        }
    else:
        coords = request.polygon.copy()
        if coords[0] != coords[-1]:
            coords.append(coords[0])

        coord_str = ", ".join([f"{c[0]} {c[1]}" for c in coords])
        polygon_wkt = f"POLYGON(({coord_str}))"

        spatial_filter_template = """
            ST_Contains(
                ST_SetSRID(ST_GeomFromText(:polygon_wkt), 4326),
                {geometry_column}
            )
        """
        spatial_params = {"polygon_wkt": polygon_wkt}

        query_area_geojson = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords],
            },
            "properties": {"type": "polygon"},
        }

    return spatial_filter_template, spatial_params, query_area_geojson


def _build_date_filter(
    request: "LocationReportRequest",
    spatial_params: dict,
    date_column: str,
) -> str:
    date_filters = []
    if request.start_date:
        date_filters.append(f"{date_column} >= :start_date")
        spatial_params["start_date"] = request.start_date
    end_date_normalized = normalize_end_date(request.end_date)
    if end_date_normalized:
        date_filters.append(f"{date_column} <= :end_date")
        spatial_params["end_date"] = end_date_normalized
    if not date_filters:
        return ""
    return " AND " + " AND ".join(date_filters)


def _stream_csv(result) -> Iterable[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(result.keys())
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in result:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def _build_select_list(model, alias: str, geometry_column: str | None = None) -> str:
    columns = []
    for column in model.__table__.columns:
        if geometry_column and column.name == geometry_column:
            continue
        columns.append(f"{alias}.{column.name}")
    if geometry_column:
        columns.append(f"ST_AsText({alias}.{geometry_column}) AS {geometry_column}")
    return ", ".join(columns)


class DashboardStats(BaseModel):
    """Aggregate statistics for the dashboard."""

    total_crashes: int
    total_injuries: int
    total_fatalities: int
    pedestrians_involved: int
    cyclists_involved: int
    hit_and_run_count: int


class WeeklyTrend(BaseModel):
    """Weekly trend data point."""

    week: str
    crashes: int
    injuries: int
    fatalities: int


class CrashFeatureProperties(BaseModel):
    """Properties for a crash GeoJSON feature."""

    crash_record_id: str
    crash_date: datetime
    injuries_total: int
    injuries_fatal: int
    injuries_incapacitating: int
    hit_and_run_i: Optional[str]
    crash_type: Optional[str]
    street_name: Optional[str]
    prim_contributory_cause: Optional[str]


class CrashFeature(BaseModel):
    """GeoJSON Feature for a crash."""

    type: str = "Feature"
    geometry: dict
    properties: CrashFeatureProperties


class CrashGeoJSON(BaseModel):
    """GeoJSON FeatureCollection for crashes."""

    type: str = "FeatureCollection"
    features: list[CrashFeature]


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
) -> DashboardStats:
    """
    Get aggregate statistics for dashboard metric cards.

    Optionally filter by date range. End date is inclusive (includes all of that day).
    """
    try:
        # Normalize end_date to include the full day
        end_date_normalized = normalize_end_date(end_date)

        # Build base query for crashes
        crash_query = db.query(Crash)
        if start_date:
            crash_query = crash_query.filter(Crash.crash_date >= start_date)
        if end_date_normalized:
            crash_query = crash_query.filter(Crash.crash_date <= end_date_normalized)

        # Get crash statistics
        total_crashes = crash_query.count()

        stats = crash_query.with_entities(
            func.coalesce(func.sum(Crash.injuries_total), 0).label("injuries"),
            func.coalesce(func.sum(Crash.injuries_fatal), 0).label("fatalities"),
        ).first()

        total_injuries = int(stats.injuries) if stats else 0
        total_fatalities = int(stats.fatalities) if stats else 0

        # Count hit and run
        hit_and_run_count = crash_query.filter(Crash.hit_and_run_i == "Y").count()

        # Get pedestrian and cyclist counts from people table
        people_query = db.query(CrashPerson)
        if start_date:
            people_query = people_query.filter(CrashPerson.crash_date >= start_date)
        if end_date_normalized:
            people_query = people_query.filter(CrashPerson.crash_date <= end_date_normalized)

        pedestrians = people_query.filter(
            CrashPerson.person_type.ilike("%PEDESTRIAN%")
        ).count()

        cyclists = people_query.filter(
            CrashPerson.person_type.ilike("%BICYCLE%")
            | CrashPerson.person_type.ilike("%CYCLIST%")
            | CrashPerson.person_type.ilike("%PEDALCYCLIST%")
        ).count()

        return DashboardStats(
            total_crashes=total_crashes,
            total_injuries=total_injuries,
            total_fatalities=total_fatalities,
            pedestrians_involved=pedestrians,
            cyclists_involved=cyclists,
            hit_and_run_count=hit_and_run_count,
        )

    except Exception as e:
        logger.error("Failed to get dashboard stats", error=str(e))
        raise


@router.get("/trends/weekly", response_model=list[WeeklyTrend])
async def get_weekly_trends(
    weeks: Optional[int] = Query(default=None, le=104, ge=1),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
) -> list[WeeklyTrend]:
    """
    Get weekly crash trends for charts.

    Returns crash, injury, and fatality counts grouped by week.
    Supports either a weeks parameter (going back from today) or explicit date range.
    If start_date/end_date are provided, they take precedence over weeks.
    End date is inclusive (includes all of that day).
    """
    try:
        # Determine date range
        if start_date is not None or end_date is not None:
            # Use explicit date range
            query_start_date = start_date
            query_end_date = normalize_end_date(end_date)
        elif weeks is not None:
            # Calculate start date using Chicago timezone
            query_start_date = now_chicago() - timedelta(weeks=weeks)
            query_end_date = None
        else:
            # Default to 52 weeks
            query_start_date = now_chicago() - timedelta(weeks=52)
            query_end_date = None

        # Query for weekly aggregates using PostgreSQL date_trunc
        query = text("""
            SELECT
                date_trunc('week', crash_date)::date AS week_start,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE crash_date IS NOT NULL
                AND (:start_date IS NULL OR crash_date >= :start_date)
                AND (:end_date IS NULL OR crash_date <= :end_date)
            GROUP BY date_trunc('week', crash_date)
            ORDER BY week_start
        """)

        result = db.execute(query, {"start_date": query_start_date, "end_date": query_end_date})
        rows = result.fetchall()

        trends = []
        for row in rows:
            trends.append(
                WeeklyTrend(
                    week=row.week_start.strftime("%Y-%m-%d"),
                    crashes=row.crashes,
                    injuries=int(row.injuries),
                    fatalities=int(row.fatalities),
                )
            )

        return trends

    except Exception as e:
        logger.error("Failed to get weekly trends", error=str(e))
        raise


@router.get("/crashes/geojson")
async def get_crashes_geojson(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=10000, le=50000, ge=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get crashes as GeoJSON FeatureCollection for map display.

    Returns crash points with properties needed for visualization.
    Limited to 50,000 records max to avoid overwhelming the client.
    End date is inclusive (includes all of that day).
    """
    try:
        # Normalize end_date to include the full day
        end_date_normalized = normalize_end_date(end_date)

        # Use raw SQL for efficient GeoJSON generation
        query = text("""
            SELECT
                crash_record_id,
                crash_date,
                injuries_total,
                injuries_fatal,
                injuries_incapacitating,
                hit_and_run_i,
                crash_type,
                street_name,
                prim_contributory_cause,
                ST_X(geometry) AS longitude,
                ST_Y(geometry) AS latitude
            FROM crashes
            WHERE geometry IS NOT NULL
                AND (:start_date IS NULL OR crash_date >= :start_date)
                AND (:end_date IS NULL OR crash_date <= :end_date)
            ORDER BY crash_date DESC
            LIMIT :limit
        """)

        result = db.execute(
            query,
            {
                "start_date": start_date,
                "end_date": end_date_normalized,
                "limit": limit,
            },
        )
        rows = result.fetchall()

        features = []
        for row in rows:
            if row.longitude is not None and row.latitude is not None:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [row.longitude, row.latitude],
                        },
                        "properties": {
                            "crash_record_id": row.crash_record_id,
                            "crash_date": row.crash_date.isoformat()
                            if row.crash_date
                            else None,
                            "injuries_total": row.injuries_total or 0,
                            "injuries_fatal": row.injuries_fatal or 0,
                            "injuries_incapacitating": row.injuries_incapacitating or 0,
                            "hit_and_run_i": row.hit_and_run_i == "Y",
                            "crash_type": row.crash_type,
                            "street_name": row.street_name,
                            "primary_contributory_cause": row.prim_contributory_cause,
                        },
                    }
                )

        return {
            "type": "FeatureCollection",
            "features": features,
        }

    except Exception as e:
        logger.error("Failed to get crashes GeoJSON", error=str(e))
        raise


@router.get("/crashes/by-hour")
async def get_crashes_by_hour(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Get crash counts grouped by hour of day.

    Useful for time-of-day analysis charts.
    End date is inclusive (includes all of that day).
    """
    try:
        # Normalize end_date to include the full day
        end_date_normalized = normalize_end_date(end_date)

        query = text("""
            SELECT
                EXTRACT(HOUR FROM crash_date)::int AS hour,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE crash_date IS NOT NULL
                AND (:start_date IS NULL OR crash_date >= :start_date)
                AND (:end_date IS NULL OR crash_date <= :end_date)
            GROUP BY EXTRACT(HOUR FROM crash_date)
            ORDER BY hour
        """)

        result = db.execute(
            query,
            {"start_date": start_date, "end_date": end_date_normalized},
        )
        rows = result.fetchall()

        return [
            {
                "hour": row.hour,
                "crashes": row.crashes,
                "injuries": int(row.injuries),
                "fatalities": int(row.fatalities),
            }
            for row in rows
        ]

    except Exception as e:
        logger.error("Failed to get crashes by hour", error=str(e))
        raise


@router.get("/crashes/by-cause")
async def get_crashes_by_cause(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=10, le=50),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Get crash counts grouped by primary contributory cause.

    Returns top N causes by crash count.
    End date is inclusive (includes all of that day).
    """
    try:
        # Normalize end_date to include the full day
        end_date_normalized = normalize_end_date(end_date)

        query = text("""
            SELECT
                prim_contributory_cause AS cause,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE prim_contributory_cause IS NOT NULL
                AND prim_contributory_cause != ''
                AND (:start_date IS NULL OR crash_date >= :start_date)
                AND (:end_date IS NULL OR crash_date <= :end_date)
            GROUP BY prim_contributory_cause
            ORDER BY crashes DESC
            LIMIT :limit
        """)

        result = db.execute(
            query,
            {"start_date": start_date, "end_date": end_date_normalized, "limit": limit},
        )
        rows = result.fetchall()

        return [
            {
                "cause": row.cause,
                "crashes": row.crashes,
                "injuries": int(row.injuries),
                "fatalities": int(row.fatalities),
            }
            for row in rows
        ]

    except Exception as e:
        logger.error("Failed to get crashes by cause", error=str(e))
        raise


# ==========================================
# Location Report Endpoints
# ==========================================


class LocationReportRequest(BaseModel):
    """Request body for location-based crash report."""

    # Either radius query or polygon query
    latitude: Optional[float] = Field(None, ge=-90, le=90, description="Center latitude for radius query")
    longitude: Optional[float] = Field(None, ge=-180, le=180, description="Center longitude for radius query")
    radius_feet: Optional[float] = Field(None, gt=0, le=26400, description="Radius in feet (max 5 miles)")

    # Or provide a polygon as GeoJSON coordinates
    polygon: Optional[List[List[float]]] = Field(
        None,
        description="Polygon coordinates as [[lng, lat], [lng, lat], ...]. Must have at least 3 points.",
    )

    # Or provide a place type and ID for predefined boundaries
    place_type: Optional[str] = Field(
        None,
        description="Place type (e.g., 'wards', 'community_areas', 'layer:123')",
    )
    place_id: Optional[str] = Field(
        None,
        description="Place ID within the type",
    )

    # Date filters
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class LocationReportExportRequest(LocationReportRequest):
    datasets: List[str] = Field(min_items=1)


class LocationReportStats(BaseModel):
    """Aggregate statistics for a location."""

    total_crashes: int
    total_injuries: int
    total_fatalities: int
    pedestrians_involved: int
    cyclists_involved: int
    hit_and_run_count: int
    incapacitating_injuries: int
    children_injured: int = Field(
        default=0,
        description="Count of people under 18 with any injury classification"
    )
    # Severity breakdown
    crashes_with_injuries: int
    crashes_with_fatalities: int
    # Cost estimates (2024$) - FHWA methodology
    estimated_economic_damages: float = Field(
        description="Economic damages based on KABCO person-injury + vehicle costs"
    )
    estimated_societal_costs: float = Field(
        description="Economic + QALY costs (comprehensive costs)"
    )
    # Vehicle count for transparency
    total_vehicles: int = Field(description="Total vehicles involved in crashes")
    # Data quality metric - unknown injury classifications excluded from costs
    unknown_injury_count: int = Field(
        default=0,
        description="Count of people with unknown/blank injury classification (excluded from costs)"
    )
    # Detailed cost breakdown
    cost_breakdown: Optional["CostBreakdown"] = Field(
        default=None,
        description="Detailed breakdown of costs by injury classification and vehicles"
    )


class InjuryClassificationCost(BaseModel):
    """Cost breakdown for a single injury classification."""

    classification: str = Field(description="KABCO classification name")
    classification_label: str = Field(description="Human-readable label (e.g., 'Fatal (K)')")
    count: int = Field(description="Number of people in this classification")
    unit_economic_cost: int = Field(description="Per-person economic cost in dollars")
    unit_qaly_cost: int = Field(description="Per-person QALY cost in dollars")
    subtotal_economic: int = Field(description="count * unit_economic_cost")
    subtotal_societal: int = Field(description="count * (unit_economic + unit_qaly)")


class VehicleCostBreakdown(BaseModel):
    """Cost breakdown for vehicles."""

    count: int = Field(description="Total vehicles involved")
    unit_economic_cost: int = Field(description="Per-vehicle economic cost")
    unit_qaly_cost: int = Field(description="Per-vehicle QALY cost")
    subtotal_economic: int = Field(description="count * unit_economic_cost")
    subtotal_societal: int = Field(description="count * (unit_economic + unit_qaly)")


class CostBreakdown(BaseModel):
    """Complete cost breakdown with per-classification details."""

    injury_costs: List[InjuryClassificationCost] = Field(
        description="Breakdown by injury classification"
    )
    vehicle_costs: VehicleCostBreakdown = Field(description="Vehicle cost breakdown")
    total_economic: int = Field(description="Grand total economic cost")
    total_societal: int = Field(description="Grand total societal cost")


class CrashCauseSummary(BaseModel):
    """Summary of crashes by cause."""

    cause: str
    crashes: int
    injuries: int
    fatalities: int
    percentage: float


class MonthlyTrendPoint(BaseModel):
    """Monthly trend data point for sparklines."""

    month: str
    crashes: int
    injuries: int
    fatalities: int


class LocationReportResponse(BaseModel):
    """Full location report response."""

    stats: LocationReportStats
    causes: List[CrashCauseSummary]
    monthly_trends: List[MonthlyTrendPoint]
    crashes_geojson: dict
    query_area_geojson: dict


# Native place type configuration for location report queries
# Maps type ID to (table name, pk column name)
_NATIVE_PLACE_TABLES = {
    "wards": ("wards", "ward"),
    "community_areas": ("community_areas", "area_numbe"),
    "house_districts": ("house_districts", "district"),
    "senate_districts": ("senate_districts", "district"),
    "police_beats": ("police_beats", "beat_num"),
}


def _get_place_geometry(
    db: Session, place_type: str, place_id: str
) -> tuple[str, dict] | None:
    """
    Look up the geometry for a place.

    Returns (name, geometry_dict) tuple or None if not found.
    """
    # Handle user-uploaded layers
    if place_type.startswith("layer:"):
        layer_id = int(place_type.split(":")[1])
        feature_id = int(place_id)

        result = db.execute(
            text(
                """
                SELECT
                    slf.properties,
                    ST_AsGeoJSON(slf.geometry)::json as geometry
                FROM spatial_layer_features slf
                WHERE slf.layer_id = :layer_id AND slf.id = :feature_id
                """
            ),
            {"layer_id": layer_id, "feature_id": feature_id},
        ).fetchone()

        if not result:
            return None

        props = result.properties or {}
        name = (
            props.get("name")
            or props.get("NAME")
            or props.get("title")
            or props.get("TITLE")
            or f"Feature {feature_id}"
        )

        return (name, result.geometry)

    # Handle native place types
    if place_type not in _NATIVE_PLACE_TABLES:
        return None

    table_name, pk_column = _NATIVE_PLACE_TABLES[place_type]

    result = db.execute(
        text(
            f"""
            SELECT
                ST_AsGeoJSON(geometry)::json as geometry
            FROM {table_name}
            WHERE {pk_column}::text = :place_id
            """
        ),
        {"place_id": place_id},
    ).fetchone()

    if not result:
        return None

    # Generate a display name based on place type
    if place_type == "wards":
        name = f"Ward {place_id}"
    elif place_type == "community_areas":
        # Query for the community name
        name_result = db.execute(
            text("SELECT community FROM community_areas WHERE area_numbe::text = :place_id"),
            {"place_id": place_id},
        ).fetchone()
        name = name_result.community if name_result else f"Community Area {place_id}"
    elif place_type == "house_districts":
        name = f"House District {place_id}"
    elif place_type == "senate_districts":
        name = f"Senate District {place_id}"
    elif place_type == "police_beats":
        name = f"Police Beat {place_id}"
    else:
        name = f"{place_type} {place_id}"

    return (name, result.geometry)


@router.post("/location-report", response_model=LocationReportResponse)
async def get_location_report(
    request: LocationReportRequest,
    db: Session = Depends(get_db),
) -> LocationReportResponse:
    """
    Generate a crash report for a specific location.

    Provide either:
    - latitude, longitude, and radius_feet for a circular area
    - polygon coordinates for a custom shape
    - place_type and place_id for a predefined boundary

    Returns comprehensive crash statistics, cause breakdown, trends, and GeoJSON data.
    """
    try:
        spatial_filter_template, spatial_params, query_area_geojson = _build_location_report_filters(
            request, db
        )
        spatial_filter = spatial_filter_template.format(geometry_column="geometry")
        spatial_filter_aliased = spatial_filter_template.format(geometry_column="c.geometry")

        date_filter = _build_date_filter(request, spatial_params, "crash_date")
        date_filter_aliased = _build_date_filter(request, spatial_params, "c.crash_date")

        # 1. Get aggregate statistics
        stats_query = text(f"""
            SELECT
                COUNT(*) AS total_crashes,
                COALESCE(SUM(injuries_total), 0) AS total_injuries,
                COALESCE(SUM(injuries_fatal), 0) AS total_fatalities,
                COALESCE(SUM(injuries_incapacitating), 0) AS incapacitating_injuries,
                COUNT(*) FILTER (WHERE injuries_total > 0) AS crashes_with_injuries,
                COUNT(*) FILTER (WHERE injuries_fatal > 0) AS crashes_with_fatalities,
                COUNT(*) FILTER (WHERE hit_and_run_i = 'Y') AS hit_and_run_count
            FROM crashes
            WHERE geometry IS NOT NULL
                AND {spatial_filter}
                {date_filter}
        """)

        stats_result = db.execute(stats_query, spatial_params).fetchone()

        # Get pedestrian, cyclist counts AND injury classification counts for cost calculation
        # Need to join with crashes that match our spatial filter
        # Use aliased versions since this is a JOIN query
        people_query = text(f"""
            SELECT
                COUNT(*) FILTER (WHERE person_type ILIKE '%PEDESTRIAN%') AS pedestrians,
                COUNT(*) FILTER (WHERE person_type ILIKE '%BICYCLE%' OR person_type ILIKE '%CYCLIST%' OR person_type ILIKE '%PEDALCYCLIST%') AS cyclists,
                COUNT(*) FILTER (WHERE injury_classification = 'FATAL') AS fatal_count,
                COUNT(*) FILTER (WHERE injury_classification = 'INCAPACITATING INJURY') AS incapacitating_count,
                COUNT(*) FILTER (WHERE injury_classification = 'NONINCAPACITATING INJURY') AS nonincapacitating_count,
                COUNT(*) FILTER (WHERE injury_classification = 'REPORTED, NOT EVIDENT') AS reported_not_evident_count,
                COUNT(*) FILTER (WHERE injury_classification = 'NO INDICATION OF INJURY') AS no_indication_count,
                COUNT(*) FILTER (WHERE injury_classification IS NULL OR injury_classification NOT IN (
                    'FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY',
                    'REPORTED, NOT EVIDENT', 'NO INDICATION OF INJURY'
                )) AS unknown_count,
                COUNT(*) FILTER (
                    WHERE cp.age >= 0 AND cp.age < 18
                    AND injury_classification IN (
                        'FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT'
                    )
                ) AS children_injured
            FROM crash_people cp
            INNER JOIN crashes c ON cp.crash_record_id = c.crash_record_id
            WHERE c.geometry IS NOT NULL
                AND {spatial_filter_aliased}
                {date_filter_aliased}
        """)

        people_result = db.execute(people_query, spatial_params).fetchone()

        # Get vehicle counts:
        # - total_vehicles: all vehicles for display
        # - pdo_vehicles: vehicles from Property Damage Only crashes (no injuries/fatalities)
        #   Only PDO vehicles are costed separately since injury costs already include vehicle damage
        vehicles_query = text(f"""
            SELECT
                COUNT(*) AS total_vehicle_count,
                COUNT(*) FILTER (
                    WHERE COALESCE(c.injuries_total, 0) = 0
                    AND COALESCE(c.injuries_fatal, 0) = 0
                ) AS pdo_vehicle_count
            FROM crash_vehicles cv
            INNER JOIN crashes c ON cv.crash_record_id = c.crash_record_id
            WHERE c.geometry IS NOT NULL
                AND {spatial_filter_aliased}
                {date_filter_aliased}
        """)

        vehicles_result = db.execute(vehicles_query, spatial_params).fetchone()
        total_vehicles = vehicles_result.total_vehicle_count or 0
        pdo_vehicles = vehicles_result.pdo_vehicle_count or 0

        # Calculate costs based on KABCO methodology
        # Economic damages = sum of economic costs for all people + vehicle costs
        # Societal costs = economic + QALY (comprehensive costs)
        injury_counts = {
            "FATAL": people_result.fatal_count or 0,
            "INCAPACITATING INJURY": people_result.incapacitating_count or 0,
            "NONINCAPACITATING INJURY": people_result.nonincapacitating_count or 0,
            "REPORTED, NOT EVIDENT": people_result.reported_not_evident_count or 0,
            "NO INDICATION OF INJURY": people_result.no_indication_count or 0,
        }

        # Calculate person-based costs
        person_economic_cost = sum(
            count * KABCO_COSTS[classification][0]  # economic component
            for classification, count in injury_counts.items()
        )
        person_qaly_cost = sum(
            count * KABCO_COSTS[classification][1]  # QALY component
            for classification, count in injury_counts.items()
        )

        # Add vehicle costs only for Property Damage Only crashes
        # (injury costs already include vehicle damage for crashes with injuries)
        vehicle_economic_cost = pdo_vehicles * VEHICLE_ECONOMIC_COST
        vehicle_qaly_cost = pdo_vehicles * VEHICLE_QALY_COST

        # Total costs
        estimated_economic_damages = person_economic_cost + vehicle_economic_cost
        estimated_societal_costs = estimated_economic_damages + person_qaly_cost + vehicle_qaly_cost

        # Build detailed cost breakdown for transparency
        injury_cost_breakdowns = []
        for classification, count in injury_counts.items():
            economic, qaly, _ = KABCO_COSTS[classification]
            injury_cost_breakdowns.append(
                InjuryClassificationCost(
                    classification=classification,
                    classification_label=KABCO_LABELS.get(classification, classification),
                    count=count,
                    unit_economic_cost=economic,
                    unit_qaly_cost=qaly,
                    subtotal_economic=count * economic,
                    subtotal_societal=count * (economic + qaly),
                )
            )

        vehicle_breakdown = VehicleCostBreakdown(
            count=pdo_vehicles,  # Only PDO vehicles are costed
            unit_economic_cost=VEHICLE_ECONOMIC_COST,
            unit_qaly_cost=VEHICLE_QALY_COST,
            subtotal_economic=vehicle_economic_cost,
            subtotal_societal=vehicle_economic_cost + vehicle_qaly_cost,
        )

        cost_breakdown = CostBreakdown(
            injury_costs=injury_cost_breakdowns,
            vehicle_costs=vehicle_breakdown,
            total_economic=estimated_economic_damages,
            total_societal=estimated_societal_costs,
        )

        stats = LocationReportStats(
            total_crashes=stats_result.total_crashes or 0,
            total_injuries=int(stats_result.total_injuries or 0),
            total_fatalities=int(stats_result.total_fatalities or 0),
            incapacitating_injuries=int(stats_result.incapacitating_injuries or 0),
            crashes_with_injuries=stats_result.crashes_with_injuries or 0,
            crashes_with_fatalities=stats_result.crashes_with_fatalities or 0,
            hit_and_run_count=stats_result.hit_and_run_count or 0,
            pedestrians_involved=people_result.pedestrians or 0,
            cyclists_involved=people_result.cyclists or 0,
            children_injured=people_result.children_injured or 0,
            estimated_economic_damages=estimated_economic_damages,
            estimated_societal_costs=estimated_societal_costs,
            total_vehicles=total_vehicles,
            unknown_injury_count=people_result.unknown_count or 0,
            cost_breakdown=cost_breakdown,
        )

        # 2. Get crash causes breakdown
        causes_query = text(f"""
            SELECT
                COALESCE(prim_contributory_cause, 'UNKNOWN') AS cause,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE geometry IS NOT NULL
                AND {spatial_filter}
                {date_filter}
            GROUP BY prim_contributory_cause
            ORDER BY crashes DESC
            LIMIT 15
        """)

        causes_result = db.execute(causes_query, spatial_params).fetchall()
        total_for_percentage = stats.total_crashes or 1

        causes = [
            CrashCauseSummary(
                cause=row.cause or "UNKNOWN",
                crashes=row.crashes,
                injuries=int(row.injuries),
                fatalities=int(row.fatalities),
                percentage=round((row.crashes / total_for_percentage) * 100, 1),
            )
            for row in causes_result
        ]

        # 3. Get monthly trends for sparklines
        trends_query = text(f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', crash_date), 'YYYY-MM') AS month,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE geometry IS NOT NULL
                AND crash_date >= NOW() - INTERVAL '12 months'
                AND {spatial_filter}
                {date_filter}
            GROUP BY DATE_TRUNC('month', crash_date)
            ORDER BY month
        """)

        trends_result = db.execute(trends_query, spatial_params).fetchall()

        monthly_trends = [
            MonthlyTrendPoint(
                month=row.month,
                crashes=row.crashes,
                injuries=int(row.injuries),
                fatalities=int(row.fatalities),
            )
            for row in trends_result
        ]

        # 4. Get crashes as GeoJSON for map display
        crashes_query = text(f"""
            SELECT
                crash_record_id,
                crash_date,
                injuries_total,
                injuries_fatal,
                injuries_incapacitating,
                hit_and_run_i,
                crash_type,
                street_name,
                prim_contributory_cause,
                ST_X(geometry) AS longitude,
                ST_Y(geometry) AS latitude
            FROM crashes
            WHERE geometry IS NOT NULL
                AND {spatial_filter}
                {date_filter}
            ORDER BY crash_date DESC
            LIMIT 5000
        """)

        crashes_result = db.execute(crashes_query, spatial_params).fetchall()

        features = []
        for row in crashes_result:
            if row.longitude is not None and row.latitude is not None:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row.longitude, row.latitude],
                    },
                    "properties": {
                        "crash_record_id": row.crash_record_id,
                        "crash_date": row.crash_date.isoformat() if row.crash_date else None,
                        "injuries_total": row.injuries_total or 0,
                        "injuries_fatal": row.injuries_fatal or 0,
                        "injuries_incapacitating": row.injuries_incapacitating or 0,
                        "hit_and_run_i": row.hit_and_run_i == "Y",
                        "crash_type": row.crash_type,
                        "street_name": row.street_name,
                        "primary_contributory_cause": row.prim_contributory_cause,
                    },
                })

        crashes_geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        return LocationReportResponse(
            stats=stats,
            causes=causes,
            monthly_trends=monthly_trends,
            crashes_geojson=crashes_geojson,
            query_area_geojson=query_area_geojson,
        )

    except Exception as e:
        logger.error("Failed to generate location report", error=str(e))
        raise


@router.post("/location-report/export")
async def export_location_report(
    request: LocationReportExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export location report data as CSV or ZIP using the same spatial filters."""
    try:
        allowed_datasets = {"crashes", "people", "vehicles", "vision_zero"}
        invalid_datasets = [dataset for dataset in request.datasets if dataset not in allowed_datasets]
        if invalid_datasets:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid datasets: {', '.join(invalid_datasets)}",
            )

        spatial_filter_template, spatial_params, _ = _build_location_report_filters(
            request, db
        )

        def spatial_filter_for(geometry_column: str) -> str:
            return spatial_filter_template.format(geometry_column=geometry_column)

        crashes_select = _build_select_list(Crash, "c", geometry_column="geometry")
        people_select = _build_select_list(CrashPerson, "cp")
        vehicles_select = _build_select_list(CrashVehicle, "cv")
        vision_zero_select = _build_select_list(
            VisionZeroFatality, "vz", geometry_column="geometry"
        )

        dataset_queries = {
            "crashes": text(f"""
                SELECT {crashes_select}
                FROM crashes c
                WHERE c.geometry IS NOT NULL
                    AND {spatial_filter_for("c.geometry")}
                    {_build_date_filter(request, spatial_params, "c.crash_date")}
            """),
            "people": text(f"""
                SELECT {people_select}
                FROM crash_people cp
                INNER JOIN crashes c ON cp.crash_record_id = c.crash_record_id
                WHERE c.geometry IS NOT NULL
                    AND {spatial_filter_for("c.geometry")}
                    {_build_date_filter(request, spatial_params, "c.crash_date")}
            """),
            "vehicles": text(f"""
                SELECT {vehicles_select}
                FROM crash_vehicles cv
                INNER JOIN crashes c ON cv.crash_record_id = c.crash_record_id
                WHERE c.geometry IS NOT NULL
                    AND {spatial_filter_for("c.geometry")}
                    {_build_date_filter(request, spatial_params, "c.crash_date")}
            """),
            "vision_zero": text(f"""
                SELECT {vision_zero_select}
                FROM vision_zero_fatalities vz
                WHERE vz.geometry IS NOT NULL
                    AND {spatial_filter_for("vz.geometry")}
                    {_build_date_filter(request, spatial_params, "vz.crash_date")}
            """),
        }

        if len(request.datasets) == 1:
            dataset = request.datasets[0]
            result = db.execute(dataset_queries[dataset], spatial_params)
            filename = f"location-report-{dataset}.csv"
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return StreamingResponse(
                _stream_csv(result),
                media_type="text/csv",
                headers=headers,
            )

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_file.close()
        with zipfile.ZipFile(temp_file.name, "w", zipfile.ZIP_DEFLATED) as zipf:
            for dataset in request.datasets:
                result = db.execute(dataset_queries[dataset], spatial_params)
                csv_name = f"location-report-{dataset}.csv"
                with zipf.open(csv_name, "w") as buffer:
                    text_buffer = io.TextIOWrapper(buffer, encoding="utf-8", newline="")
                    writer = csv.writer(text_buffer)
                    writer.writerow(result.keys())
                    for row in result:
                        writer.writerow(row)
                    text_buffer.flush()

        background_tasks.add_task(os.unlink, temp_file.name)
        headers = {"Content-Disposition": 'attachment; filename="location-report-export.zip"'}
        return StreamingResponse(
            open(temp_file.name, "rb"),
            media_type="application/zip",
            headers=headers,
        )
    except Exception as e:
        logger.error("Failed to export location report", error=str(e))
        raise


# ==========================================
# Ward Scorecard Endpoints
# ==========================================


class WardStats(BaseModel):
    """Statistics for a single ward or citywide."""

    total_crashes: int
    fatalities: int
    serious_injuries: int
    ksi: int  # Killed or Seriously Injured
    vru_injuries: int  # Vulnerable Road User injuries
    children_injured: int
    hit_and_run: int
    economic_cost: float
    societal_cost: float


class WardRanking(BaseModel):
    """Ward with stats for ranking table."""

    ward: int
    ward_name: str
    alderman: Optional[str] = None
    total_crashes: int
    fatalities: int
    serious_injuries: int
    ksi: int
    vru_injuries: int
    children_injured: int
    economic_cost: float
    societal_cost: float


class WardScorecardCitywideResponse(BaseModel):
    """Response for citywide ward scorecard endpoint."""

    year: int
    citywide_stats: WardStats
    ward_rankings: List[WardRanking]
    wards_geojson: dict  # GeoJSON FeatureCollection with ward boundaries


class WardTrendData(BaseModel):
    """Trend data for a single entity (citywide or ward)."""

    ksi: List[int]
    fatalities: List[int]
    serious_injuries: List[int]


class WardTrendResponse(BaseModel):
    """Response for citywide trends endpoint."""

    years: List[int]
    citywide: WardTrendData
    ward: Optional[dict] = None  # Includes ward number + trend data


class MonthlySeasonalityData(BaseModel):
    """Monthly seasonality data."""

    months: List[str]
    selected_year: dict
    five_year_avg: dict


class WardDetailTrendResponse(BaseModel):
    """Response for ward detail trends endpoint."""

    ward: int
    yearly_trends: dict
    monthly_seasonality: MonthlySeasonalityData


class WardDetailResponse(BaseModel):
    """Response for ward detail endpoint."""

    year: int
    ward: int
    ward_name: str
    alderman: Optional[str] = None
    stats: WardStats
    citywide_comparison: WardStats
    cost_breakdown: CostBreakdown
    crashes_geojson: dict
    ward_boundary_geojson: dict


def _get_ward_layer_id(db: Session) -> int:
    """Get the spatial layer ID for wards."""
    result = db.execute(
        text("SELECT id FROM spatial_layers WHERE slug = 'wards' LIMIT 1")
    ).fetchone()
    if not result:
        raise HTTPException(status_code=500, detail="Wards spatial layer not found")
    return result.id


def _calculate_ward_costs(
    fatalities: int,
    serious_injuries: int,
    nonincap_injuries: int,
    possible_injuries: int,
    no_indication: int,
    pdo_vehicles: int,
) -> tuple[float, float]:
    """Calculate economic and societal costs for ward stats."""
    # Person-based costs
    person_economic = (
        fatalities * KABCO_COSTS["FATAL"][0]
        + serious_injuries * KABCO_COSTS["INCAPACITATING INJURY"][0]
        + nonincap_injuries * KABCO_COSTS["NONINCAPACITATING INJURY"][0]
        + possible_injuries * KABCO_COSTS["REPORTED, NOT EVIDENT"][0]
        + no_indication * KABCO_COSTS["NO INDICATION OF INJURY"][0]
    )
    person_qaly = (
        fatalities * KABCO_COSTS["FATAL"][1]
        + serious_injuries * KABCO_COSTS["INCAPACITATING INJURY"][1]
        + nonincap_injuries * KABCO_COSTS["NONINCAPACITATING INJURY"][1]
        + possible_injuries * KABCO_COSTS["REPORTED, NOT EVIDENT"][1]
        + no_indication * KABCO_COSTS["NO INDICATION OF INJURY"][1]
    )

    # Vehicle costs (PDO only)
    vehicle_economic = pdo_vehicles * VEHICLE_ECONOMIC_COST
    vehicle_qaly = pdo_vehicles * VEHICLE_QALY_COST

    economic_cost = person_economic + vehicle_economic
    societal_cost = economic_cost + person_qaly + vehicle_qaly

    return economic_cost, societal_cost


@router.get("/ward-scorecard/citywide", response_model=WardScorecardCitywideResponse)
async def get_ward_scorecard_citywide(
    year: int = Query(..., ge=2018, le=2026, description="Year to query"),
    db: Session = Depends(get_db),
) -> WardScorecardCitywideResponse:
    """
    Get citywide aggregated stats and all ward rankings for a given year.

    Returns ward statistics aggregated by ward with costs and geometry for choropleth.
    """
    from datetime import date

    try:
        ward_layer_id = _get_ward_layer_id(db)

        # Use date range for better index utilization
        start_date = date(year, 1, 1)
        end_date = date(year + 1, 1, 1)

        # Query 1: Crash-level aggregation (fast with ward index)
        crash_stats_query = text("""
            SELECT
                c.ward,
                COUNT(DISTINCT c.crash_record_id) as total_crashes,
                COALESCE(SUM(c.injuries_fatal), 0) as fatalities,
                COALESCE(SUM(c.injuries_incapacitating), 0) as serious_injuries,
                COUNT(DISTINCT c.crash_record_id) FILTER (WHERE c.hit_and_run_i = 'Y') as hit_and_run,
                COUNT(DISTINCT c.crash_record_id) FILTER (
                    WHERE COALESCE(c.injuries_total, 0) = 0
                    AND COALESCE(c.injuries_fatal, 0) = 0
                ) as pdo_crashes
            FROM crashes c
            WHERE c.ward IS NOT NULL
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
            GROUP BY c.ward
            ORDER BY c.ward
        """)

        crash_results = db.execute(
            crash_stats_query,
            {"start_date": start_date, "end_date": end_date},
        ).fetchall()

        # Query 2: Person-level aggregation (VRU, children, injury counts)
        people_stats_query = text("""
            SELECT
                c.ward,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'FATAL') as fatal_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'INCAPACITATING INJURY') as incap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NONINCAPACITATING INJURY') as nonincap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'REPORTED, NOT EVIDENT') as possible_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NO INDICATION OF INJURY') as no_injury_people,
                COUNT(*) FILTER (
                    WHERE cp.person_type IN ('PEDESTRIAN', 'BICYCLE', 'PEDALCYCLIST')
                    AND cp.injury_classification IN (
                        'FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT'
                    )
                ) as vru_injuries,
                COUNT(*) FILTER (
                    WHERE cp.age >= 0 AND cp.age < 18
                    AND cp.injury_classification IN (
                        'FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT'
                    )
                ) as children_injured
            FROM crashes c
            JOIN crash_people cp ON c.crash_record_id = cp.crash_record_id
            WHERE c.ward IS NOT NULL
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
            GROUP BY c.ward
        """)

        people_results = db.execute(
            people_stats_query,
            {"start_date": start_date, "end_date": end_date},
        ).fetchall()

        # Merge results in Python
        people_by_ward = {r.ward: r for r in people_results}

        # Build combined results
        ward_results = []
        for crash_row in crash_results:
            people_row = people_by_ward.get(crash_row.ward)
            ward_results.append({
                "ward": crash_row.ward,
                "total_crashes": crash_row.total_crashes,
                "fatalities": crash_row.fatalities,
                "serious_injuries": crash_row.serious_injuries,
                "hit_and_run": crash_row.hit_and_run,
                "fatal_people": people_row.fatal_people if people_row else 0,
                "incap_people": people_row.incap_people if people_row else 0,
                "nonincap_people": people_row.nonincap_people if people_row else 0,
                "possible_people": people_row.possible_people if people_row else 0,
                "no_injury_people": people_row.no_injury_people if people_row else 0,
                "vru_injuries": people_row.vru_injuries if people_row else 0,
                "children_injured": people_row.children_injured if people_row else 0,
                "pdo_vehicles": crash_row.pdo_crashes * 2,  # Estimate 2 vehicles per PDO crash
            })

        # Build ward rankings and calculate citywide totals
        ward_rankings = []
        citywide_totals = {
            "total_crashes": 0,
            "fatalities": 0,
            "serious_injuries": 0,
            "ksi": 0,
            "vru_injuries": 0,
            "children_injured": 0,
            "hit_and_run": 0,
            "economic_cost": 0.0,
            "societal_cost": 0.0,
        }

        for row in ward_results:
            ksi = row["fatalities"] + row["serious_injuries"]
            economic_cost, societal_cost = _calculate_ward_costs(
                row["fatal_people"],
                row["incap_people"],
                row["nonincap_people"],
                row["possible_people"],
                row["no_injury_people"],
                row["pdo_vehicles"],
            )

            ward_rankings.append(
                WardRanking(
                    ward=row["ward"],
                    ward_name=f"Ward {row['ward']}",
                    alderman=None,  # Could add alderman lookup if needed
                    total_crashes=row["total_crashes"],
                    fatalities=row["fatalities"],
                    serious_injuries=row["serious_injuries"],
                    ksi=ksi,
                    vru_injuries=row["vru_injuries"],
                    children_injured=row["children_injured"],
                    economic_cost=economic_cost,
                    societal_cost=societal_cost,
                )
            )

            # Accumulate citywide totals
            citywide_totals["total_crashes"] += row["total_crashes"]
            citywide_totals["fatalities"] += row["fatalities"]
            citywide_totals["serious_injuries"] += row["serious_injuries"]
            citywide_totals["ksi"] += ksi
            citywide_totals["vru_injuries"] += row["vru_injuries"]
            citywide_totals["children_injured"] += row["children_injured"]
            citywide_totals["hit_and_run"] += row["hit_and_run"]
            citywide_totals["economic_cost"] += economic_cost
            citywide_totals["societal_cost"] += societal_cost

        citywide_stats = WardStats(**citywide_totals)

        # Get ward geometries for choropleth map
        geojson_query = text("""
            SELECT
                FLOOR((f.properties->>'ward')::numeric)::int as ward,
                ST_AsGeoJSON(f.geometry)::json as geometry
            FROM spatial_layer_features f
            WHERE f.layer_id = :ward_layer_id
            ORDER BY ward
        """)

        geom_results = db.execute(
            geojson_query, {"ward_layer_id": ward_layer_id}
        ).fetchall()

        # Build GeoJSON with KSI values for coloring
        ward_ksi_map = {w.ward: w.ksi for w in ward_rankings}
        features = []
        for row in geom_results:
            features.append({
                "type": "Feature",
                "geometry": row.geometry,
                "properties": {
                    "ward": row.ward,
                    "ward_name": f"Ward {row.ward}",
                    "ksi": ward_ksi_map.get(row.ward, 0),
                },
            })

        wards_geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        return WardScorecardCitywideResponse(
            year=year,
            citywide_stats=citywide_stats,
            ward_rankings=ward_rankings,
            wards_geojson=wards_geojson,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get ward scorecard citywide", error=str(e))
        raise


@router.get("/ward-scorecard/citywide/trends", response_model=WardTrendResponse)
async def get_ward_scorecard_citywide_trends(
    ward: Optional[int] = Query(None, ge=1, le=50, description="Ward to compare"),
    db: Session = Depends(get_db),
) -> WardTrendResponse:
    """
    Get yearly trend data for citywide stats, optionally with a ward for comparison.
    """
    try:
        ward_layer_id = _get_ward_layer_id(db)

        # Citywide yearly trends
        citywide_query = text("""
            SELECT
                EXTRACT(YEAR FROM crash_date)::int as year,
                COALESCE(SUM(injuries_fatal), 0) as fatalities,
                COALESCE(SUM(injuries_incapacitating), 0) as serious_injuries
            FROM crashes
            WHERE crash_date IS NOT NULL
                AND EXTRACT(YEAR FROM crash_date) >= 2018
                AND geometry IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM crash_date)
            ORDER BY year
        """)

        citywide_results = db.execute(citywide_query).fetchall()

        years = [r.year for r in citywide_results]
        citywide = WardTrendData(
            ksi=[r.fatalities + r.serious_injuries for r in citywide_results],
            fatalities=[r.fatalities for r in citywide_results],
            serious_injuries=[r.serious_injuries for r in citywide_results],
        )

        ward_data = None
        if ward:
            # Use pre-computed ward column for fast filtering
            ward_query = text("""
                SELECT
                    EXTRACT(YEAR FROM c.crash_date)::int as year,
                    COALESCE(SUM(c.injuries_fatal), 0) as fatalities,
                    COALESCE(SUM(c.injuries_incapacitating), 0) as serious_injuries
                FROM crashes c
                WHERE c.ward = :ward
                    AND c.crash_date IS NOT NULL
                    AND EXTRACT(YEAR FROM c.crash_date) >= 2018
                GROUP BY EXTRACT(YEAR FROM c.crash_date)
                ORDER BY year
            """)

            ward_results = db.execute(
                ward_query, {"ward_layer_id": ward_layer_id, "ward": ward}
            ).fetchall()

            # Build ward data aligned with years
            ward_year_map = {r.year: r for r in ward_results}
            ward_data = {
                "ward": ward,
                "ksi": [
                    (ward_year_map[y].fatalities + ward_year_map[y].serious_injuries)
                    if y in ward_year_map else 0
                    for y in years
                ],
                "fatalities": [
                    ward_year_map[y].fatalities if y in ward_year_map else 0
                    for y in years
                ],
                "serious_injuries": [
                    ward_year_map[y].serious_injuries if y in ward_year_map else 0
                    for y in years
                ],
            }

        return WardTrendResponse(
            years=years,
            citywide=citywide,
            ward=ward_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get ward scorecard citywide trends", error=str(e))
        raise


@router.get("/ward-scorecard/ward/{ward}", response_model=WardDetailResponse)
async def get_ward_detail(
    ward: int = Path(..., ge=1, le=50, description="Ward number"),
    year: int = Query(..., ge=2018, le=2026, description="Year to query"),
    db: Session = Depends(get_db),
) -> WardDetailResponse:
    """
    Get detailed stats for a specific ward including crash points and cost breakdown.
    """
    from datetime import date as date_type

    try:
        ward_layer_id = _get_ward_layer_id(db)

        # Use date range for better index utilization
        start_date = date_type(year, 1, 1)
        end_date = date_type(year + 1, 1, 1)

        # Query 1: Ward crash-level stats (fast)
        ward_crash_query = text("""
            SELECT
                COUNT(DISTINCT c.crash_record_id) as total_crashes,
                COALESCE(SUM(c.injuries_fatal), 0) as fatalities,
                COALESCE(SUM(c.injuries_incapacitating), 0) as serious_injuries,
                COUNT(DISTINCT c.crash_record_id) FILTER (WHERE c.hit_and_run_i = 'Y') as hit_and_run,
                COUNT(DISTINCT c.crash_record_id) FILTER (
                    WHERE COALESCE(c.injuries_total, 0) = 0 AND COALESCE(c.injuries_fatal, 0) = 0
                ) as pdo_crashes
            FROM crashes c
            WHERE c.ward = :ward
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
        """)

        ward_crash_result = db.execute(
            ward_crash_query,
            {"ward": ward, "start_date": start_date, "end_date": end_date},
        ).fetchone()

        # Query 2: Ward person-level stats
        ward_people_query = text("""
            SELECT
                COUNT(*) FILTER (WHERE cp.injury_classification = 'FATAL') as fatal_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'INCAPACITATING INJURY') as incap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NONINCAPACITATING INJURY') as nonincap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'REPORTED, NOT EVIDENT') as possible_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NO INDICATION OF INJURY') as no_injury_people,
                COUNT(*) FILTER (
                    WHERE cp.person_type IN ('PEDESTRIAN', 'BICYCLE', 'PEDALCYCLIST')
                    AND cp.injury_classification IN ('FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT')
                ) as vru_injuries,
                COUNT(*) FILTER (
                    WHERE cp.age >= 0 AND cp.age < 18
                    AND cp.injury_classification IN ('FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT')
                ) as children_injured
            FROM crashes c
            JOIN crash_people cp ON c.crash_record_id = cp.crash_record_id
            WHERE c.ward = :ward
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
        """)

        ward_people_result = db.execute(
            ward_people_query,
            {"ward": ward, "start_date": start_date, "end_date": end_date},
        ).fetchone()

        # Combine results
        stats_result = type('obj', (object,), {
            'total_crashes': ward_crash_result.total_crashes,
            'fatalities': ward_crash_result.fatalities,
            'serious_injuries': ward_crash_result.serious_injuries,
            'hit_and_run': ward_crash_result.hit_and_run,
            'fatal_people': ward_people_result.fatal_people,
            'incap_people': ward_people_result.incap_people,
            'nonincap_people': ward_people_result.nonincap_people,
            'possible_people': ward_people_result.possible_people,
            'no_injury_people': ward_people_result.no_injury_people,
            'vru_injuries': ward_people_result.vru_injuries,
            'children_injured': ward_people_result.children_injured,
            'pdo_vehicles': ward_crash_result.pdo_crashes * 2,  # Estimate 2 vehicles per PDO crash
        })()

        ksi = stats_result.fatalities + stats_result.serious_injuries
        economic_cost, societal_cost = _calculate_ward_costs(
            stats_result.fatal_people,
            stats_result.incap_people,
            stats_result.nonincap_people,
            stats_result.possible_people,
            stats_result.no_injury_people,
            stats_result.pdo_vehicles,
        )

        ward_stats = WardStats(
            total_crashes=stats_result.total_crashes,
            fatalities=stats_result.fatalities,
            serious_injuries=stats_result.serious_injuries,
            ksi=ksi,
            vru_injuries=stats_result.vru_injuries,
            children_injured=stats_result.children_injured,
            hit_and_run=stats_result.hit_and_run,
            economic_cost=economic_cost,
            societal_cost=societal_cost,
        )

        # Get citywide stats for comparison - use date range and split queries for speed
        citywide_crash_query = text("""
            SELECT
                COUNT(DISTINCT c.crash_record_id) as total_crashes,
                COALESCE(SUM(c.injuries_fatal), 0) as fatalities,
                COALESCE(SUM(c.injuries_incapacitating), 0) as serious_injuries,
                COUNT(DISTINCT c.crash_record_id) FILTER (WHERE c.hit_and_run_i = 'Y') as hit_and_run,
                COUNT(DISTINCT c.crash_record_id) FILTER (
                    WHERE COALESCE(c.injuries_total, 0) = 0 AND COALESCE(c.injuries_fatal, 0) = 0
                ) as pdo_crashes
            FROM crashes c
            WHERE c.ward IS NOT NULL
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
        """)

        citywide_crash_result = db.execute(
            citywide_crash_query,
            {"start_date": start_date, "end_date": end_date},
        ).fetchone()

        citywide_people_query = text("""
            SELECT
                COUNT(*) FILTER (WHERE cp.injury_classification = 'FATAL') as fatal_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'INCAPACITATING INJURY') as incap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NONINCAPACITATING INJURY') as nonincap_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'REPORTED, NOT EVIDENT') as possible_people,
                COUNT(*) FILTER (WHERE cp.injury_classification = 'NO INDICATION OF INJURY') as no_injury_people,
                COUNT(*) FILTER (
                    WHERE cp.person_type IN ('PEDESTRIAN', 'BICYCLE', 'PEDALCYCLIST')
                    AND cp.injury_classification IN ('FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT')
                ) as vru_injuries,
                COUNT(*) FILTER (
                    WHERE cp.age >= 0 AND cp.age < 18
                    AND cp.injury_classification IN ('FATAL', 'INCAPACITATING INJURY', 'NONINCAPACITATING INJURY', 'REPORTED, NOT EVIDENT')
                ) as children_injured
            FROM crashes c
            JOIN crash_people cp ON c.crash_record_id = cp.crash_record_id
            WHERE c.ward IS NOT NULL
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
        """)

        citywide_people_result = db.execute(
            citywide_people_query,
            {"start_date": start_date, "end_date": end_date},
        ).fetchone()

        # Combine citywide results
        citywide_result = type('obj', (object,), {
            'total_crashes': citywide_crash_result.total_crashes,
            'fatalities': citywide_crash_result.fatalities,
            'serious_injuries': citywide_crash_result.serious_injuries,
            'hit_and_run': citywide_crash_result.hit_and_run,
            'fatal_people': citywide_people_result.fatal_people,
            'incap_people': citywide_people_result.incap_people,
            'nonincap_people': citywide_people_result.nonincap_people,
            'possible_people': citywide_people_result.possible_people,
            'no_injury_people': citywide_people_result.no_injury_people,
            'vru_injuries': citywide_people_result.vru_injuries,
            'children_injured': citywide_people_result.children_injured,
            'pdo_vehicles': citywide_crash_result.pdo_crashes * 2,  # Estimate 2 vehicles per PDO crash
        })()

        citywide_ksi = citywide_result.fatalities + citywide_result.serious_injuries
        citywide_economic, citywide_societal = _calculate_ward_costs(
            citywide_result.fatal_people,
            citywide_result.incap_people,
            citywide_result.nonincap_people,
            citywide_result.possible_people,
            citywide_result.no_injury_people,
            citywide_result.pdo_vehicles,
        )

        citywide_comparison = WardStats(
            total_crashes=citywide_result.total_crashes,
            fatalities=citywide_result.fatalities,
            serious_injuries=citywide_result.serious_injuries,
            ksi=citywide_ksi,
            vru_injuries=citywide_result.vru_injuries,
            children_injured=citywide_result.children_injured,
            hit_and_run=citywide_result.hit_and_run,
            economic_cost=citywide_economic,
            societal_cost=citywide_societal,
        )

        # Build cost breakdown
        injury_cost_breakdowns = [
            InjuryClassificationCost(
                classification="FATAL",
                classification_label=KABCO_LABELS["FATAL"],
                count=stats_result.fatal_people,
                unit_economic_cost=KABCO_COSTS["FATAL"][0],
                unit_qaly_cost=KABCO_COSTS["FATAL"][1],
                subtotal_economic=stats_result.fatal_people * KABCO_COSTS["FATAL"][0],
                subtotal_societal=stats_result.fatal_people * (KABCO_COSTS["FATAL"][0] + KABCO_COSTS["FATAL"][1]),
            ),
            InjuryClassificationCost(
                classification="INCAPACITATING INJURY",
                classification_label=KABCO_LABELS["INCAPACITATING INJURY"],
                count=stats_result.incap_people,
                unit_economic_cost=KABCO_COSTS["INCAPACITATING INJURY"][0],
                unit_qaly_cost=KABCO_COSTS["INCAPACITATING INJURY"][1],
                subtotal_economic=stats_result.incap_people * KABCO_COSTS["INCAPACITATING INJURY"][0],
                subtotal_societal=stats_result.incap_people * (KABCO_COSTS["INCAPACITATING INJURY"][0] + KABCO_COSTS["INCAPACITATING INJURY"][1]),
            ),
            InjuryClassificationCost(
                classification="NONINCAPACITATING INJURY",
                classification_label=KABCO_LABELS["NONINCAPACITATING INJURY"],
                count=stats_result.nonincap_people,
                unit_economic_cost=KABCO_COSTS["NONINCAPACITATING INJURY"][0],
                unit_qaly_cost=KABCO_COSTS["NONINCAPACITATING INJURY"][1],
                subtotal_economic=stats_result.nonincap_people * KABCO_COSTS["NONINCAPACITATING INJURY"][0],
                subtotal_societal=stats_result.nonincap_people * (KABCO_COSTS["NONINCAPACITATING INJURY"][0] + KABCO_COSTS["NONINCAPACITATING INJURY"][1]),
            ),
            InjuryClassificationCost(
                classification="REPORTED, NOT EVIDENT",
                classification_label=KABCO_LABELS["REPORTED, NOT EVIDENT"],
                count=stats_result.possible_people,
                unit_economic_cost=KABCO_COSTS["REPORTED, NOT EVIDENT"][0],
                unit_qaly_cost=KABCO_COSTS["REPORTED, NOT EVIDENT"][1],
                subtotal_economic=stats_result.possible_people * KABCO_COSTS["REPORTED, NOT EVIDENT"][0],
                subtotal_societal=stats_result.possible_people * (KABCO_COSTS["REPORTED, NOT EVIDENT"][0] + KABCO_COSTS["REPORTED, NOT EVIDENT"][1]),
            ),
            InjuryClassificationCost(
                classification="NO INDICATION OF INJURY",
                classification_label=KABCO_LABELS["NO INDICATION OF INJURY"],
                count=stats_result.no_injury_people,
                unit_economic_cost=KABCO_COSTS["NO INDICATION OF INJURY"][0],
                unit_qaly_cost=KABCO_COSTS["NO INDICATION OF INJURY"][1],
                subtotal_economic=0,
                subtotal_societal=0,
            ),
        ]

        vehicle_breakdown = VehicleCostBreakdown(
            count=stats_result.pdo_vehicles,
            unit_economic_cost=VEHICLE_ECONOMIC_COST,
            unit_qaly_cost=VEHICLE_QALY_COST,
            subtotal_economic=stats_result.pdo_vehicles * VEHICLE_ECONOMIC_COST,
            subtotal_societal=stats_result.pdo_vehicles * (VEHICLE_ECONOMIC_COST + VEHICLE_QALY_COST),
        )

        cost_breakdown = CostBreakdown(
            injury_costs=injury_cost_breakdowns,
            vehicle_costs=vehicle_breakdown,
            total_economic=int(economic_cost),
            total_societal=int(societal_cost),
        )

        # Get crash points for map - use ward column and date range for speed
        crashes_query = text("""
            SELECT
                c.crash_record_id,
                c.crash_date,
                c.injuries_fatal,
                c.injuries_incapacitating,
                c.most_severe_injury,
                c.longitude,
                c.latitude
            FROM crashes c
            WHERE c.ward = :ward
                AND c.crash_date >= :start_date
                AND c.crash_date < :end_date
                AND c.latitude IS NOT NULL
                AND c.longitude IS NOT NULL
            ORDER BY c.crash_date DESC
            LIMIT 5000
        """)

        crashes_results = db.execute(
            crashes_query,
            {"ward": ward, "start_date": start_date, "end_date": end_date},
        ).fetchall()

        crash_features = []
        for row in crashes_results:
            crash_features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row.longitude, row.latitude],
                },
                "properties": {
                    "crash_record_id": row.crash_record_id,
                    "crash_date": row.crash_date.isoformat() if row.crash_date else None,
                    "injuries_fatal": row.injuries_fatal or 0,
                    "injuries_incapacitating": row.injuries_incapacitating or 0,
                    "most_severe_injury": row.most_severe_injury,
                },
            })

        crashes_geojson = {
            "type": "FeatureCollection",
            "features": crash_features,
        }

        # Get ward boundary
        boundary_query = text("""
            SELECT ST_AsGeoJSON(f.geometry)::json as geometry
            FROM spatial_layer_features f
            WHERE f.layer_id = :ward_layer_id
                AND FLOOR((f.properties->>'ward')::numeric)::int = :ward
            LIMIT 1
        """)

        boundary_result = db.execute(
            boundary_query,
            {"ward_layer_id": ward_layer_id, "ward": ward},
        ).fetchone()

        ward_boundary_geojson = {
            "type": "Feature",
            "geometry": boundary_result.geometry if boundary_result else None,
            "properties": {"ward": ward, "ward_name": f"Ward {ward}"},
        }

        return WardDetailResponse(
            year=year,
            ward=ward,
            ward_name=f"Ward {ward}",
            alderman=None,
            stats=ward_stats,
            citywide_comparison=citywide_comparison,
            cost_breakdown=cost_breakdown,
            crashes_geojson=crashes_geojson,
            ward_boundary_geojson=ward_boundary_geojson,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get ward detail", error=str(e))
        raise


@router.get("/ward-scorecard/ward/{ward}/trends", response_model=WardDetailTrendResponse)
async def get_ward_detail_trends(
    ward: int = Path(..., ge=1, le=50, description="Ward number"),
    year: int = Query(..., ge=2018, le=2026, description="Selected year for monthly"),
    db: Session = Depends(get_db),
) -> WardDetailTrendResponse:
    """
    Get yearly and monthly trend data for a specific ward.
    """
    try:
        ward_layer_id = _get_ward_layer_id(db)

        # Yearly trends (using pre-computed ward column)
        yearly_query = text("""
            SELECT
                EXTRACT(YEAR FROM c.crash_date)::int as year,
                COUNT(DISTINCT c.crash_record_id) as total_crashes,
                COALESCE(SUM(c.injuries_fatal), 0) as fatalities,
                COALESCE(SUM(c.injuries_incapacitating), 0) as serious_injuries
            FROM crashes c
            WHERE c.ward = :ward
                AND c.crash_date IS NOT NULL
                AND EXTRACT(YEAR FROM c.crash_date) >= 2018
            GROUP BY EXTRACT(YEAR FROM c.crash_date)
            ORDER BY year
        """)

        yearly_results = db.execute(
            yearly_query, {"ward_layer_id": ward_layer_id, "ward": ward}
        ).fetchall()

        yearly_trends = {
            "years": [r.year for r in yearly_results],
            "ksi": [r.fatalities + r.serious_injuries for r in yearly_results],
            "fatalities": [r.fatalities for r in yearly_results],
            "serious_injuries": [r.serious_injuries for r in yearly_results],
            "total_crashes": [r.total_crashes for r in yearly_results],
        }

        # Monthly seasonality for selected year + 5-year average (using pre-computed ward column)
        monthly_query = text("""
            SELECT
                EXTRACT(MONTH FROM c.crash_date)::int as month,
                EXTRACT(YEAR FROM c.crash_date)::int as year,
                COALESCE(SUM(c.injuries_fatal), 0) + COALESCE(SUM(c.injuries_incapacitating), 0) as ksi
            FROM crashes c
            WHERE c.ward = :ward
                AND EXTRACT(YEAR FROM c.crash_date) BETWEEN :start_year AND :year
            GROUP BY EXTRACT(MONTH FROM c.crash_date), EXTRACT(YEAR FROM c.crash_date)
            ORDER BY month, year
        """)

        start_year = year - 5
        monthly_results = db.execute(
            monthly_query,
            {"ward_layer_id": ward_layer_id, "ward": ward, "year": year, "start_year": start_year},
        ).fetchall()

        # Organize monthly data
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        selected_year_ksi = [0] * 12
        five_year_sums = [0] * 12
        five_year_counts = [0] * 12

        for row in monthly_results:
            month_idx = row.month - 1
            if row.year == year:
                selected_year_ksi[month_idx] = row.ksi
            elif row.year < year:
                five_year_sums[month_idx] += row.ksi
                five_year_counts[month_idx] += 1

        five_year_avg_ksi = [
            round(five_year_sums[i] / five_year_counts[i], 1) if five_year_counts[i] > 0 else 0
            for i in range(12)
        ]

        monthly_seasonality = MonthlySeasonalityData(
            months=months,
            selected_year={"year": year, "ksi": selected_year_ksi},
            five_year_avg={"ksi": five_year_avg_ksi},
        )

        return WardDetailTrendResponse(
            ward=ward,
            yearly_trends=yearly_trends,
            monthly_seasonality=monthly_seasonality,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get ward detail trends", error=str(e))
        raise

"""Dashboard API endpoints for the Chicago Crash Dashboard frontend."""

import json
from datetime import datetime, time, timedelta
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.models.base import get_db
from src.models.crashes import Crash, CrashPerson
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Chicago timezone - all crash data from the Chicago Data Portal is in local Chicago time
CHICAGO_TZ = ZoneInfo("America/Chicago")

# FHWA Crash Cost Constants (2024$)
# Source: https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf
# KABCO Person-Injury Unit Costs
KABCO_COSTS = {
    # injury_classification: (economic, qaly, comprehensive)
    "FATAL": (1_606_644, 9_651_851, 11_258_495),  # K
    "INCAPACITATING INJURY": (172_179, 917_345, 1_089_524),  # A
    "NONINCAPACITATING INJURY": (44_490, 180_107, 224_597),  # B
    "REPORTED, NOT EVIDENT": (25_933, 85_348, 111_281),  # C
    "NO INDICATION OF INJURY": (6_269, 3_927, 10_196),  # O
}

# Vehicle unit cost (QALY = 0 for vehicles)
VEHICLE_ECONOMIC_COST = 7_913

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


class LocationReportStats(BaseModel):
    """Aggregate statistics for a location."""

    total_crashes: int
    total_injuries: int
    total_fatalities: int
    pedestrians_involved: int
    cyclists_involved: int
    hit_and_run_count: int
    incapacitating_injuries: int
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
    unit_cost: int = Field(description="Per-vehicle economic cost")
    subtotal_economic: int = Field(description="count * unit_cost")


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
        # Validate request - must have either radius query, polygon, or place
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

        # Normalize end_date
        end_date_normalized = normalize_end_date(request.end_date)

        # Build the spatial filter SQL based on query type
        if has_place_query:
            # Look up the place geometry
            place_geometry_result = _get_place_geometry(
                db, request.place_type, request.place_id
            )
            if not place_geometry_result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Place not found: {request.place_type}/{request.place_id}",
                )

            place_name, place_geometry = place_geometry_result

            # Use ST_Contains with the place geometry
            spatial_filter = """
                ST_Contains(
                    ST_SetSRID(ST_GeomFromGeoJSON(:place_geojson), 4326),
                    geometry
                )
            """
            spatial_filter_aliased = """
                ST_Contains(
                    ST_SetSRID(ST_GeomFromGeoJSON(:place_geojson), 4326),
                    c.geometry
                )
            """
            spatial_params = {"place_geojson": json.dumps(place_geometry)}

            # Query area is the place geometry
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
            # Convert feet to meters (1 foot = 0.3048 meters)
            radius_meters = request.radius_feet * 0.3048

            # Create a point and buffer for the query area
            # Note: For single-table queries, we use unqualified column names.
            # For JOIN queries (like people_query), we use c.geometry
            spatial_filter = """
                ST_DWithin(
                    geometry::geography,
                    ST_SetSRID(ST_MakePoint(:center_lng, :center_lat), 4326)::geography,
                    :radius_meters
                )
            """
            # Spatial filter with table alias for JOIN queries
            spatial_filter_aliased = """
                ST_DWithin(
                    c.geometry::geography,
                    ST_SetSRID(ST_MakePoint(:center_lng, :center_lat), 4326)::geography,
                    :radius_meters
                )
            """
            spatial_params = {
                "center_lat": request.latitude,
                "center_lng": request.longitude,
                "radius_meters": radius_meters,
            }

            # Generate query area GeoJSON (circle approximation)
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
            # Polygon query - close the ring if needed
            coords = request.polygon.copy()
            if coords[0] != coords[-1]:
                coords.append(coords[0])

            # Build WKT polygon string
            coord_str = ", ".join([f"{c[0]} {c[1]}" for c in coords])
            polygon_wkt = f"POLYGON(({coord_str}))"

            spatial_filter = """
                ST_Contains(
                    ST_SetSRID(ST_GeomFromText(:polygon_wkt), 4326),
                    geometry
                )
            """
            # Spatial filter with table alias for JOIN queries
            spatial_filter_aliased = """
                ST_Contains(
                    ST_SetSRID(ST_GeomFromText(:polygon_wkt), 4326),
                    c.geometry
                )
            """
            spatial_params = {"polygon_wkt": polygon_wkt}

            # Query area is the polygon itself
            query_area_geojson = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                },
                "properties": {"type": "polygon"},
            }

        # Build date filter (unqualified for single-table queries)
        date_filter = ""
        # Build date filter with table alias for JOIN queries
        date_filter_aliased = ""
        if request.start_date:
            date_filter += " AND crash_date >= :start_date"
            date_filter_aliased += " AND c.crash_date >= :start_date"
            spatial_params["start_date"] = request.start_date
        if end_date_normalized:
            date_filter += " AND crash_date <= :end_date"
            date_filter_aliased += " AND c.crash_date <= :end_date"
            spatial_params["end_date"] = end_date_normalized

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
                )) AS unknown_count
            FROM crash_people cp
            INNER JOIN crashes c ON cp.crash_record_id = c.crash_record_id
            WHERE c.geometry IS NOT NULL
                AND {spatial_filter_aliased}
                {date_filter_aliased}
        """)

        people_result = db.execute(people_query, spatial_params).fetchone()

        # Get vehicle count for vehicle costs
        vehicles_query = text(f"""
            SELECT COUNT(*) AS vehicle_count
            FROM crash_vehicles cv
            INNER JOIN crashes c ON cv.crash_record_id = c.crash_record_id
            WHERE c.geometry IS NOT NULL
                AND {spatial_filter_aliased}
                {date_filter_aliased}
        """)

        vehicles_result = db.execute(vehicles_query, spatial_params).fetchone()
        total_vehicles = vehicles_result.vehicle_count or 0

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

        # Add vehicle costs (economic only, QALY = 0)
        vehicle_economic_cost = total_vehicles * VEHICLE_ECONOMIC_COST

        # Total costs
        estimated_economic_damages = person_economic_cost + vehicle_economic_cost
        estimated_societal_costs = estimated_economic_damages + person_qaly_cost

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
            count=total_vehicles,
            unit_cost=VEHICLE_ECONOMIC_COST,
            subtotal_economic=vehicle_economic_cost,
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

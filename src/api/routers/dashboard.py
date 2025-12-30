"""Dashboard API endpoints for the Chicago Crash Dashboard frontend."""

from datetime import datetime, time, timedelta
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
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

    Returns comprehensive crash statistics, cause breakdown, trends, and GeoJSON data.
    """
    try:
        # Validate request - must have either radius query or polygon
        has_radius_query = all([
            request.latitude is not None,
            request.longitude is not None,
            request.radius_feet is not None,
        ])
        has_polygon_query = request.polygon is not None and len(request.polygon) >= 3

        if not has_radius_query and not has_polygon_query:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Must provide either (latitude, longitude, radius_feet) or polygon coordinates",
            )

        # Normalize end_date
        end_date_normalized = normalize_end_date(request.end_date)

        # Build the spatial filter SQL
        if has_radius_query:
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
            import json
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

        # Get pedestrian and cyclist counts from people table
        # Need to join with crashes that match our spatial filter
        # Use aliased versions since this is a JOIN query
        people_query = text(f"""
            SELECT
                COUNT(*) FILTER (WHERE person_type ILIKE '%PEDESTRIAN%') AS pedestrians,
                COUNT(*) FILTER (WHERE person_type ILIKE '%BICYCLE%' OR person_type ILIKE '%CYCLIST%' OR person_type ILIKE '%PEDALCYCLIST%') AS cyclists
            FROM crash_people cp
            INNER JOIN crashes c ON cp.crash_record_id = c.crash_record_id
            WHERE c.geometry IS NOT NULL
                AND {spatial_filter_aliased}
                {date_filter_aliased}
        """)

        people_result = db.execute(people_query, spatial_params).fetchone()

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

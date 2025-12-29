"""Dashboard API endpoints for the Chicago Crash Dashboard frontend."""

from datetime import datetime, time, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.models.base import get_db
from src.models.crashes import Crash, CrashPerson
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
    weeks: int = Query(default=52, le=104, ge=1),
    db: Session = Depends(get_db),
) -> list[WeeklyTrend]:
    """
    Get weekly crash trends for charts.

    Returns crash, injury, and fatality counts grouped by week.
    """
    try:
        # Calculate start date
        start_date = datetime.now() - timedelta(weeks=weeks)

        # Query for weekly aggregates using PostgreSQL date_trunc
        query = text("""
            SELECT
                date_trunc('week', crash_date)::date AS week_start,
                COUNT(*) AS crashes,
                COALESCE(SUM(injuries_total), 0) AS injuries,
                COALESCE(SUM(injuries_fatal), 0) AS fatalities
            FROM crashes
            WHERE crash_date >= :start_date
                AND crash_date IS NOT NULL
            GROUP BY date_trunc('week', crash_date)
            ORDER BY week_start
        """)

        result = db.execute(query, {"start_date": start_date})
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

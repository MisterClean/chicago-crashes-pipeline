"""Health check and system status endpoints."""
import asyncio
import sys
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from src.api.dependencies import get_sync_state
from src.api.models import HealthResponse
from src.etl.soda_client import SODAClient
from src.models.base import SessionLocal
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint."""
    services_status = {}
    overall_healthy = True

    try:
        # Test configuration loading
        _ = settings.api.endpoints
        services_status["configuration"] = "healthy"
    except Exception as e:
        services_status["configuration"] = f"error: {str(e)}"
        overall_healthy = False

    try:
        client = SODAClient()
        test_records = await _fetch_single_record(client)
        services_status["soda_client"] = "healthy"
        services_status["api_connectivity"] = (
            "healthy" if test_records else "warning: no data returned"
        )
        if not test_records:
            overall_healthy = False
    except Exception as e:
        services_status["soda_client"] = f"warning: {str(e)}"
        services_status["api_connectivity"] = "warning: external API unavailable"

    # Database connectivity
    try:
        await _check_database()
        services_status["database"] = "healthy"
    except Exception as e:
        logger.warning("Database health check failed", error=str(e))
        services_status["database"] = f"warning: {str(e)}"
        overall_healthy = False

    status = "healthy" if overall_healthy else "degraded"

    if not overall_healthy:
        logger.warning("Health check failed", services=services_status)

    logger.debug("Health check services", services=services_status)
    return HealthResponse(
        status=status, timestamp=datetime.now(), services=services_status
    )


async def _fetch_single_record(client: Any) -> Any:
    """Fetch a small sample record, supporting mocked clients used in tests."""

    if hasattr(client, "__aenter__"):
        async with client:
            return await client.fetch_records(
                endpoint=settings.api.endpoints["crashes"],
                limit=1,
            )

    # Fallback for mocks that don't implement async context manager
    try:
        result = client.fetch_records(
            endpoint=settings.api.endpoints["crashes"],
            limit=1,
        )
        if asyncio.iscoroutine(result):
            result = await result
        return result
    finally:
        closer = getattr(client, "close", None)
        if closer:
            maybe = closer()
            if asyncio.iscoroutine(maybe):
                await maybe


async def _check_database() -> None:
    """Run a lightweight database connectivity check off the event loop."""

    def _probe() -> None:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()

    await asyncio.to_thread(_probe)


@router.get("/")
async def root(sync_state: dict = Depends(get_sync_state)):
    """Root endpoint with API information."""
    uptime = "unknown"
    if "started_at" in sync_state:
        uptime = str(datetime.now() - sync_state["started_at"])

    return {
        "name": "Chicago Crash Data Pipeline API",
        "version": "1.0.0",
        "status": "online",
        "uptime": uptime,
        "sync_status": sync_state["status"],
        "endpoints": {
            "health": "/health",
            "sync_status": "/sync/status",
            "trigger_sync": "/sync/trigger",
            "test_sync": "/sync/test",
            "endpoints_info": "/sync/endpoints",
            "validate_data": "/validate",
            "docs": "/docs",
            "openapi": "/openapi.json",
        },
        "data_sources": {
            "crashes": "Traffic Crashes - Crashes",
            "people": "Traffic Crashes - People",
            "vehicles": "Traffic Crashes - Vehicles",
            "fatalities": "Vision Zero Fatalities",
        },
    }


@router.get("/version")
async def get_version():
    """Get API version and build information."""
    return {
        "version": "1.0.0",
        "build_date": "2024-08-28",  # Would be set during build
        "commit": "unknown",  # Would be set from git during build
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "dependencies": {"fastapi": "0.104.1", "pydantic": "2.5.0", "httpx": "0.25.2"},
    }

"""Health check and system status endpoints."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from api.models import HealthResponse
from api.dependencies import get_soda_client, get_sync_state
from etl.soda_client import SODAClient
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(client: SODAClient = Depends(get_soda_client)):
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
        # Test SODA client initialization
        _ = SODAClient()
        services_status["soda_client"] = "healthy"
    except Exception as e:
        services_status["soda_client"] = f"error: {str(e)}"
        overall_healthy = False
    
    try:
        # Test basic API connectivity (small request)
        test_records = await client.fetch_records(
            endpoint=settings.api.endpoints["crashes"],
            limit=1
        )
        if test_records:
            services_status["api_connectivity"] = "healthy"
        else:
            services_status["api_connectivity"] = "warning: no data returned"
    except Exception as e:
        services_status["api_connectivity"] = f"error: {str(e)}"
        overall_healthy = False
    
    # Database would be tested here if connected
    services_status["database"] = "not_connected"
    
    status = "healthy" if overall_healthy else "degraded"
    
    if not overall_healthy:
        logger.warning("Health check failed", services=services_status)
    
    return HealthResponse(
        status=status,
        timestamp=datetime.now(),
        services=services_status
    )


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
            "openapi": "/openapi.json"
        },
        "data_sources": {
            "crashes": "Traffic Crashes - Crashes",
            "people": "Traffic Crashes - People", 
            "vehicles": "Traffic Crashes - Vehicles",
            "fatalities": "Vision Zero Fatalities"
        }
    }


@router.get("/version")
async def get_version():
    """Get API version and build information."""
    return {
        "version": "1.0.0",
        "build_date": "2024-08-28",  # Would be set during build
        "commit": "unknown",  # Would be set from git during build
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "dependencies": {
            "fastapi": "0.104.1",
            "pydantic": "2.5.0",
            "httpx": "0.25.2"
        }
    }
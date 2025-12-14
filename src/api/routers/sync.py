"""Sync operation endpoints."""

import asyncio
import inspect
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.api.dependencies import get_sync_lock, get_sync_state
from src.api.models import StatusResponse, SyncRequest, SyncResponse, TestSyncResponse
from src.etl.soda_client import SODAClient
from src.services.database_service import DatabaseService as _DatabaseService
from src.services.sync_service import SyncService
from src.utils.config import settings
from src.utils.logging import get_logger
from src.validators.data_sanitizer import DataSanitizer

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])

# Backwards-compatibility alias for legacy patches targeting this module
DatabaseService = _DatabaseService


def get_soda_client() -> SODAClient:
    """Factory used so tests can patch SODA client creation."""
    return SODAClient()


def get_data_sanitizer() -> DataSanitizer:
    """Factory used so tests can patch data sanitizer creation."""
    return DataSanitizer()


async def _maybe_await(result):
    """Await the value if it's awaitable."""
    if inspect.isawaitable(result):
        return await result
    return result


@router.get("/status", response_model=StatusResponse)
async def get_sync_status(sync_state: dict = Depends(get_sync_state)):
    """Get current sync status and statistics."""
    started_at = sync_state.get("started_at", datetime.now())
    uptime = str(datetime.now() - started_at)

    return StatusResponse(
        status="idle"
        if sync_state["status"] == "running" and sync_state["current_operation"] is None
        else sync_state["status"],
        last_sync=sync_state["last_sync"],
        current_operation=sync_state["current_operation"],
        stats=sync_state["stats"],
        uptime=uptime,
    )


@router.post("/trigger", response_model=SyncResponse)
async def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    sync_state: dict = Depends(get_sync_state),
):
    """Trigger a manual sync operation."""
    # Prevent concurrent syncs using shared lock state
    sync_lock = get_sync_lock()

    if sync_state["status"] == "running" or sync_lock.locked():
        raise HTTPException(
            status_code=409, detail="Sync operation already in progress"
        )

    # Generate sync ID
    sync_id = f"sync_{int(datetime.now().timestamp())}"

    # Update sync state
    sync_state["status"] = "running"
    sync_state["current_operation"] = f"Manual sync {sync_id}"

    # Add background task
    background_tasks.add_task(
        guarded_run_sync_operation,
        sync_id,
        request,
        sync_state,
    )

    logger.info("Triggered manual sync", sync_id=sync_id, request=request.dict())

    return SyncResponse(
        message="Sync operation started",
        sync_id=sync_id,
        status="running",
        started_at=datetime.now(),
    )


@router.post("/test", response_model=TestSyncResponse)
async def test_sync(sync_state: dict = Depends(get_sync_state)):
    """Test sync operation with a small dataset."""
    try:
        sync_state["status"] = "testing"
        sync_state["current_operation"] = "Test sync"

        client = get_soda_client()
        sanitizer = get_data_sanitizer()

        test_records = await _fetch_sample_records(client)

        # Test data sanitization
        cleaned_records = []
        for record in test_records:
            cleaned = sanitizer.sanitize_crash_record(record)
            cleaned_records.append(cleaned)

        sync_state["status"] = "idle"
        sync_state["current_operation"] = None

        return TestSyncResponse(
            status="success",
            message="Test sync completed successfully",
            records_fetched=len(test_records),
            records_cleaned=len(cleaned_records),
            sample_record=cleaned_records[0] if cleaned_records else None,
        )

    except Exception as e:
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["stats"]["last_error"] = str(e)

        logger.error("Test sync failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Test sync failed: {str(e)}")


@router.get("/endpoints")
async def get_endpoints():
    """Get information about available data endpoints."""
    endpoints_info = []

    for name, url in settings.api.endpoints.items():
        description_map = {
            "crashes": "Main crash records with location and injury data",
            "people": "Person-level injury and demographic data",
            "vehicles": "Vehicle/unit information involved in crashes",
            "fatalities": "Curated fatality dataset from Vision Zero initiative",
        }

        endpoints_info.append(
            {
                "name": name,
                "url": url,
                "description": description_map.get(name, "Chicago crash data endpoint"),
            }
        )

    return {"endpoints": endpoints_info, "total_endpoints": len(endpoints_info)}


@router.get("/counts")
async def get_database_counts():
    """Get current record counts in the database."""
    try:
        db_service = DatabaseService()
        counts = db_service.get_record_counts()

        return {
            "status": "success",
            "counts": counts,
            "total_records": sum(counts.values()) if counts else 0,
            "timestamp": datetime.now(),
        }
    except Exception as e:
        logger.error("Failed to get database counts", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to get database counts: {str(e)}"
        )


async def _fetch_sample_records(client: Any, limit: int = 5) -> list[dict[str, Any]]:
    """Fetch a small number of crash records, accommodating patched clients."""

    if hasattr(client, "__aenter__"):
        async with client:
            return await client.fetch_records(
                endpoint=settings.api.endpoints["crashes"],
                limit=limit,
            )

    result = client.fetch_records(
        endpoint=settings.api.endpoints["crashes"],
        limit=limit,
    )
    if asyncio.iscoroutine(result):
        result = await result

    closer = getattr(client, "close", None)
    if closer:
        maybe = closer()
        if asyncio.iscoroutine(
            maybe
        ):  # pragma: no cover - depends on client implementation
            await maybe

    return result


async def guarded_run_sync_operation(
    sync_id: str, request: SyncRequest, sync_state: dict
) -> None:
    """Wrap sync execution with the global sync lock."""
    sync_lock = get_sync_lock()
    async with sync_lock:
        await run_sync_operation(
            sync_id=sync_id,
            sync_state=sync_state,
            start_date=request.start_date,
            end_date=request.end_date,
            endpoint=request.endpoint,
        )


async def run_sync_operation(
    *,
    sync_id: str,
    sync_state: dict,
    start_date: str | None = None,
    end_date: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Background task to run sync operation."""
    start_time = datetime.now()

    try:
        logger.info("Starting sync operation", sync_id=sync_id)

        sync_state["stats"]["total_syncs"] += 1

        endpoints_to_sync = (
            [endpoint] if endpoint else list(settings.api.endpoints.keys())
        )

        sanitizer = get_data_sanitizer()
        sync_service = SyncService(
            client_factory=get_soda_client,
            sanitizer=sanitizer,
            database_service=DatabaseService(),
        )

        sync_state["current_operation"] = "Preparing sync"

        service_result = await sync_service.sync(
            endpoints=endpoints_to_sync,
            start_date=start_date,
            end_date=end_date,
        )

        duration = (datetime.now() - start_time).total_seconds()

        # Small delay so status endpoints register running state before reset
        await asyncio.sleep(0.3)

        # Mark sync as completed
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["last_sync"] = datetime.now()
        sync_state["stats"]["successful_syncs"] += 1
        sync_state["stats"]["total_records_processed"] += service_result.total_records
        sync_state["stats"]["last_sync_duration"] = duration

        logger.info(
            "Sync operation completed successfully",
            sync_id=sync_id,
            total_records=service_result.total_records,
            total_inserted=service_result.total_inserted,
            total_updated=service_result.total_updated,
            duration=duration,
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()

        await asyncio.sleep(0.3)

        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["stats"]["failed_syncs"] += 1
        sync_state["stats"]["last_error"] = str(e)
        sync_state["stats"]["last_sync_duration"] = duration

        logger.error(
            "Sync operation failed", sync_id=sync_id, error=str(e), duration=duration
        )

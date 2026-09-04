"""Sync operation endpoints."""

import asyncio
import inspect
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from src.api.dependencies import get_sync_lock, get_sync_state
from src.api.models import StatusResponse, SyncRequest, SyncResponse, TestSyncResponse
from src.etl.soda_client import SODAClient
from src.models.base import SessionLocal
from src.models.jobs import JobExecution, JobStatus, JobType, RecurrenceType
from src.services.database_service import DatabaseService as _DatabaseService
from src.services.job_service import JobService
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
    try:
        with SessionLocal() as session:
            latest = (
                session.query(JobExecution).order_by(JobExecution.id.desc()).first()
            )
            last_success = (
                session.query(func.max(JobExecution.completed_at))
                .filter(JobExecution.status == JobStatus.COMPLETED)
                .scalar()
            )
            active = (
                session.query(JobExecution)
                .filter(JobExecution.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
                .order_by(JobExecution.id)
                .first()
            )
            counts = dict(
                session.query(JobExecution.status, func.count())
                .group_by(JobExecution.status)
                .all()
            )
            return StatusResponse(
                status=active.status if active else "idle",
                last_sync=last_success,
                current_operation=active.execution_id if active else None,
                stats={
                    "total_syncs": sum(counts.values()),
                    "successful_syncs": counts.get(JobStatus.COMPLETED, 0),
                    "failed_syncs": counts.get(JobStatus.FAILED, 0),
                    "last_error": latest.error_message if latest else None,
                    "last_execution_id": latest.execution_id if latest else None,
                },
                uptime=str(
                    datetime.now() - sync_state.get("started_at", datetime.now())
                ),
            )
    except SQLAlchemyError as exc:
        logger.error("Sync status database unavailable", error=type(exc).__name__)
        raise HTTPException(503, "Sync status is temporarily unavailable") from exc


@router.post("/trigger", response_model=SyncResponse, status_code=202)
async def trigger_sync(request: SyncRequest):
    """Persist manual work for the same worker used by scheduled executions."""
    if request.endpoint is not None and request.endpoint not in settings.api.endpoints:
        raise HTTPException(status_code=422, detail="Unknown endpoint")
    if request.mode == "full" and (request.start_date or request.end_date):
        raise HTTPException(
            status_code=422, detail="Full refresh cannot have date filters"
        )
    mode = "api" if request.start_date or request.end_date else request.mode
    service = JobService()
    try:
        job = service.create_job(
            {
                "name": "Manual sync",
                "job_type": JobType.FULL_REFRESH
                if mode == "full"
                else (JobType.INCREMENTAL if mode == "incremental" else JobType.CUSTOM),
                "enabled": False,
                "recurrence_type": RecurrenceType.ONCE,
                "timeout_minutes": 480 if mode == "full" else 60,
                "config": {
                    "endpoints": [request.endpoint]
                    if request.endpoint
                    else list(settings.api.endpoints),
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "mode": mode,
                },
            },
            created_by="manual-sync",
        )
        identifier = await service.execute_job(job.id, force=request.force)
    except SQLAlchemyError as exc:
        logger.error("Unable to queue sync", error=type(exc).__name__)
        raise HTTPException(503, "Sync queue is temporarily unavailable") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return SyncResponse(
        message="Sync queued for worker",
        sync_id=identifier,
        status="pending",
        started_at=datetime.utcnow(),
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

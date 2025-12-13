"""Job management endpoints."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.models import (CreateJobRequest, DataDeletionRequest,
                            DataDeletionResponse, ErrorResponse,
                            ExecuteJobRequest, ExecuteJobResponse,
                            ExecutionLogEntry, JobExecutionDetailResponse,
                            JobExecutionResponse, JobResponse,
                            JobSummaryResponse, UpdateJobRequest)
from src.models.base import get_db
from src.models.jobs import (JobExecution, JobStatus, JobType, RecurrenceType,
                             ScheduledJob)
from src.services.job_service import JobService
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

# Initialize job service
job_service = JobService()


def _build_execution_response(execution: JobExecution) -> JobExecutionResponse:
    """Convert execution ORM model to API response."""
    return JobExecutionResponse(
        id=execution.id,
        execution_id=execution.execution_id,
        job_id=execution.job_id,
        job_name=execution.job.name if execution.job else None,
        status=execution.status,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_seconds=execution.duration_seconds,
        records_processed=execution.records_processed or 0,
        records_inserted=execution.records_inserted or 0,
        records_updated=execution.records_updated or 0,
        records_skipped=execution.records_skipped or 0,
        error_message=execution.error_message,
        retry_count=execution.retry_count,
        created_at=execution.created_at,
    )


def _parse_execution_logs(raw_logs: Any) -> List[ExecutionLogEntry]:
    """Normalise stored execution logs into response entries."""
    if not isinstance(raw_logs, list):
        return []

    parsed_logs: List[ExecutionLogEntry] = []
    for entry in raw_logs:
        if not isinstance(entry, dict):
            continue

        timestamp_value = entry.get("timestamp")
        if isinstance(timestamp_value, datetime):
            timestamp = timestamp_value
        elif isinstance(timestamp_value, str):
            timestamp = _coerce_timestamp(timestamp_value)
        else:
            timestamp = datetime.utcnow()

        level = str(entry.get("level", "info"))
        message = str(entry.get("message", ""))

        parsed_logs.append(
            ExecutionLogEntry(
                timestamp=timestamp,
                level=level,
                message=message,
            )
        )

    return parsed_logs


def _coerce_timestamp(value: str) -> datetime:
    """Parse ISO formatted timestamp strings safely."""
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.utcnow()


# Note: Initialization is now handled in the main app startup


@router.get("/", response_model=List[JobResponse])
async def list_jobs(
    enabled_only: bool = Query(False, description="Filter to only enabled jobs")
):
    """List all scheduled jobs."""
    try:
        jobs = job_service.get_jobs(enabled_only=enabled_only)

        return [
            JobResponse(
                id=job.id,
                name=job.name,
                description=job.description,
                job_type=job.job_type,
                enabled=job.enabled,
                recurrence_type=job.recurrence_type,
                cron_expression=job.cron_expression,
                next_run=job.next_run,
                last_run=job.last_run,
                config=job.config,
                timeout_minutes=job.timeout_minutes,
                max_retries=job.max_retries,
                retry_delay_minutes=job.retry_delay_minutes,
                created_by=job.created_by,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            for job in jobs
        ]
    except Exception as e:
        logger.error(f"Failed to list jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@router.get("/summary", response_model=JobSummaryResponse)
async def get_jobs_summary():
    """Get summary statistics for all jobs."""
    try:
        summary = job_service.get_job_summary()
        return JobSummaryResponse(**summary)
    except Exception as e:
        logger.error(f"Failed to get jobs summary: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get jobs summary: {str(e)}"
        )


@router.post("/", response_model=JobResponse, status_code=201)
async def create_job(request: CreateJobRequest):
    """Create a new scheduled job."""
    try:
        # Validate job type
        if request.job_type not in [jt.value for jt in JobType]:
            raise HTTPException(
                status_code=400, detail=f"Invalid job type: {request.job_type}"
            )

        # Validate recurrence type
        if request.recurrence_type not in [rt.value for rt in RecurrenceType]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid recurrence type: {request.recurrence_type}",
            )

        job_data = {
            "name": request.name,
            "description": request.description,
            "job_type": request.job_type,
            "enabled": request.enabled,
            "recurrence_type": request.recurrence_type,
            "cron_expression": request.cron_expression,
            "config": request.config.dict(),
            "timeout_minutes": request.timeout_minutes,
            "max_retries": request.max_retries,
            "retry_delay_minutes": request.retry_delay_minutes,
        }

        job = job_service.create_job(job_data, created_by="admin")

        return JobResponse(
            id=job.id,
            name=job.name,
            description=job.description,
            job_type=job.job_type,
            enabled=job.enabled,
            recurrence_type=job.recurrence_type,
            cron_expression=job.cron_expression,
            next_run=job.next_run,
            last_run=job.last_run,
            config=job.config,
            timeout_minutes=job.timeout_minutes,
            max_retries=job.max_retries,
            retry_delay_minutes=job.retry_delay_minutes,
            created_by=job.created_by,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int):
    """Get a specific job by ID."""
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobResponse(
        id=job.id,
        name=job.name,
        description=job.description,
        job_type=job.job_type,
        enabled=job.enabled,
        recurrence_type=job.recurrence_type,
        cron_expression=job.cron_expression,
        next_run=job.next_run,
        last_run=job.last_run,
        config=job.config,
        timeout_minutes=job.timeout_minutes,
        max_retries=job.max_retries,
        retry_delay_minutes=job.retry_delay_minutes,
        created_by=job.created_by,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(job_id: int, request: UpdateJobRequest):
    """Update an existing job."""
    try:
        updates = {}

        # Only include non-None values
        for field, value in request.dict(exclude_unset=True).items():
            if field == "config" and value:
                updates[field] = value.dict() if hasattr(value, "dict") else value
            else:
                updates[field] = value

        # Validate job type if provided
        if "job_type" in updates and updates["job_type"] not in [
            jt.value for jt in JobType
        ]:
            raise HTTPException(
                status_code=400, detail=f"Invalid job type: {updates['job_type']}"
            )

        # Validate recurrence type if provided
        if "recurrence_type" in updates and updates["recurrence_type"] not in [
            rt.value for rt in RecurrenceType
        ]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid recurrence type: {updates['recurrence_type']}",
            )

        job = job_service.update_job(job_id, updates)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        return JobResponse(
            id=job.id,
            name=job.name,
            description=job.description,
            job_type=job.job_type,
            enabled=job.enabled,
            recurrence_type=job.recurrence_type,
            cron_expression=job.cron_expression,
            next_run=job.next_run,
            last_run=job.last_run,
            config=job.config,
            timeout_minutes=job.timeout_minutes,
            max_retries=job.max_retries,
            retry_delay_minutes=job.retry_delay_minutes,
            created_by=job.created_by,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update job: {str(e)}")


@router.delete("/{job_id}")
async def delete_job(job_id: int):
    """Delete a job."""
    try:
        success = job_service.delete_job(job_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        return {"message": f"Job {job_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


@router.post("/{job_id}/execute", response_model=ExecuteJobResponse)
async def execute_job(job_id: int, request: ExecuteJobRequest):
    """Manually execute a job."""
    try:
        override_config = None
        if request.override_config:
            override_config = request.override_config.dict()

        execution_id = await job_service.execute_job(
            job_id=job_id, force=request.force, override_config=override_config
        )

        return ExecuteJobResponse(
            message=f"Job {job_id} execution started",
            execution_id=execution_id,
            job_id=job_id,
            status=JobStatus.PENDING,
            started_at=datetime.now(),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to execute job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to execute job: {str(e)}")


@router.get("/{job_id}/executions", response_model=List[JobExecutionResponse])
async def get_job_executions(
    job_id: int,
    limit: int = Query(
        50, ge=1, le=200, description="Limit number of executions returned"
    ),
):
    """Get execution history for a job."""
    try:
        executions = job_service.get_job_executions(job_id=job_id, limit=limit)

        return [_build_execution_response(execution) for execution in executions]

    except Exception as e:
        logger.error(f"Failed to get executions for job {job_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get executions: {str(e)}"
        )


@router.get("/executions/recent", response_model=List[JobExecutionResponse])
async def get_recent_executions(
    limit: int = Query(
        50, ge=1, le=200, description="Limit number of executions returned"
    )
):
    """Get recent execution history across all jobs."""
    try:
        executions = job_service.get_job_executions(limit=limit)

        return [_build_execution_response(execution) for execution in executions]

    except Exception as e:
        logger.error(f"Failed to get recent executions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get executions: {str(e)}"
        )


@router.get("/executions/{execution_id}", response_model=JobExecutionDetailResponse)
async def get_execution_detail(execution_id: str):
    """Get detailed execution information including logs."""
    try:
        execution = job_service.get_execution_by_identifier(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        context = (
            execution.execution_context
            if isinstance(execution.execution_context, dict)
            else {}
        )
        logs = _parse_execution_logs(context.get("logs"))

        return JobExecutionDetailResponse(
            id=execution.id,
            execution_id=execution.execution_id,
            job_id=execution.job_id,
            job_name=execution.job.name if execution.job else None,
            status=execution.status,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            duration_seconds=execution.duration_seconds,
            records_processed=execution.records_processed or 0,
            records_inserted=execution.records_inserted or 0,
            records_updated=execution.records_updated or 0,
            records_skipped=execution.records_skipped or 0,
            error_message=execution.error_message,
            retry_count=execution.retry_count,
            created_at=execution.created_at,
            execution_context=context or None,
            logs=logs,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution {execution_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get execution: {str(e)}"
        )


@router.post("/data/delete", response_model=DataDeletionResponse)
async def delete_table_data(request: DataDeletionRequest):
    """Delete data from a table with optional date filtering."""
    try:
        # Validate table name
        valid_tables = [
            "crashes",
            "crash_people",
            "crash_vehicles",
            "vision_zero_fatalities",
        ]
        if request.table_name not in valid_tables:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid table name. Valid options: {valid_tables}",
            )

        # Safety check - require confirmation
        if not request.confirm:
            raise HTTPException(
                status_code=400,
                detail="Data deletion requires confirmation. Set 'confirm' to true.",
            )

        result = job_service.delete_all_data(
            table_name=request.table_name, date_range=request.date_range
        )

        return DataDeletionResponse(
            message=f"Successfully deleted {result['records_deleted']} records from {request.table_name}",
            table_name=request.table_name,
            records_deleted=result["records_deleted"],
            execution_time_seconds=result["execution_time_seconds"],
            backup_location=result["backup_location"],
            can_restore=result["can_restore"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete data from {request.table_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete data: {str(e)}")


@router.get("/types", response_model=Dict[str, Any])
async def get_job_types():
    """Get available job types and recurrence types."""
    return {
        "job_types": [
            {"value": jt.value, "label": jt.value.replace("_", " ").title()}
            for jt in JobType
        ],
        "recurrence_types": [
            {"value": rt.value, "label": rt.value.replace("_", " ").title()}
            for rt in RecurrenceType
        ],
        "valid_endpoints": ["crashes", "people", "vehicles", "fatalities"],
        "valid_tables": [
            "crashes",
            "crash_people",
            "crash_vehicles",
            "vision_zero_fatalities",
        ],
    }

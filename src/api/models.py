"""Pydantic models for API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request model for sync operations."""

    start_date: str | None = Field(
        None, description="Start date for sync in YYYY-MM-DD format"
    )
    end_date: str | None = Field(
        None, description="End date for sync in YYYY-MM-DD format"
    )
    force: bool = Field(False, description="Force sync even if recently completed")
    endpoint: str | None = Field(
        None,
        description="Specific endpoint to sync (crashes, people, vehicles, fatalities)",
    )


class SyncResponse(BaseModel):
    """Response model for sync operations."""

    message: str
    sync_id: str
    status: str
    started_at: datetime


class StatusResponse(BaseModel):
    """Response model for status checks."""

    status: str
    last_sync: datetime | None
    current_operation: str | None
    stats: dict[str, Any]
    uptime: str


class HealthResponse(BaseModel):
    """Response model for health checks."""

    status: str
    timestamp: datetime
    services: dict[str, str]


class TestSyncResponse(BaseModel):
    """Response model for test sync operations."""

    status: str
    message: str
    records_fetched: int
    records_cleaned: int
    sample_record: dict[str, Any] | None


class ErrorResponse(BaseModel):
    """Response model for errors."""

    detail: str
    error_code: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class DataValidationResponse(BaseModel):
    """Response model for data validation results."""

    endpoint: str
    total_records: int
    valid_records: int
    invalid_records: int
    validation_errors: list[str]
    warnings: list[str]


class EndpointInfo(BaseModel):
    """Information about a data endpoint."""

    name: str
    url: str
    description: str
    record_count_estimate: int | None = None
    last_updated: datetime | None = None


# Job Management API Models


class JobConfig(BaseModel):
    """Job configuration parameters."""

    endpoints: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    date_range_days: int | None = None
    force: bool = False
    description: str | None = None


class CreateJobRequest(BaseModel):
    """Request model for creating a new job."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    job_type: str
    enabled: bool = True
    recurrence_type: str
    cron_expression: str | None = None
    config: JobConfig
    timeout_minutes: int = Field(default=60, gt=0, le=480)  # Max 8 hours
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_minutes: int = Field(default=5, ge=1, le=60)


class UpdateJobRequest(BaseModel):
    """Request model for updating an existing job."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    enabled: bool | None = None
    recurrence_type: str | None = None
    cron_expression: str | None = None
    config: JobConfig | None = None
    timeout_minutes: int | None = Field(None, gt=0, le=480)
    max_retries: int | None = Field(None, ge=0, le=10)
    retry_delay_minutes: int | None = Field(None, ge=1, le=60)


class JobResponse(BaseModel):
    """Response model for job operations."""

    id: int
    name: str
    description: str | None
    job_type: str
    enabled: bool
    recurrence_type: str
    cron_expression: str | None
    next_run: datetime | None
    last_run: datetime | None
    config: dict[str, Any]
    timeout_minutes: int
    max_retries: int
    retry_delay_minutes: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class JobExecutionResponse(BaseModel):
    """Response model for job execution details."""

    id: int
    execution_id: str
    job_id: int
    job_name: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int | None
    records_processed: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    error_message: str | None
    retry_count: int
    created_at: datetime


class ExecutionLogEntry(BaseModel):
    """Structured log entry for a job execution."""

    timestamp: datetime
    level: str
    message: str


class JobExecutionDetailResponse(JobExecutionResponse):
    """Detailed response for job execution with logs and context."""

    execution_context: dict[str, Any] | None = None
    logs: list[ExecutionLogEntry] = Field(default_factory=list)


class ExecuteJobRequest(BaseModel):
    """Request model for manual job execution."""

    force: bool = False
    override_config: JobConfig | None = None


class ExecuteJobResponse(BaseModel):
    """Response model for job execution trigger."""

    message: str
    execution_id: str
    job_id: int
    status: str
    started_at: datetime


class DataDeletionRequest(BaseModel):
    """Request model for data deletion operations."""

    table_name: str
    confirm: bool = False
    backup: bool = True
    date_range: dict[str, str] | None = (
        None  # {"start": "2023-01-01", "end": "2023-12-31"}
    )


class DataDeletionResponse(BaseModel):
    """Response model for data deletion operations."""

    message: str
    table_name: str
    records_deleted: int
    execution_time_seconds: float
    backup_location: str | None
    can_restore: bool


class JobSummaryResponse(BaseModel):
    """Summary response for all jobs."""

    total_jobs: int
    active_jobs: int
    running_jobs: int
    failed_jobs_24h: int
    last_execution: datetime | None


class SpatialLayerResponse(BaseModel):
    """Metadata response for a spatial layer."""

    id: int
    name: str
    slug: str
    description: str | None
    geometry_type: str
    srid: int
    feature_count: int
    original_filename: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SpatialLayerDetailResponse(SpatialLayerResponse):
    """Detailed response including sample features."""

    feature_samples: list[dict[str, Any]] = []


class SpatialLayerUpdateRequest(BaseModel):
    """Payload for updating a spatial layer."""

    name: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    is_active: bool | None = None


# Places API Models


class PlaceTypeResponse(BaseModel):
    """Response model for a place type (native boundary or uploaded layer)."""

    id: str
    name: str
    source: str  # "native" or "uploaded"
    feature_count: int


class PlaceItemResponse(BaseModel):
    """Response model for a place within a type."""

    id: str
    name: str
    display_name: str


class PlaceGeometryResponse(BaseModel):
    """Response model for a place's geometry."""

    place_type: str
    place_id: str
    name: str
    geometry: dict[str, Any]  # GeoJSON geometry

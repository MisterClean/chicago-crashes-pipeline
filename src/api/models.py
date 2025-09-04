"""Pydantic models for API requests and responses."""
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request model for sync operations."""
    start_date: Optional[str] = Field(None, description="Start date for sync in YYYY-MM-DD format")
    end_date: Optional[str] = Field(None, description="End date for sync in YYYY-MM-DD format")
    force: bool = Field(False, description="Force sync even if recently completed")
    endpoint: Optional[str] = Field(None, description="Specific endpoint to sync (crashes, people, vehicles, fatalities)")


class SyncResponse(BaseModel):
    """Response model for sync operations."""
    message: str
    sync_id: str
    status: str
    started_at: datetime


class StatusResponse(BaseModel):
    """Response model for status checks."""
    status: str
    last_sync: Optional[datetime]
    current_operation: Optional[str]
    stats: Dict[str, Any]
    uptime: str


class HealthResponse(BaseModel):
    """Response model for health checks."""
    status: str
    timestamp: datetime
    services: Dict[str, str]


class TestSyncResponse(BaseModel):
    """Response model for test sync operations."""
    status: str
    message: str
    records_fetched: int
    records_cleaned: int
    sample_record: Optional[Dict[str, Any]]


class ErrorResponse(BaseModel):
    """Response model for errors."""
    detail: str
    error_code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class DataValidationResponse(BaseModel):
    """Response model for data validation results."""
    endpoint: str
    total_records: int
    valid_records: int
    invalid_records: int
    validation_errors: List[str]
    warnings: List[str]


class EndpointInfo(BaseModel):
    """Information about a data endpoint."""
    name: str
    url: str
    description: str
    record_count_estimate: Optional[int] = None
    last_updated: Optional[datetime] = None


# Job Management API Models

class JobConfig(BaseModel):
    """Job configuration parameters."""
    endpoints: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_range_days: Optional[int] = None
    force: bool = False
    description: Optional[str] = None


class CreateJobRequest(BaseModel):
    """Request model for creating a new job."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    job_type: str
    enabled: bool = True
    recurrence_type: str
    cron_expression: Optional[str] = None
    config: JobConfig
    timeout_minutes: int = Field(default=60, gt=0, le=480)  # Max 8 hours
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_minutes: int = Field(default=5, ge=1, le=60)


class UpdateJobRequest(BaseModel):
    """Request model for updating an existing job."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    recurrence_type: Optional[str] = None
    cron_expression: Optional[str] = None
    config: Optional[JobConfig] = None
    timeout_minutes: Optional[int] = Field(None, gt=0, le=480)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    retry_delay_minutes: Optional[int] = Field(None, ge=1, le=60)


class JobResponse(BaseModel):
    """Response model for job operations."""
    id: int
    name: str
    description: Optional[str]
    job_type: str
    enabled: bool
    recurrence_type: str
    cron_expression: Optional[str]
    next_run: Optional[datetime]
    last_run: Optional[datetime]
    config: Dict[str, Any]
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
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    records_processed: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    error_message: Optional[str]
    retry_count: int
    created_at: datetime


class ExecuteJobRequest(BaseModel):
    """Request model for manual job execution."""
    force: bool = False
    override_config: Optional[JobConfig] = None


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
    date_range: Optional[Dict[str, str]] = None  # {"start": "2023-01-01", "end": "2023-12-31"}
    
    
class DataDeletionResponse(BaseModel):
    """Response model for data deletion operations."""
    message: str
    table_name: str
    records_deleted: int
    execution_time_seconds: float
    backup_location: Optional[str]
    can_restore: bool


class JobSummaryResponse(BaseModel):
    """Summary response for all jobs."""
    total_jobs: int
    active_jobs: int
    running_jobs: int
    failed_jobs_24h: int
    last_execution: Optional[datetime]
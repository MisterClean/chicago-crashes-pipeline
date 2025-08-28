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
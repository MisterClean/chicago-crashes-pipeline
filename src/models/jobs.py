"""Models for job management and scheduling system."""
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import (JSON, BigInteger, Boolean, Column, DateTime, Float,
                        ForeignKey, Index, Integer, String, Text)
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


class JobType(str, Enum):
    """Type of job to execute."""

    FULL_REFRESH = "full_refresh"
    LAST_30_DAYS_CRASHES = "last_30_days_crashes"
    LAST_30_DAYS_PEOPLE = "last_30_days_people"
    LAST_30_DAYS_VEHICLES = "last_30_days_vehicles"
    LAST_6_MONTHS_FATALITIES = "last_6_months_fatalities"
    CUSTOM = "custom"


class RecurrenceType(str, Enum):
    """Job recurrence patterns."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM_CRON = "custom_cron"


class ScheduledJob(Base, TimestampMixin):
    """Scheduled job configuration."""

    __tablename__ = "scheduled_jobs"

    # Primary key
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Job identification
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    job_type = Column(String(50), nullable=False, index=True)

    # Job configuration
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    config = Column(
        JSON
    )  # Stores job-specific configuration (endpoints, date ranges, etc.)

    # Scheduling
    recurrence_type = Column(String(50), nullable=False)
    cron_expression = Column(String(100))  # For custom cron schedules
    next_run = Column(DateTime, index=True)
    last_run = Column(DateTime)

    # Execution settings
    timeout_minutes = Column(Integer, default=60)  # Job timeout
    max_retries = Column(Integer, default=3)
    retry_delay_minutes = Column(Integer, default=5)

    # Metadata
    created_by = Column(String(100), default="system")

    # Relationships
    executions = relationship(
        "JobExecution", back_populates="job", cascade="all, delete-orphan"
    )

    # Indexes (with unique names to avoid conflicts)
    __table_args__ = (
        Index("idx_scheduled_jobs_next_run_enabled", "next_run", "enabled"),
        Index("idx_scheduled_jobs_type_enabled", "job_type", "enabled"),
    )


class JobExecution(Base, TimestampMixin):
    """Individual job execution record."""

    __tablename__ = "job_executions"

    # Primary key
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    execution_id = Column(String(128), unique=True, nullable=False, index=True)

    # Foreign key
    job_id = Column(
        BigInteger, ForeignKey("scheduled_jobs.id"), nullable=False, index=True
    )

    # Execution information
    status = Column(String(50), nullable=False, default=JobStatus.PENDING, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)

    # Results and metrics
    records_processed = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_skipped = Column(Integer, default=0)

    # Error information
    error_message = Column(Text)
    error_details = Column(JSON)  # Stack trace, additional error context
    retry_count = Column(Integer, default=0)

    # Execution context
    execution_context = Column(JSON)  # Store request parameters, system state, etc.

    # Relationship
    job = relationship("ScheduledJob", back_populates="executions")

    # Indexes (with unique names to avoid conflicts)
    __table_args__ = (
        Index("idx_job_executions_status", "status"),
        Index("idx_job_executions_started", "started_at"),
        Index("idx_job_executions_job_status", "job_id", "status"),
    )


class DataDeletionLog(Base, TimestampMixin):
    """Log of data deletion operations."""

    __tablename__ = "data_deletion_logs"

    # Primary key
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Deletion information
    table_name = Column(String(100), nullable=False, index=True)
    records_deleted = Column(Integer, nullable=False)
    deletion_criteria = Column(JSON)  # Store filter conditions used

    # Execution information
    executed_by = Column(String(100), default="system")
    execution_time_seconds = Column(Float)

    # Backup/recovery information
    backup_location = Column(String(500))  # Path to backup if created
    can_restore = Column(Boolean, default=False)

    # Indexes (with unique names to avoid conflicts)
    __table_args__ = (
        Index("idx_deletion_logs_table", "table_name"),
        Index("idx_deletion_logs_executed_by", "executed_by"),
    )


def get_default_jobs():
    """Get configuration for default job templates."""
    return [
        {
            "name": "Full Data Refresh",
            "description": "Complete refresh of all data from Chicago Open Data Portal",
            "job_type": JobType.FULL_REFRESH,
            "enabled": False,  # Default to off as requested
            "recurrence_type": RecurrenceType.ONCE,
            "config": {
                "endpoints": ["crashes", "people", "vehicles", "fatalities"],
                "force": True,
                "description": "Fetches all available data from all endpoints",
            },
            "timeout_minutes": 300,  # 5 hours for full refresh
            "max_retries": 1,
        },
        {
            "name": "Last 30 Days - Crash Data",
            "description": "Refresh crash data from the last 30 days",
            "job_type": JobType.LAST_30_DAYS_CRASHES,
            "enabled": True,
            "recurrence_type": RecurrenceType.DAILY,
            "config": {"endpoints": ["crashes"], "date_range_days": 30, "force": True},
            "timeout_minutes": 60,
            "max_retries": 3,
        },
        {
            "name": "Last 30 Days - People Data",
            "description": "Refresh people data from the last 30 days",
            "job_type": JobType.LAST_30_DAYS_PEOPLE,
            "enabled": True,
            "recurrence_type": RecurrenceType.DAILY,
            "config": {"endpoints": ["people"], "date_range_days": 30, "force": True},
            "timeout_minutes": 60,
            "max_retries": 3,
        },
        {
            "name": "Last 30 Days - Vehicle Data",
            "description": "Refresh vehicle data from the last 30 days",
            "job_type": JobType.LAST_30_DAYS_VEHICLES,
            "enabled": True,
            "recurrence_type": RecurrenceType.DAILY,
            "config": {"endpoints": ["vehicles"], "date_range_days": 30, "force": True},
            "timeout_minutes": 60,
            "max_retries": 3,
        },
        {
            "name": "Last 6 Months - Vision Zero Fatalities",
            "description": "Refresh Vision Zero fatality data from the last 6 months",
            "job_type": JobType.LAST_6_MONTHS_FATALITIES,
            "enabled": True,
            "recurrence_type": RecurrenceType.WEEKLY,
            "config": {
                "endpoints": ["fatalities"],
                "date_range_days": 180,  # ~6 months
                "force": True,
            },
            "timeout_minutes": 30,
            "max_retries": 3,
        },
    ]


def calculate_next_run(
    recurrence_type: RecurrenceType,
    cron_expression: str = None,
    last_run: datetime = None,
) -> datetime:
    """Calculate the next run time based on recurrence type."""
    now = datetime.now()

    if recurrence_type == RecurrenceType.ONCE:
        return None  # Run once, no next run

    base_time = last_run if last_run else now

    if recurrence_type == RecurrenceType.DAILY:
        return base_time + timedelta(days=1)
    elif recurrence_type == RecurrenceType.WEEKLY:
        return base_time + timedelta(weeks=1)
    elif recurrence_type == RecurrenceType.MONTHLY:
        # Add one month (approximate)
        return base_time + timedelta(days=30)
    elif recurrence_type == RecurrenceType.CUSTOM_CRON:
        # For custom cron, we'd need a cron parser library
        # For now, return daily as fallback
        return base_time + timedelta(days=1)

    return now + timedelta(hours=1)  # Default fallback

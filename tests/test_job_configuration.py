"""Tests for scheduler ownership and default job reconciliation."""

from datetime import datetime

from src.models.jobs import JobType, RecurrenceType, ScheduledJob, get_default_jobs
from src.services.job_service import JobService
from src.utils.config import Settings


def test_settings_enable_scheduler_by_default():
    """Scheduler ownership should default to enabled for local/dev runs."""
    runtime_settings = Settings()
    assert runtime_settings.job_scheduler_enabled is True


def test_default_jobs_disable_legacy_child_jobs():
    """Legacy people and vehicle daily jobs should no longer own scheduling."""
    default_jobs = {job["job_type"]: job for job in get_default_jobs()}

    assert default_jobs[JobType.LAST_30_DAYS_CORE_DATA]["enabled"] is True
    assert default_jobs[JobType.LAST_30_DAYS_CORE_DATA]["config"]["endpoints"] == [
        "crashes",
        "people",
        "vehicles",
    ]
    assert default_jobs[JobType.LAST_30_DAYS_PEOPLE]["enabled"] is False
    assert default_jobs[JobType.LAST_30_DAYS_VEHICLES]["enabled"] is False


def test_apply_default_job_template_promotes_legacy_crash_job():
    """Legacy crash-only daily jobs should be upgraded to the ordered core-data job."""
    service = JobService()
    job = ScheduledJob(
        id=2,
        name="Last 30 Days - Crash Data",
        description="old",
        job_type="last_30_days_crashes",
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        config={"endpoints": ["crashes"]},
        timeout_minutes=60,
        max_retries=3,
        last_run=datetime(2026, 4, 8, 3, 48, 19),
    )

    template = {
        "name": "Last 30 Days - Core Crash Data",
        "description": "Refresh crash, people, and vehicle data from the last 30 days in dependency order",
        "job_type": JobType.LAST_30_DAYS_CORE_DATA,
        "enabled": True,
        "recurrence_type": RecurrenceType.DAILY,
        "config": {"endpoints": ["crashes", "people", "vehicles"], "date_range_days": 30, "force": True},
        "timeout_minutes": 60,
        "max_retries": 3,
    }

    service._apply_default_job_template(job, template)

    assert job.job_type == JobType.LAST_30_DAYS_CORE_DATA
    assert job.enabled is True
    assert job.config["endpoints"] == ["crashes", "people", "vehicles"]
    assert job.next_run is not None


def test_apply_default_job_template_disables_legacy_child_job():
    """Legacy child jobs should be disabled and unscheduled."""
    service = JobService()
    job = ScheduledJob(
        id=3,
        name="Last 30 Days - People Data",
        description="old",
        job_type=JobType.LAST_30_DAYS_PEOPLE,
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        config={"endpoints": ["people"]},
        timeout_minutes=60,
        max_retries=3,
        next_run=datetime(2026, 4, 9, 3, 48, 46),
        last_run=datetime(2026, 4, 8, 3, 48, 46),
    )

    template = {
        "name": "Last 30 Days - People Data",
        "description": "Refresh people data from the last 30 days",
        "job_type": JobType.LAST_30_DAYS_PEOPLE,
        "enabled": False,
        "recurrence_type": RecurrenceType.DAILY,
        "config": {"endpoints": ["people"], "date_range_days": 30, "force": True},
        "timeout_minutes": 60,
        "max_retries": 3,
    }

    service._apply_default_job_template(job, template)

    assert job.enabled is False
    assert job.next_run is None


def test_build_sync_params_for_core_data_preserves_dependency_order():
    """Core-data jobs should execute crashes before people before vehicles."""
    service = JobService()

    params = service._build_sync_params(
        JobType.LAST_30_DAYS_CORE_DATA,
        {"endpoints": ["crashes", "people", "vehicles"], "force": True},
    )

    assert params["endpoints"] == ["crashes", "people", "vehicles"]
    assert params["force"] is True
    assert params["start_date"] is not None
    assert params["end_date"] is not None

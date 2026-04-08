"""Tests for scheduler ownership and default job reconciliation."""

from datetime import datetime, timedelta

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


def test_reconcile_default_job_promotes_legacy_crash_job_without_resetting_schedule():
    """Legacy crash jobs should migrate without overwriting operator-managed settings."""
    service = JobService()
    existing_next_run = datetime(2026, 4, 15, 3, 48, 19)
    job = ScheduledJob(
        id=2,
        name="Last 30 Days - Crash Data",
        description="old",
        job_type=service.LEGACY_CORE_JOB_TYPE,
        enabled=True,
        recurrence_type=RecurrenceType.WEEKLY,
        config={
            "endpoints": ["crashes"],
            "date_range_days": 14,
            "force": False,
            "custom_filter": "north_side",
        },
        timeout_minutes=90,
        max_retries=7,
        next_run=existing_next_run,
        last_run=datetime(2026, 4, 8, 3, 48, 19),
    )

    template = {
        "name": "Last 30 Days - Core Crash Data",
        "description": (
            "Refresh crash, people, and vehicle data from the last 30 days "
            "in dependency order"
        ),
        "job_type": JobType.LAST_30_DAYS_CORE_DATA,
        "enabled": True,
        "recurrence_type": RecurrenceType.DAILY,
        "config": {
            "endpoints": ["crashes", "people", "vehicles"],
            "date_range_days": 30,
            "force": True,
        },
        "timeout_minutes": 60,
        "max_retries": 3,
    }

    service._reconcile_default_job(job, template)

    assert job.name == template["name"]
    assert job.job_type == JobType.LAST_30_DAYS_CORE_DATA
    assert job.enabled is True
    assert job.recurrence_type == RecurrenceType.WEEKLY
    assert job.timeout_minutes == 90
    assert job.max_retries == 7
    assert job.config["endpoints"] == ["crashes", "people", "vehicles"]
    assert job.config["date_range_days"] == 14
    assert job.config["force"] is False
    assert job.config["custom_filter"] == "north_side"
    assert job.next_run == existing_next_run


def test_reconcile_default_job_initializes_missing_next_run_for_legacy_core_job():
    """Legacy core job migration should fill next_run once using the last run time."""
    service = JobService()
    last_run = datetime(2026, 4, 8, 3, 48, 19)
    job = ScheduledJob(
        id=2,
        name="Last 30 Days - Crash Data",
        description="Refresh crash data from the last 30 days",
        job_type=service.LEGACY_CORE_JOB_TYPE,
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        config={"endpoints": ["crashes"]},
        timeout_minutes=60,
        max_retries=3,
        last_run=last_run,
        next_run=None,
    )

    template = {
        "name": "Last 30 Days - Core Crash Data",
        "description": (
            "Refresh crash, people, and vehicle data from the last 30 days "
            "in dependency order"
        ),
        "job_type": JobType.LAST_30_DAYS_CORE_DATA,
        "enabled": True,
        "recurrence_type": RecurrenceType.DAILY,
        "config": {
            "endpoints": ["crashes", "people", "vehicles"],
            "date_range_days": 30,
            "force": True,
        },
        "timeout_minutes": 60,
        "max_retries": 3,
    }

    service._reconcile_default_job(job, template)

    assert job.next_run == last_run + timedelta(days=1)


def test_reconcile_default_job_disables_system_legacy_child_job_once():
    """System-owned legacy child jobs should be disabled and marked as migrated."""
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
        created_by="system",
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

    service._reconcile_default_job(job, template)

    assert job.enabled is False
    assert job.next_run is None
    assert job.created_by == service.DEFAULT_JOB_MIGRATION_MARKER


def test_reconcile_default_job_preserves_operator_managed_legacy_child_job():
    """Operator-managed legacy child jobs should not be disabled on restart."""
    service = JobService()
    existing_next_run = datetime(2026, 4, 9, 3, 48, 46)
    job = ScheduledJob(
        id=3,
        name="Last 30 Days - People Data",
        description="Custom people replay",
        job_type=JobType.LAST_30_DAYS_PEOPLE,
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        config={"endpoints": ["people"], "date_range_days": 7},
        timeout_minutes=45,
        max_retries=5,
        next_run=existing_next_run,
        last_run=datetime(2026, 4, 8, 3, 48, 46),
        created_by="admin",
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

    service._reconcile_default_job(job, template)

    assert job.enabled is True
    assert job.next_run == existing_next_run
    assert job.created_by == "admin"
    assert job.config["date_range_days"] == 7


def test_reconcile_default_job_leaves_existing_core_job_untouched():
    """Already-migrated core jobs should keep their persisted schedule state."""
    service = JobService()
    existing_next_run = datetime(2026, 4, 9, 4, 0, 0)
    job = ScheduledJob(
        id=2,
        name="Custom Core Job",
        description="Operator-tuned description",
        job_type=JobType.LAST_30_DAYS_CORE_DATA,
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        config={
            "endpoints": ["crashes", "people", "vehicles"],
            "date_range_days": 7,
            "force": False,
        },
        timeout_minutes=30,
        max_retries=1,
        next_run=existing_next_run,
        last_run=None,
        created_by="admin",
    )

    template = {
        "name": "Last 30 Days - Core Crash Data",
        "description": (
            "Refresh crash, people, and vehicle data from the last 30 days "
            "in dependency order"
        ),
        "job_type": JobType.LAST_30_DAYS_CORE_DATA,
        "enabled": True,
        "recurrence_type": RecurrenceType.DAILY,
        "config": {
            "endpoints": ["crashes", "people", "vehicles"],
            "date_range_days": 30,
            "force": True,
        },
        "timeout_minutes": 60,
        "max_retries": 3,
    }

    service._reconcile_default_job(job, template)

    assert job.name == "Custom Core Job"
    assert job.description == "Operator-tuned description"
    assert job.timeout_minutes == 30
    assert job.max_retries == 1
    assert job.next_run == existing_next_run
    assert job.config["date_range_days"] == 7


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

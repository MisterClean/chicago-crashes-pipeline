"""Regression tests for upstream child-record integrity during syncs."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.crashes import CrashPerson, CrashVehicle
from src.models.jobs import JobExecution, JobStatus, RecurrenceType, ScheduledJob
from src.services.database_service import DatabaseService
from src.services.job_service import JobService


@pytest.mark.parametrize(
    ("method_name", "valid_record", "orphan_record", "model"),
    [
        (
            "upsert_person_records",
            {"crash_record_id": "VALID", "person_id": "P1"},
            {"crash_record_id": "ORPHAN", "person_id": "P2"},
            CrashPerson,
        ),
        (
            "upsert_vehicle_records",
            {
                "crash_record_id": "VALID",
                "crash_unit_id": "U1",
                "unit_no": 1,
            },
            {
                "crash_record_id": "ORPHAN",
                "crash_unit_id": "U2",
                "unit_no": 2,
            },
            CrashVehicle,
        ),
    ],
)
def test_child_upserts_skip_only_records_with_missing_parents(
    method_name, valid_record, orphan_record, model
):
    session = MagicMock()
    session.scalars.return_value.all.return_value = ["VALID"]
    session.get.return_value = None

    service = DatabaseService()
    service.session_factory = MagicMock(return_value=session)

    with patch("src.services.database_service.logger") as logger:
        result = getattr(service, method_name)([valid_record, orphan_record])

    assert result == {"inserted": 1, "updated": 0, "skipped": 1}
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
    session.add.assert_called_once()

    inserted = session.add.call_args.args[0]
    assert isinstance(inserted, model)
    assert inserted.crash_record_id == "VALID"
    logger.warning.assert_called_once_with(
        "Skipped child records with missing crash parents",
        model=model.__tablename__,
        orphaned_records=1,
        orphaned_crash_ids=1,
        sample_crash_ids=["ORPHAN"],
    )


@pytest.mark.asyncio
async def test_failed_recurring_job_advances_next_run():
    previous_next_run = datetime(2026, 8, 9, 12, 0, 0)
    job = ScheduledJob(
        id=2,
        name="Daily core sync",
        job_type="last_30_days_core_data",
        enabled=True,
        recurrence_type=RecurrenceType.DAILY,
        next_run=previous_next_run,
        config={"endpoints": ["crashes", "people", "vehicles"]},
    )
    execution = JobExecution(
        id=10,
        execution_id="exec-10",
        job_id=job.id,
        status=JobStatus.PENDING,
        execution_context={},
    )
    execution.job = job

    session = MagicMock()
    query = session.query.return_value
    query.options.return_value.filter_by.return_value.first.return_value = execution

    service = JobService()
    service.get_session = MagicMock(return_value=session)

    with (
        patch("src.services.job_service.SyncService") as sync_service_cls,
        patch.object(service, "_merge_execution_context"),
        patch.object(service, "_append_execution_log"),
    ):
        sync_service_cls.return_value.sync = AsyncMock(
            side_effect=RuntimeError("upstream unavailable")
        )
        await service._run_job_execution(execution.id, job.config)

    assert execution.status == JobStatus.FAILED
    assert job.next_run > execution.completed_at
    assert job.next_run > previous_next_run
    session.close.assert_called_once_with()

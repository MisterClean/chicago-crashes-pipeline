"""Real PostgreSQL tests for claims, retries and atomic scheduling."""

import asyncio
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.models.jobs import JobExecution, JobType, ScheduledJob
from src.services import job_queue, job_service


@pytest.fixture
def queue_db(monkeypatch):
    url = os.getenv("QUEUE_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("QUEUE_TEST_DATABASE_URL must point to disposable PostgreSQL")
    admin = create_engine(url)
    schema = "queue_test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema},public"}
    )
    ScheduledJob.__table__.create(engine)
    JobExecution.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(job_queue, "SessionLocal", sessions)
    monkeypatch.setattr(job_service, "SessionLocal", sessions)
    with sessions.begin() as session:
        job = ScheduledJob(
            name="test",
            job_type="incremental",
            enabled=True,
            recurrence_type="daily",
            timeout_minutes=2,
            max_retries=1,
            retry_delay_minutes=5,
            next_run=datetime.utcnow() - timedelta(minutes=1),
            config={"endpoints": ["crashes"]},
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield sessions, engine, job_id
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def enqueue(job_id, **kwargs):
    return asyncio.run(job_service.JobService().execute_job(job_id, **kwargs))


def test_enqueue_is_durable_without_starting_a_task(queue_db):
    sessions, _, job_id = queue_db
    identifier = enqueue(job_id)
    with sessions() as session:
        execution = session.query(JobExecution).one()
        assert execution.execution_id == identifier
        assert execution.status == "pending"
        assert execution.started_at is None


def test_concurrent_enqueue_has_one_winner_even_when_forced(queue_db):
    sessions, _, job_id = queue_db

    def attempt():
        try:
            return enqueue(job_id, force=True)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(value is not None for value in results) == 1
    with sessions() as session:
        assert session.query(JobExecution).count() == 1


def test_claim_fences_owners_and_delays_retry(queue_db):
    sessions, _, job_id = queue_db
    enqueue(job_id)
    execution_id, timeout = job_queue.claim_execution("owner")
    assert timeout == 120
    assert job_queue.claim_execution("other") is None
    assert not job_queue.renew_execution(execution_id, "other")
    assert job_queue.renew_execution(execution_id, "owner")
    job_queue.finish_attempt(execution_id, "owner", "timeout")
    assert job_queue.claim_execution("other") is None
    with sessions() as session:
        execution = session.get(JobExecution, execution_id)
        assert execution.status == "pending"
        assert execution.retry_count == 1
        assert execution.error_message == "timeout"
        assert execution.available_at > datetime.utcnow()


@pytest.mark.parametrize("abandoned_status", ["running", "failed"])
def test_abandoned_attempt_is_recovered_and_old_owner_cannot_finish(
    queue_db, abandoned_status
):
    sessions, _, job_id = queue_db
    enqueue(job_id)
    execution_id, _ = job_queue.claim_execution("old")
    with sessions.begin() as session:
        row = session.get(JobExecution, execution_id)
        row.status = abandoned_status
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert job_queue.claim_execution("new")[0] == execution_id
    job_queue.finish_attempt(execution_id, "old", "stale")
    with sessions() as session:
        row = session.get(JobExecution, execution_id)
        assert row.status == "running"
        assert row.lease_owner == "new"
    job_queue.finish_attempt(execution_id, "new", "second failure")
    with sessions() as session:
        assert session.get(JobExecution, execution_id).status == "failed"
    assert job_queue.claim_execution("third") is None


def test_stale_scheduled_occurrence_is_not_enqueued_twice(queue_db):
    sessions, _, job_id = queue_db
    enqueue(job_id, scheduled=True)
    with sessions.begin() as session:
        row = session.query(JobExecution).one()
        row.status = "completed"
    with pytest.raises(ValueError, match="no longer due"):
        enqueue(job_id, scheduled=True)


def test_full_and_incremental_parameters_have_no_event_date_filter():
    service = job_service.JobService()
    assert service._build_sync_params(JobType.FULL_REFRESH, {})["mode"] == "full"
    result = service._build_sync_params(JobType.INCREMENTAL, {})
    assert result["mode"] == "incremental"
    assert "start_date" not in result


def test_additive_migration_upgrades_existing_job_table(queue_db, monkeypatch):
    _, engine, _ = queue_db
    path = Path("migrations/versions/b73a91d8e402_durable_workers_and_exports.py")
    spec = importlib.util.spec_from_file_location("worker_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn:
        for column in ("lease_owner", "lease_expires_at", "available_at"):
            conn.execute(text(f'ALTER TABLE job_executions DROP COLUMN "{column}"'))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()  # API create_all / deployment retries must be safe.
        columns = {c["name"] for c in inspect(conn).get_columns("job_executions")}
        assert {"lease_owner", "lease_expires_at", "available_at"} <= columns
        assert "export_jobs" in inspect(conn).get_table_names()


def test_expired_child_cannot_start_or_mark_replacement_failed(queue_db):
    sessions, _, job_id = queue_db
    enqueue(job_id)
    execution_id, _ = job_queue.claim_execution("stale")
    with sessions.begin() as session:
        execution = session.get(JobExecution, execution_id)
        execution.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    asyncio.run(job_service.JobService()._run_job_execution(execution_id, {}, "stale"))
    with sessions() as session:
        execution = session.get(JobExecution, execution_id)
        assert execution.status == "running"
        assert execution.error_message is None
    job_queue.claim_execution("replacement")
    asyncio.run(job_service.JobService()._run_job_execution(execution_id, {}, "stale"))
    with sessions() as session:
        execution = session.get(JobExecution, execution_id)
        assert execution.lease_owner == "replacement"
        assert execution.status == "running"


@pytest.mark.parametrize("fails", [False, True])
def test_owned_child_persists_terminal_state(queue_db, monkeypatch, fails):
    from unittest.mock import AsyncMock

    from src.services.sync_service import SyncResult

    sessions, _, job_id = queue_db
    enqueue(job_id)
    execution_id, _ = job_queue.claim_execution("owner")
    sync = AsyncMock(return_value=SyncResult(started_at=datetime.utcnow()))
    if fails:
        sync.side_effect = RuntimeError("test source failure")
    monkeypatch.setattr(job_service.SyncService, "sync", sync)
    asyncio.run(job_service.JobService()._run_job_execution(
        execution_id, {"endpoints": ["crashes"]}, "owner"
    ))
    with sessions() as session:
        execution = session.get(JobExecution, execution_id)
        assert execution.status == ("failed" if fails else "completed")
        assert execution.completed_at is not None

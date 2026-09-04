"""Postgres-backed execution claims, leases and bounded retries."""

from datetime import datetime, timedelta

from sqlalchemy import or_

from src.models.base import SessionLocal
from src.models.jobs import JobExecution, JobStatus, ScheduledJob

LEASE_SECONDS = 90


def claim_execution(owner: str) -> tuple[int, int] | None:
    """Atomically claim pending work; reclaim abandoned work within retry budget."""
    now = datetime.utcnow()
    with SessionLocal.begin() as session:
        execution = (
            session.query(JobExecution)
            .filter(
                or_(
                    (JobExecution.status == JobStatus.PENDING)
                    & or_(
                        JobExecution.available_at <= now,
                        JobExecution.available_at.is_(None),
                    ),
                    (JobExecution.status.in_([JobStatus.RUNNING, JobStatus.FAILED]))
                    & or_(
                        JobExecution.lease_expires_at < now,
                        (
                            JobExecution.lease_expires_at.is_(None)
                            & (JobExecution.status == JobStatus.RUNNING)
                        ),
                    ),
                )
            )
            .order_by(JobExecution.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if execution is None:
            return None
        job = session.get(ScheduledJob, execution.job_id)
        if execution.status in {JobStatus.RUNNING, JobStatus.FAILED}:
            if execution.retry_count >= job.max_retries:
                execution.status = JobStatus.FAILED
                execution.error_message = "Worker lease expired; retry budget exhausted"
                execution.completed_at = now
                execution.lease_owner = None
                execution.lease_expires_at = None
                return None
            execution.retry_count += 1
        execution.status = JobStatus.RUNNING
        execution.started_at = now
        execution.completed_at = None
        execution.error_message = None
        execution.lease_owner = owner
        execution.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        return execution.id, job.timeout_minutes * 60


def renew_execution(execution_id: int, owner: str) -> bool:
    now = datetime.utcnow()
    with SessionLocal.begin() as session:
        return (
            session.query(JobExecution)
            .filter(
                JobExecution.id == execution_id,
                JobExecution.lease_owner == owner,
                JobExecution.status == JobStatus.RUNNING,
                JobExecution.lease_expires_at > now,
            )
            .update({"lease_expires_at": now + timedelta(seconds=LEASE_SECONDS)})
            == 1
        )


def owns_execution(execution_id: int, owner: str) -> bool:
    with SessionLocal() as session:
        return (
            session.query(JobExecution.id)
            .filter(
                JobExecution.id == execution_id,
                JobExecution.lease_owner == owner,
                JobExecution.lease_expires_at > datetime.utcnow(),
            )
            .first()
            is not None
        )


def finish_attempt(execution_id: int, owner: str, error: str | None = None) -> None:
    """Release ownership, scheduling a delayed retry when an attempt failed."""
    now = datetime.utcnow()
    with SessionLocal.begin() as session:
        execution = (
            session.query(JobExecution)
            .filter_by(id=execution_id, lease_owner=owner)
            .with_for_update()
            .first()
        )
        if execution is None:
            return
        job = session.get(ScheduledJob, execution.job_id)
        if execution.status == JobStatus.RUNNING:
            execution.status = JobStatus.FAILED
            execution.error_message = (
                error or "Worker exited without completing execution"
            )
            execution.completed_at = now
        if (
            execution.status == JobStatus.FAILED
            and execution.retry_count < job.max_retries
        ):
            execution.retry_count += 1
            execution.status = JobStatus.PENDING
            execution.available_at = now + timedelta(minutes=job.retry_delay_minutes)
            execution.completed_at = None
        execution.lease_owner = None
        execution.lease_expires_at = None

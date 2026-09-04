"""Dedicated worker: python -m src.worker (API processes never execute ETL)."""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from src.models.base import SessionLocal
from src.models.jobs import JobExecution
from src.services.job_queue import (
    claim_execution,
    finish_attempt,
    owns_execution,
    renew_execution,
)
from src.services.job_scheduler import JobScheduler
from src.services.job_service import JobService
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def run_execution(execution_id: int, owner: str) -> None:
    """Child watchdog fences orphaned work even if its supervisor crashes."""
    stop = threading.Event()

    def watch_lease() -> None:
        while not stop.wait(5):
            try:
                if owns_execution(execution_id, owner):
                    continue
            except Exception:
                logger.exception("Unable to verify execution lease")
            # The process may be inside synchronous COPY/merge. Exiting closes
            # its connections and rolls back open transactions immediately.
            os._exit(75)

    if not owns_execution(execution_id, owner):
        raise RuntimeError("Execution lease is not owned by this worker")
    with SessionLocal() as session:
        execution = session.get(JobExecution, execution_id)
        config = (execution.execution_context or {}).get("config", {})
    threading.Thread(target=watch_lease, daemon=True).start()
    try:
        asyncio.run(JobService()._run_job_execution(execution_id, config, owner))
    finally:
        stop.set()


def supervise_execution(
    execution_id: int, timeout: int, owner: str, stopping: threading.Event
) -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.worker",
            "--execution",
            str(execution_id),
            "--owner",
            owner,
        ],
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    error = None
    try:
        while child.poll() is None:
            if stopping.wait(5):
                error = "Worker shutting down"
                break
            if time.monotonic() >= deadline:
                error = "Execution exceeded configured timeout"
                break
            if not renew_execution(execution_id, owner):
                # Completed jobs need no heartbeat; allow the child to finish
                # its final logging before deciding ownership was lost.
                child.wait(timeout=10)
                break
    except Exception as exc:
        error = str(exc)
        logger.exception("Execution supervision failed")
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        finish_attempt(execution_id, owner, error)


def run_worker(lane: str = "all", once: bool = False) -> None:
    """Separate lanes can isolate long ingestion from interactive export jobs."""
    # Import here only because export support is optional for ingestion workers.
    from src.services.export_service import (
        cleanup_expired_exports,
        process_one_export_job,
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    owner = uuid4().hex
    scheduler = JobScheduler()
    if lane in {"all", "ingestion"}:
        JobService().initialize_default_jobs()
    next_schedule = next_cleanup = 0.0
    while not stop.is_set():
        try:
            if lane in {"all", "ingestion"}:
                if time.monotonic() >= next_schedule:
                    asyncio.run(scheduler._check_and_execute_due_jobs())
                    next_schedule = time.monotonic() + 60
                claim = claim_execution(owner)
                if claim is not None:
                    supervise_execution(*claim, owner, stop)
            if lane in {"all", "exports"}:
                process_one_export_job()
                if time.monotonic() >= next_cleanup:
                    cleanup_expired_exports()
                    next_cleanup = time.monotonic() + 3600
        except Exception:
            logger.exception("Worker iteration failed; retrying after delay")
        if once:
            break
        stop.wait(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=int)
    parser.add_argument("--owner")
    parser.add_argument(
        "--lane", choices=["all", "ingestion", "exports"], default="all"
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    setup_logging("worker", "INFO")
    if args.execution is not None:
        if args.owner is None:
            parser.error("--owner is required with --execution")
        run_execution(args.execution, args.owner)
    else:
        run_worker(args.lane, args.once)


if __name__ == "__main__":
    main()

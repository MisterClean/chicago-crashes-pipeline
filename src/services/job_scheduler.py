"""Job scheduler service for running scheduled jobs automatically."""
import asyncio
import signal
from datetime import datetime, timedelta
from typing import List, Optional

from src.models.jobs import JobExecution, JobStatus, ScheduledJob
from src.services.job_service import JobService
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class JobScheduler:
    """Background service for executing scheduled jobs."""

    def __init__(self, check_interval: int = 60):
        """
        Initialize job scheduler.

        Args:
            check_interval: How often to check for due jobs (in seconds)
        """
        self.check_interval = check_interval
        self.job_service = JobService()
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the job scheduler."""
        if self.running:
            logger.warning("Job scheduler is already running")
            return

        self.running = True
        logger.info(
            f"Starting job scheduler with {self.check_interval}s check interval"
        )

        # Initialize default jobs if needed
        try:
            self.job_service.initialize_default_jobs()
        except Exception as e:
            logger.error(f"Failed to initialize default jobs: {str(e)}")

        # Start the main scheduler loop
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        """Stop the job scheduler."""
        if not self.running:
            return

        logger.info("Stopping job scheduler...")
        self.running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Job scheduler stopped")

    async def _scheduler_loop(self):
        """Main scheduler loop that checks for and executes due jobs."""
        while self.running:
            try:
                await self._check_and_execute_due_jobs()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
                # Continue running even if there's an error
                await asyncio.sleep(self.check_interval)

    async def _check_and_execute_due_jobs(self):
        """Check for jobs that are due for execution and execute them."""
        try:
            due_jobs = self.job_service.get_jobs_due_for_execution()

            if not due_jobs:
                logger.debug("No jobs due for execution")
                return

            logger.info(f"Found {len(due_jobs)} jobs due for execution")

            for job in due_jobs:
                try:
                    await self._execute_scheduled_job(job)
                except Exception as e:
                    logger.error(
                        f"Failed to execute job {job.name} (ID: {job.id}): {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Error checking for due jobs: {str(e)}")

    async def _execute_scheduled_job(self, job: ScheduledJob):
        """Execute a single scheduled job."""
        logger.info(f"Executing scheduled job: {job.name} (ID: {job.id})")

        try:
            # Check if job is already running
            running_executions = self.job_service.get_job_executions(
                job_id=job.id, limit=1
            )
            if running_executions and running_executions[0].status == JobStatus.RUNNING:
                logger.warning(f"Job {job.name} is already running, skipping execution")
                return

            # Execute the job
            execution_id = await self.job_service.execute_job(
                job_id=job.id, force=False  # Don't force scheduled executions
            )

            logger.info(
                f"Started execution {execution_id} for scheduled job {job.name}"
            )

        except Exception as e:
            logger.error(f"Failed to start execution for job {job.name}: {str(e)}")


class JobSchedulerManager:
    """Manager for controlling the job scheduler as a service."""

    def __init__(self):
        self.scheduler: Optional[JobScheduler] = None

    async def start_scheduler(self, check_interval: int = 60):
        """Start the job scheduler service."""
        if self.scheduler and self.scheduler.running:
            logger.warning("Job scheduler is already running")
            return

        self.scheduler = JobScheduler(check_interval=check_interval)
        await self.scheduler.start()

        # Set up signal handlers for graceful shutdown
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._signal_handler)
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("Job scheduler started successfully")

    async def stop_scheduler(self):
        """Stop the job scheduler service."""
        if self.scheduler:
            await self.scheduler.stop()
            self.scheduler = None

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down job scheduler...")
        if self.scheduler:
            asyncio.create_task(self.scheduler.stop())

    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self.scheduler is not None and self.scheduler.running


# Global scheduler manager instance
scheduler_manager = JobSchedulerManager()


async def start_job_scheduler():
    """Start the global job scheduler."""
    check_interval = getattr(settings, "job_scheduler_interval", 60)
    await scheduler_manager.start_scheduler(check_interval=check_interval)


async def stop_job_scheduler():
    """Stop the global job scheduler."""
    await scheduler_manager.stop_scheduler()


def is_scheduler_running() -> bool:
    """Check if the global job scheduler is running."""
    return scheduler_manager.is_running()


if __name__ == "__main__":
    """Run the job scheduler as a standalone service."""

    async def main():
        try:
            await start_job_scheduler()

            # Keep running until interrupted
            while scheduler_manager.is_running():
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}")
        finally:
            await stop_job_scheduler()

    # Run the scheduler
    asyncio.run(main())

"""Job management service for handling scheduled jobs and executions."""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from models.jobs import (
    ScheduledJob, JobExecution, DataDeletionLog, 
    JobStatus, JobType, RecurrenceType, 
    get_default_jobs, calculate_next_run
)
from models.base import SessionLocal, get_db
from models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from services.database_service import DatabaseService
from etl.soda_client import SODAClient
from validators.data_sanitizer import DataSanitizer
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)


class JobService:
    """Service for managing scheduled jobs and executions."""
    
    def __init__(self):
        self.db_service = DatabaseService()
        
    def get_session(self) -> Session:
        """Get database session."""
        return SessionLocal()
    
    def initialize_default_jobs(self) -> List[Dict[str, Any]]:
        """Initialize default job templates if they don't exist."""
        session = self.get_session()
        created_jobs = []
        
        try:
            default_jobs = get_default_jobs()
            
            for job_config in default_jobs:
                # Check if job already exists
                existing = session.query(ScheduledJob).filter_by(
                    job_type=job_config["job_type"]
                ).first()
                
                if not existing:
                    next_run = None
                    if job_config.get("enabled") and job_config["recurrence_type"] != RecurrenceType.ONCE:
                        next_run = calculate_next_run(
                            RecurrenceType(job_config["recurrence_type"])
                        )
                    
                    job = ScheduledJob(
                        name=job_config["name"],
                        description=job_config["description"],
                        job_type=job_config["job_type"],
                        enabled=job_config["enabled"],
                        config=job_config["config"],
                        recurrence_type=job_config["recurrence_type"],
                        timeout_minutes=job_config["timeout_minutes"],
                        max_retries=job_config["max_retries"],
                        next_run=next_run
                    )
                    
                    session.add(job)
                    session.flush()
                    created_jobs.append({
                        "id": job.id,
                        "name": job.name,
                        "job_type": job.job_type
                    })
            
            session.commit()
            logger.info(f"Initialized {len(created_jobs)} default jobs")
            return created_jobs
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to initialize default jobs: {str(e)}")
            raise
        finally:
            session.close()
    
    def create_job(self, job_data: Dict[str, Any], created_by: str = "admin") -> ScheduledJob:
        """Create a new scheduled job."""
        session = self.get_session()
        
        try:
            # Calculate next run time
            next_run = None
            if job_data.get("enabled") and job_data["recurrence_type"] != RecurrenceType.ONCE:
                next_run = calculate_next_run(
                    RecurrenceType(job_data["recurrence_type"]),
                    job_data.get("cron_expression")
                )
            
            job = ScheduledJob(
                name=job_data["name"],
                description=job_data.get("description"),
                job_type=job_data["job_type"],
                enabled=job_data.get("enabled", True),
                config=job_data["config"],
                recurrence_type=job_data["recurrence_type"],
                cron_expression=job_data.get("cron_expression"),
                timeout_minutes=job_data.get("timeout_minutes", 60),
                max_retries=job_data.get("max_retries", 3),
                retry_delay_minutes=job_data.get("retry_delay_minutes", 5),
                created_by=created_by,
                next_run=next_run
            )
            
            session.add(job)
            session.commit()
            session.refresh(job)
            
            logger.info(f"Created job: {job.name} (ID: {job.id})")
            return job
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create job: {str(e)}")
            raise
        finally:
            session.close()
    
    def update_job(self, job_id: int, updates: Dict[str, Any]) -> Optional[ScheduledJob]:
        """Update an existing job."""
        session = self.get_session()
        
        try:
            job = session.query(ScheduledJob).filter_by(id=job_id).first()
            if not job:
                return None
            
            # Update fields
            for field, value in updates.items():
                if hasattr(job, field):
                    setattr(job, field, value)
            
            # Recalculate next run if scheduling changed
            if "recurrence_type" in updates or "enabled" in updates:
                if job.enabled and job.recurrence_type != RecurrenceType.ONCE:
                    job.next_run = calculate_next_run(
                        RecurrenceType(job.recurrence_type),
                        job.cron_expression,
                        job.last_run
                    )
                else:
                    job.next_run = None
            
            session.commit()
            session.refresh(job)
            
            logger.info(f"Updated job: {job.name} (ID: {job.id})")
            return job
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update job {job_id}: {str(e)}")
            raise
        finally:
            session.close()
    
    def delete_job(self, job_id: int) -> bool:
        """Delete a job and its execution history."""
        session = self.get_session()
        
        try:
            job = session.query(ScheduledJob).filter_by(id=job_id).first()
            if not job:
                return False
            
            job_name = job.name
            session.delete(job)
            session.commit()
            
            logger.info(f"Deleted job: {job_name} (ID: {job_id})")
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete job {job_id}: {str(e)}")
            raise
        finally:
            session.close()
    
    def get_job(self, job_id: int) -> Optional[ScheduledJob]:
        """Get a job by ID."""
        session = self.get_session()
        try:
            return session.query(ScheduledJob).filter_by(id=job_id).first()
        finally:
            session.close()
    
    def get_jobs(self, enabled_only: bool = False) -> List[ScheduledJob]:
        """Get all jobs."""
        session = self.get_session()
        try:
            query = session.query(ScheduledJob).order_by(ScheduledJob.name)
            if enabled_only:
                query = query.filter_by(enabled=True)
            return query.all()
        finally:
            session.close()
    
    def get_jobs_due_for_execution(self) -> List[ScheduledJob]:
        """Get jobs that are due for execution."""
        session = self.get_session()
        try:
            now = datetime.now()
            return session.query(ScheduledJob).filter(
                and_(
                    ScheduledJob.enabled == True,
                    ScheduledJob.next_run <= now,
                    ScheduledJob.next_run.isnot(None)
                )
            ).all()
        finally:
            session.close()
    
    async def execute_job(self, job_id: int, force: bool = False, override_config: Dict[str, Any] = None) -> str:
        """Execute a job manually."""
        session = self.get_session()
        
        try:
            job = session.query(ScheduledJob).filter_by(id=job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            # Check if job is already running
            running_execution = session.query(JobExecution).filter(
                and_(
                    JobExecution.job_id == job_id,
                    JobExecution.status == JobStatus.RUNNING
                )
            ).first()
            
            if running_execution and not force:
                raise ValueError(f"Job {job_id} is already running")
            
            # Create execution record
            execution_id = f"exec_{job_id}_{int(datetime.now().timestamp())}"
            config = override_config or job.config
            
            execution = JobExecution(
                execution_id=execution_id,
                job_id=job_id,
                status=JobStatus.PENDING,
                execution_context={
                    "manual": True,
                    "force": force,
                    "config": config
                }
            )
            
            session.add(execution)
            session.commit()
            session.refresh(execution)
            
            # Start background execution
            asyncio.create_task(self._run_job_execution(execution.id, config))
            
            logger.info(f"Started execution {execution_id} for job {job.name}")
            return execution_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to execute job {job_id}: {str(e)}")
            raise
        finally:
            session.close()
    
    async def _run_job_execution(self, execution_id: int, config: Dict[str, Any]):
        """Run job execution in background."""
        session = self.get_session()
        
        try:
            execution = session.query(JobExecution).filter_by(id=execution_id).first()
            if not execution:
                logger.error(f"Execution {execution_id} not found")
                return
            
            job = execution.job
            start_time = datetime.now()
            
            # Update execution status
            execution.status = JobStatus.RUNNING
            execution.started_at = start_time
            session.commit()
            
            # Build sync parameters based on job type and config
            sync_params = self._build_sync_params(job.job_type, config)
            
            # Execute the sync operation
            client = SODAClient()
            sanitizer = DataSanitizer()
            
            total_records = 0
            total_inserted = 0
            total_updated = 0
            
            for endpoint_name in sync_params["endpoints"]:
                endpoint_url = settings.api.endpoints[endpoint_name]
                
                # Fetch records
                records = await client.fetch_all_records(
                    endpoint=endpoint_url,
                    batch_size=50000,
                    start_date=sync_params.get("start_date"),
                    end_date=sync_params.get("end_date"),
                    date_field="crash_date",
                    show_progress=False
                )
                
                if not records:
                    continue
                
                # Process and save records
                if endpoint_name == "crashes":
                    processed_records = [sanitizer.sanitize_crash_record(r) for r in records]
                    result = self.db_service.insert_crash_records(processed_records)
                elif endpoint_name == "people":
                    processed_records = [sanitizer.sanitize_person_record(r) for r in records]
                    result = self.db_service.insert_person_records(processed_records)
                elif endpoint_name == "vehicles":
                    processed_records = [sanitizer.sanitize_vehicle_record(r) for r in records]
                    result = self.db_service.insert_vehicle_records(processed_records)
                elif endpoint_name == "fatalities":
                    processed_records = [sanitizer.sanitize_fatality_record(r) for r in records]
                    processed_records = sanitizer.remove_duplicates(processed_records, 'person_id')
                    result = self.db_service.insert_fatality_records(processed_records)
                else:
                    result = {"inserted": 0, "updated": 0, "skipped": len(records)}
                
                total_records += len(processed_records)
                total_inserted += result.get("inserted", 0)
                total_updated += result.get("updated", 0)
            
            # Update execution as completed
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            execution.status = JobStatus.COMPLETED
            execution.completed_at = end_time
            execution.duration_seconds = duration
            execution.records_processed = total_records
            execution.records_inserted = total_inserted
            execution.records_updated = total_updated
            
            # Update job's last run and next run
            job.last_run = end_time
            if job.enabled and job.recurrence_type != RecurrenceType.ONCE:
                job.next_run = calculate_next_run(
                    RecurrenceType(job.recurrence_type),
                    job.cron_expression,
                    end_time
                )
            
            session.commit()
            
            logger.info(
                f"Job execution completed",
                execution_id=execution.execution_id,
                job_name=job.name,
                duration=duration,
                records_processed=total_records
            )
            
        except Exception as e:
            # Update execution as failed
            execution.status = JobStatus.FAILED
            execution.completed_at = datetime.now()
            execution.error_message = str(e)
            execution.error_details = {"exception": type(e).__name__}
            
            if execution.started_at:
                duration = int((datetime.now() - execution.started_at).total_seconds())
                execution.duration_seconds = duration
            
            session.commit()
            
            logger.error(
                f"Job execution failed",
                execution_id=execution.execution_id,
                job_name=job.name,
                error=str(e)
            )
        finally:
            session.close()
    
    def _build_sync_params(self, job_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build sync parameters based on job type and config."""
        now = datetime.now()
        
        if job_type == JobType.FULL_REFRESH:
            return {
                "endpoints": config.get("endpoints", ["crashes", "people", "vehicles", "fatalities"]),
                "start_date": None,
                "end_date": None,
                "force": True
            }
        elif job_type == JobType.LAST_30_DAYS_CRASHES:
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
            return {
                "endpoints": ["crashes"],
                "start_date": start_date,
                "end_date": now.strftime("%Y-%m-%d"),
                "force": config.get("force", True)
            }
        elif job_type == JobType.LAST_30_DAYS_PEOPLE:
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
            return {
                "endpoints": ["people"],
                "start_date": start_date,
                "end_date": now.strftime("%Y-%m-%d"),
                "force": config.get("force", True)
            }
        elif job_type == JobType.LAST_30_DAYS_VEHICLES:
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
            return {
                "endpoints": ["vehicles"],
                "start_date": start_date,
                "end_date": now.strftime("%Y-%m-%d"),
                "force": config.get("force", True)
            }
        elif job_type == JobType.LAST_6_MONTHS_FATALITIES:
            start_date = (now - timedelta(days=180)).strftime("%Y-%m-%d")
            return {
                "endpoints": ["fatalities"],
                "start_date": start_date,
                "end_date": now.strftime("%Y-%m-%d"),
                "force": config.get("force", True)
            }
        elif job_type == JobType.CUSTOM:
            endpoints = config.get("endpoints", ["crashes"])
            params = {
                "endpoints": endpoints,
                "force": config.get("force", False)
            }
            
            # Handle date ranges
            if config.get("start_date"):
                params["start_date"] = config["start_date"]
            elif config.get("date_range_days"):
                start_date = (now - timedelta(days=config["date_range_days"])).strftime("%Y-%m-%d")
                params["start_date"] = start_date
            
            if config.get("end_date"):
                params["end_date"] = config["end_date"]
            else:
                params["end_date"] = now.strftime("%Y-%m-%d")
            
            return params
        
        # Default fallback
        return {
            "endpoints": ["crashes"],
            "start_date": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
            "end_date": now.strftime("%Y-%m-%d"),
            "force": False
        }
    
    def get_job_executions(self, job_id: int = None, limit: int = 50) -> List[JobExecution]:
        """Get job execution history."""
        session = self.get_session()
        try:
            query = session.query(JobExecution).order_by(desc(JobExecution.created_at))
            if job_id:
                query = query.filter_by(job_id=job_id)
            return query.limit(limit).all()
        finally:
            session.close()
    
    def delete_all_data(self, table_name: str, date_range: Dict[str, str] = None) -> Dict[str, Any]:
        """Delete all data from a table with optional date filtering."""
        session = self.get_session()
        start_time = datetime.now()
        
        try:
            # Map table names to models
            table_models = {
                "crashes": Crash,
                "crash_people": CrashPerson,
                "crash_vehicles": CrashVehicle,
                "vision_zero_fatalities": VisionZeroFatality
            }
            
            if table_name not in table_models:
                raise ValueError(f"Invalid table name: {table_name}")
            
            model = table_models[table_name]
            query = session.query(model)
            
            # Apply date filtering if provided
            if date_range:
                if hasattr(model, 'crash_date'):
                    if date_range.get("start"):
                        query = query.filter(model.crash_date >= date_range["start"])
                    if date_range.get("end"):
                        query = query.filter(model.crash_date <= date_range["end"])
            
            # Count records before deletion
            record_count = query.count()
            
            # Delete records
            query.delete()
            session.commit()
            
            # Log deletion
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            deletion_log = DataDeletionLog(
                table_name=table_name,
                records_deleted=record_count,
                deletion_criteria=date_range or {},
                executed_by="admin",
                execution_time_seconds=execution_time
            )
            
            session.add(deletion_log)
            session.commit()
            
            logger.info(f"Deleted {record_count} records from {table_name}")
            
            return {
                "records_deleted": record_count,
                "execution_time_seconds": execution_time,
                "backup_location": None,  # Could implement backup functionality
                "can_restore": False
            }
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete data from {table_name}: {str(e)}")
            raise
        finally:
            session.close()
    
    def get_job_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all jobs."""
        session = self.get_session()
        try:
            total_jobs = session.query(ScheduledJob).count()
            active_jobs = session.query(ScheduledJob).filter_by(enabled=True).count()
            
            running_jobs = session.query(JobExecution).filter_by(status=JobStatus.RUNNING).count()
            
            # Failed jobs in last 24 hours
            yesterday = datetime.now() - timedelta(hours=24)
            failed_jobs_24h = session.query(JobExecution).filter(
                and_(
                    JobExecution.status == JobStatus.FAILED,
                    JobExecution.created_at >= yesterday
                )
            ).count()
            
            # Last execution
            last_execution = session.query(JobExecution).order_by(
                desc(JobExecution.started_at)
            ).first()
            
            return {
                "total_jobs": total_jobs,
                "active_jobs": active_jobs,
                "running_jobs": running_jobs,
                "failed_jobs_24h": failed_jobs_24h,
                "last_execution": last_execution.started_at if last_execution else None
            }
        finally:
            session.close()
"""Sync operation endpoints."""
import asyncio
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from api.models import SyncRequest, SyncResponse, StatusResponse, TestSyncResponse
from api.dependencies import get_soda_client, get_data_sanitizer, get_sync_state
from etl.soda_client import SODAClient
from validators.data_sanitizer import DataSanitizer
from services.database_service import DatabaseService
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status", response_model=StatusResponse)
async def get_sync_status(sync_state: dict = Depends(get_sync_state)):
    """Get current sync status and statistics."""
    started_at = sync_state.get("started_at", datetime.now())
    uptime = str(datetime.now() - started_at)
    
    return StatusResponse(
        status=sync_state["status"],
        last_sync=sync_state["last_sync"],
        current_operation=sync_state["current_operation"],
        stats=sync_state["stats"],
        uptime=uptime
    )


@router.post("/trigger", response_model=SyncResponse)
async def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    sync_state: dict = Depends(get_sync_state)
):
    """Trigger a manual sync operation."""
    # Check if sync is already running
    if sync_state["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Sync operation already in progress"
        )
    
    # Generate sync ID
    sync_id = f"sync_{int(datetime.now().timestamp())}"
    
    # Update sync state
    sync_state["status"] = "running"
    sync_state["current_operation"] = f"Manual sync {sync_id}"
    
    # Add background task
    background_tasks.add_task(
        run_sync_operation,
        sync_id,
        sync_state,
        request.start_date,
        request.end_date,
        request.force,
        request.endpoint
    )
    
    logger.info("Triggered manual sync", sync_id=sync_id, request=request.dict())
    
    return SyncResponse(
        message="Sync operation started",
        sync_id=sync_id,
        status="running",
        started_at=datetime.now()
    )


@router.post("/test", response_model=TestSyncResponse)
async def test_sync(
    client: SODAClient = Depends(get_soda_client),
    sanitizer: DataSanitizer = Depends(get_data_sanitizer),
    sync_state: dict = Depends(get_sync_state)
):
    """Test sync operation with a small dataset."""
    try:
        sync_state["status"] = "testing"
        sync_state["current_operation"] = "Test sync"
        
        # Fetch a small number of test records
        test_records = await client.fetch_records(
            endpoint=settings.api.endpoints["crashes"],
            limit=5
        )
        
        # Test data sanitization
        cleaned_records = []
        for record in test_records:
            cleaned = sanitizer.sanitize_crash_record(record)
            cleaned_records.append(cleaned)
        
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        
        return TestSyncResponse(
            status="success",
            message="Test sync completed successfully",
            records_fetched=len(test_records),
            records_cleaned=len(cleaned_records),
            sample_record=cleaned_records[0] if cleaned_records else None
        )
        
    except Exception as e:
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["stats"]["last_error"] = str(e)
        
        logger.error("Test sync failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Test sync failed: {str(e)}")


@router.get("/endpoints")
async def get_endpoints():
    """Get information about available data endpoints."""
    endpoints_info = []
    
    for name, url in settings.api.endpoints.items():
        description_map = {
            "crashes": "Main crash records with location and injury data",
            "people": "Person-level injury and demographic data",
            "vehicles": "Vehicle/unit information involved in crashes",
            "fatalities": "Curated fatality dataset from Vision Zero initiative"
        }
        
        endpoints_info.append({
            "name": name,
            "url": url,
            "description": description_map.get(name, "Chicago crash data endpoint")
        })
    
    return {
        "endpoints": endpoints_info,
        "total_endpoints": len(endpoints_info)
    }


@router.get("/counts")
async def get_database_counts():
    """Get current record counts in the database."""
    try:
        db_service = DatabaseService()
        counts = db_service.get_record_counts()
        
        return {
            "status": "success",
            "counts": counts,
            "total_records": sum(counts.values()) if counts else 0,
            "timestamp": datetime.now()
        }
    except Exception as e:
        logger.error("Failed to get database counts", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get database counts: {str(e)}")


async def run_sync_operation(
    sync_id: str,
    sync_state: dict,
    start_date: str = None,
    end_date: str = None,
    force: bool = False,
    endpoint: str = None
):
    """Background task to run sync operation."""
    start_time = datetime.now()
    
    try:
        logger.info("Starting sync operation", sync_id=sync_id)
        
        sync_state["stats"]["total_syncs"] += 1
        
        # Initialize clients
        client = SODAClient()
        sanitizer = DataSanitizer()
        db_service = DatabaseService()
        
        # Determine which endpoints to sync
        endpoints_to_sync = [endpoint] if endpoint else list(settings.api.endpoints.keys())
        
        total_records = 0
        total_inserted = 0
        total_updated = 0
        
        for endpoint_name in endpoints_to_sync:
            sync_state["current_operation"] = f"Syncing {endpoint_name}"
            
            endpoint_url = settings.api.endpoints[endpoint_name]
            
            # Fetch all records with pagination and date filtering
            records = await client.fetch_all_records(
                endpoint=endpoint_url,
                batch_size=50000,  # 50K records per batch
                start_date=start_date,
                end_date=end_date,
                date_field="crash_date",
                show_progress=False  # Disable progress bar for background task
            )
            
            if not records:
                logger.info(f"No records found for {endpoint_name}")
                continue
            
            # Process records based on type
            if endpoint_name == "crashes":
                processed_records = [sanitizer.sanitize_crash_record(r) for r in records]
                # Save to database
                sync_state["current_operation"] = f"Saving {endpoint_name} to database"
                result = db_service.insert_crash_records(processed_records)
            elif endpoint_name == "people":
                processed_records = [sanitizer.sanitize_person_record(r) for r in records]
                sync_state["current_operation"] = f"Saving {endpoint_name} to database"
                result = db_service.insert_person_records(processed_records)
            elif endpoint_name == "vehicles":
                processed_records = [sanitizer.sanitize_vehicle_record(r) for r in records]
                sync_state["current_operation"] = f"Saving {endpoint_name} to database"
                result = db_service.insert_vehicle_records(processed_records)
            elif endpoint_name == "fatalities":
                processed_records = [sanitizer.sanitize_fatality_record(r) for r in records]
                # Remove duplicates by person_id
                processed_records = sanitizer.remove_duplicates(processed_records, 'person_id')
                sync_state["current_operation"] = f"Saving {endpoint_name} to database"
                result = db_service.insert_fatality_records(processed_records)
            else:
                processed_records = records
                result = {"inserted": 0, "updated": 0, "skipped": len(records)}
            
            total_records += len(processed_records)
            total_inserted += result.get("inserted", 0)
            total_updated += result.get("updated", 0)
            
            logger.info(
                "Processed endpoint records",
                endpoint=endpoint_name,
                records=len(processed_records),
                inserted=result.get("inserted", 0),
                updated=result.get("updated", 0),
                skipped=result.get("skipped", 0)
            )
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        
        # Mark sync as completed
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["last_sync"] = datetime.now()
        sync_state["stats"]["successful_syncs"] += 1
        sync_state["stats"]["total_records_processed"] += total_records
        sync_state["stats"]["last_sync_duration"] = duration
        
        logger.info(
            "Sync operation completed successfully",
            sync_id=sync_id,
            total_records=total_records,
            total_inserted=total_inserted,
            total_updated=total_updated,
            duration=duration
        )
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        
        sync_state["status"] = "idle"
        sync_state["current_operation"] = None
        sync_state["stats"]["failed_syncs"] += 1
        sync_state["stats"]["last_error"] = str(e)
        sync_state["stats"]["last_sync_duration"] = duration
        
        logger.error("Sync operation failed", sync_id=sync_id, error=str(e), duration=duration)
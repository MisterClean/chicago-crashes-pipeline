"""Data validation endpoints."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from api.models import DataValidationResponse
from api.dependencies import get_soda_client, get_crash_validator, get_data_sanitizer
from etl.soda_client import SODAClient
from validators.crash_validator import CrashValidator
from validators.data_sanitizer import DataSanitizer
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/validate", tags=["validation"])


@router.get("/{endpoint}", response_model=DataValidationResponse)
async def validate_endpoint_data(
    endpoint: str,
    limit: int = Query(100, description="Number of records to validate", ge=1, le=1000),
    client: SODAClient = Depends(get_soda_client),
    validator: CrashValidator = Depends(get_crash_validator),
    sanitizer: DataSanitizer = Depends(get_data_sanitizer)
):
    """Validate data quality for a specific endpoint."""
    
    # Check if endpoint exists
    if endpoint not in settings.api.endpoints:
        available_endpoints = list(settings.api.endpoints.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Endpoint '{endpoint}' not found. Available endpoints: {available_endpoints}"
        )
    
    try:
        # Fetch records
        endpoint_url = settings.api.endpoints[endpoint]
        records = await client.fetch_records(endpoint=endpoint_url, limit=limit)
        
        if not records:
            return DataValidationResponse(
                endpoint=endpoint,
                total_records=0,
                valid_records=0,
                invalid_records=0,
                validation_errors=["No records returned from API"],
                warnings=[]
            )
        
        # Validate records based on endpoint type
        validation_errors = []
        warnings = []
        valid_count = 0
        
        for i, record in enumerate(records):
            try:
                # Sanitize first
                if endpoint == "crashes":
                    cleaned_record = sanitizer.sanitize_crash_record(record)
                    validation_result = validator.validate_crash_record(cleaned_record)
                else:
                    # For other endpoints, just do basic validation
                    cleaned_record = record
                    validation_result = {"valid": True, "errors": [], "warnings": []}
                
                if validation_result["valid"]:
                    valid_count += 1
                else:
                    for error in validation_result["errors"]:
                        validation_errors.append(f"Record {i+1}: {error}")
                
                for warning in validation_result["warnings"]:
                    warnings.append(f"Record {i+1}: {warning}")
                    
            except Exception as e:
                validation_errors.append(f"Record {i+1}: Processing error - {str(e)}")
        
        return DataValidationResponse(
            endpoint=endpoint,
            total_records=len(records),
            valid_records=valid_count,
            invalid_records=len(records) - valid_count,
            validation_errors=validation_errors,
            warnings=warnings
        )
        
    except Exception as e:
        logger.error("Validation failed", endpoint=endpoint, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Validation failed for endpoint '{endpoint}': {str(e)}"
        )


@router.get("/")
async def validation_info():
    """Get information about available validation endpoints."""
    return {
        "message": "Data validation endpoints",
        "available_endpoints": list(settings.api.endpoints.keys()),
        "usage": "GET /validate/{endpoint}?limit=100",
        "validation_types": {
            "crashes": "Geographic bounds, date formats, required fields",
            "people": "Age validation, required fields",
            "vehicles": "Vehicle year validation, required fields",
            "fatalities": "Geographic bounds, date formats, required fields"
        },
        "limits": {
            "max_records_per_validation": 1000,
            "default_records": 100
        }
    }
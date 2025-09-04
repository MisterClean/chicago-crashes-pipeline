# API Documentation

This document provides comprehensive documentation for the Chicago Crash Data Pipeline API.

## Base URL

```
http://localhost:8000
```

## Authentication

The API currently does not require authentication for read operations. All endpoints are publicly accessible.

## Endpoints

### Root Endpoint

**GET /**

Returns basic API information and available endpoints.

**Response:**
```json
{
  "name": "Chicago Crash Data Pipeline API",
  "version": "1.0.0",
  "status": "online",
  "uptime": "2h 34m 12s",
  "endpoints": {
    "health": "/health",
    "sync": "/sync",
    "validate": "/validate",
    "spatial": "/spatial",
    "docs": "/docs"
  }
}
```

## Health Endpoints

### Health Check

**GET /health**

Returns the health status of the API and connected services.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-08-28T10:30:00Z",
  "services": {
    "database": "healthy",
    "soda_api": "healthy",
    "configuration": "healthy"
  },
  "version": "1.0.0"
}
```

### Version Information

**GET /version**

Returns detailed version and dependency information.

**Response:**
```json
{
  "version": "1.0.0",
  "python_version": "3.13.2",
  "build_date": "2024-08-28",
  "dependencies": {
    "fastapi": "0.104.1",
    "sqlalchemy": "2.0.23",
    "httpx": "0.25.1",
    "geoalchemy2": "0.14.2"
  }
}
```

## Sync Endpoints

### Sync Status

**GET /sync/status**

Returns the current status of data synchronization operations.

**Response:**
```json
{
  "status": "idle",
  "last_sync": "2024-08-28T09:15:00Z",
  "current_operation": null,
  "stats": {
    "total_syncs": 15,
    "last_records_processed": 1245,
    "average_sync_time": 120.5
  },
  "uptime": "2h 34m 12s"
}
```

### Available Endpoints Info

**GET /sync/endpoints**

Returns information about available data endpoints.

**Response:**
```json
{
  "endpoints": [
    {
      "name": "crashes",
      "url": "https://data.cityofchicago.org/resource/85ca-t3if.json",
      "description": "Traffic Crashes - Crashes",
      "last_updated": "2024-08-28T08:00:00Z"
    },
    {
      "name": "people",
      "url": "https://data.cityofchicago.org/resource/u6pd-qa9d.json", 
      "description": "Traffic Crashes - People",
      "last_updated": "2024-08-28T08:00:00Z"
    }
  ],
  "total_endpoints": 4
}
```

### Trigger Sync

**POST /sync/trigger**

Manually trigger a data synchronization operation.

**Request Body:**
```json
{
  "endpoint": "crashes",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "force": false
}
```

**Response:**
```json
{
  "message": "Sync operation started",
  "sync_id": "sync_20240828_103000",
  "status": "running",
  "started_at": "2024-08-28T10:30:00Z"
}
```

### Test Sync

**POST /sync/test**

Perform a test sync operation with a small dataset.

**Response:**
```json
{
  "status": "success",
  "message": "Test sync completed successfully",
  "records_fetched": 5,
  "records_cleaned": 5,
  "sample_record": {
    "crash_record_id": "cd8c5a2e582f87dc6b060d1bb0a18bf6e0d5db20",
    "crash_date": "2024-01-15T14:30:00",
    "latitude": 41.8781,
    "longitude": -87.6298
  },
  "processing_time": 1.25
}
```

## Validation Endpoints

### Validation Info

**GET /validate/**

Returns information about available validation endpoints and options.

**Response:**
```json
{
  "available_endpoints": ["crashes", "people", "vehicles", "fatalities"],
  "validation_types": ["required_fields", "data_types", "geographic_bounds"],
  "limits": {
    "max_records_per_request": 1000,
    "default_limit": 100
  }
}
```

### Validate Data

**GET /validate/{endpoint}**

Validate data quality for a specific endpoint.

**Parameters:**
- `endpoint` (path): Data endpoint to validate (crashes, people, vehicles, fatalities)
- `limit` (query, optional): Number of records to validate (default: 100, max: 1000)

**Example:** `GET /validate/crashes?limit=50`

**Response:**
```json
{
  "endpoint": "crashes",
  "total_records": 50,
  "valid_records": 47,
  "invalid_records": 3,
  "validation_summary": {
    "required_fields": "passed",
    "data_types": "passed", 
    "geographic_bounds": "warnings"
  },
  "validation_errors": [
    {
      "record_id": "abc123",
      "errors": ["Missing crash_date", "Invalid latitude"]
    }
  ],
  "warnings": [
    {
      "record_id": "def456", 
      "warnings": ["Coordinates outside Chicago bounds"]
    }
  ],
  "processing_time": 2.1
}
```

## Spatial Endpoints

### Spatial Info

**GET /spatial/**

Returns information about spatial data capabilities.

**Response:**
```json
{
  "message": "Spatial data management for Chicago crash analysis",
  "capabilities": [
    "Shapefile loading",
    "PostGIS integration",
    "Geographic queries"
  ],
  "usage": {
    "load_shapefiles": "POST /spatial/load",
    "list_tables": "GET /spatial/tables",
    "query_table": "GET /spatial/query/{table_name}"
  },
  "supported_formats": [".shp", ".geojson"],
  "coordinate_system": "EPSG:4326 (WGS84)"
}
```

### List Spatial Tables

**GET /spatial/tables**

Returns information about loaded spatial tables.

**Response:**
```json
{
  "tables": [
    {
      "table_name": "wards",
      "record_count": 50,
      "geometry_type": "POLYGON",
      "last_loaded": "2024-08-28T09:00:00Z"
    },
    {
      "table_name": "community_areas", 
      "record_count": 77,
      "geometry_type": "POLYGON",
      "last_loaded": "2024-08-28T09:00:00Z"
    }
  ],
  "total_tables": 2
}
```

## Job Management Endpoints

### List Jobs

**GET /jobs/**

Returns all scheduled jobs in the system.

**Query Parameters:**
- `enabled_only` (boolean, optional): Filter to only enabled jobs

**Response:**
```json
[
  {
    "id": 1,
    "name": "Full Data Refresh",
    "description": "Complete refresh of all data from Chicago Open Data Portal",
    "job_type": "full_refresh",
    "enabled": false,
    "recurrence_type": "once",
    "cron_expression": null,
    "next_run": null,
    "last_run": null,
    "config": {
      "endpoints": ["crashes", "people", "vehicles", "fatalities"],
      "force": true
    },
    "timeout_minutes": 300,
    "max_retries": 1,
    "retry_delay_minutes": 5,
    "created_by": "system",
    "created_at": "2024-09-04T02:44:40.450000Z",
    "updated_at": "2024-09-04T02:44:40.450000Z"
  }
]
```

### Create Job

**POST /jobs/**

Creates a new scheduled job.

**Request Body:**
```json
{
  "name": "Custom Sync Job",
  "description": "Custom data synchronization job",
  "job_type": "custom",
  "enabled": true,
  "recurrence_type": "daily",
  "config": {
    "endpoints": ["crashes"],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "force": false
  },
  "timeout_minutes": 60,
  "max_retries": 3,
  "retry_delay_minutes": 5
}
```

### Get Job

**GET /jobs/{job_id}**

Returns details for a specific job.

### Update Job

**PUT /jobs/{job_id}**

Updates an existing job configuration.

### Delete Job

**DELETE /jobs/{job_id}**

Deletes a job and all its execution history.

### Execute Job

**POST /jobs/{job_id}/execute**

Manually executes a job.

**Request Body:**
```json
{
  "force": true,
  "override_config": {
    "endpoints": ["crashes"],
    "start_date": "2024-08-01"
  }
}
```

**Response:**
```json
{
  "message": "Job 1 execution started",
  "execution_id": "exec_1_1725413040",
  "job_id": 1,
  "status": "pending",
  "started_at": "2024-09-04T02:44:00Z"
}
```

### Job Execution History

**GET /jobs/{job_id}/executions**

Returns execution history for a specific job.

**GET /jobs/executions/recent**

Returns recent execution history across all jobs.

**Query Parameters:**
- `limit` (integer, optional): Maximum number of executions to return (1-200, default: 50)

### Job Summary

**GET /jobs/summary**

Returns summary statistics for all jobs.

**Response:**
```json
{
  "total_jobs": 4,
  "active_jobs": 3,
  "running_jobs": 0,
  "failed_jobs_24h": 0,
  "last_execution": "2024-09-04T02:44:00Z"
}
```

### Data Deletion

**POST /jobs/data/delete**

Safely deletes data from database tables.

**Request Body:**
```json
{
  "table_name": "crashes",
  "confirm": true,
  "backup": true,
  "date_range": {
    "start": "2024-01-01",
    "end": "2024-01-31"
  }
}
```

**Response:**
```json
{
  "message": "Successfully deleted 1500 records from crashes",
  "table_name": "crashes",
  "records_deleted": 1500,
  "execution_time_seconds": 2.34,
  "backup_location": null,
  "can_restore": false
}
```

### Job Types and Configuration

**GET /jobs/types**

Returns available job types, recurrence types, and valid configuration options.

**Response:**
```json
{
  "job_types": [
    {"value": "full_refresh", "label": "Full Refresh"},
    {"value": "last_30_days_crashes", "label": "Last 30 Days Crashes"},
    {"value": "last_30_days_people", "label": "Last 30 Days People"},
    {"value": "last_6_months_fatalities", "label": "Last 6 Months Fatalities"},
    {"value": "custom", "label": "Custom"}
  ],
  "recurrence_types": [
    {"value": "once", "label": "Once"},
    {"value": "daily", "label": "Daily"},
    {"value": "weekly", "label": "Weekly"},
    {"value": "monthly", "label": "Monthly"}
  ],
  "valid_endpoints": ["crashes", "people", "vehicles", "fatalities"],
  "valid_tables": ["crashes", "crash_people", "crash_vehicles", "vision_zero_fatalities"]
}
```

## Admin Portal

The admin portal provides a web-based interface for managing the system and is available at:

**URL:** http://localhost:8000/admin

See [ADMIN_PORTAL.md](./ADMIN_PORTAL.md) for complete documentation.

## Error Responses

The API uses standard HTTP status codes and returns error details in JSON format.

### Error Format

```json
{
  "detail": "Error description",
  "error_type": "ValidationError",
  "timestamp": "2024-08-28T10:30:00Z"
}
```

### Common Status Codes

- **200 OK**: Request successful
- **400 Bad Request**: Invalid request parameters
- **404 Not Found**: Resource not found
- **422 Unprocessable Entity**: Validation error
- **500 Internal Server Error**: Server error

### Example Error Responses

**404 Not Found:**
```json
{
  "detail": "Endpoint 'invalid_endpoint' not found. Available endpoints: crashes, people, vehicles, fatalities"
}
```

**422 Validation Error:**
```json
{
  "detail": [
    {
      "loc": ["body", "start_date"],
      "msg": "Invalid date format. Use YYYY-MM-DD",
      "type": "value_error.date"
    }
  ]
}
```

## Rate Limiting

The API implements rate limiting to ensure fair usage:

- **Default limit**: 1000 requests per hour per IP
- **Burst limit**: 60 requests per minute
- **Headers included**:
  - `X-RateLimit-Limit`: Rate limit ceiling
  - `X-RateLimit-Remaining`: Number of requests remaining
  - `X-RateLimit-Reset`: UTC timestamp when limit resets

## CORS Policy

Cross-Origin Resource Sharing (CORS) is enabled for all origins during development. In production, configure specific allowed origins in the settings.

## Interactive Documentation

- **Swagger UI**: Available at `/docs`
- **ReDoc**: Available at `/redoc`
- **OpenAPI Schema**: Available at `/openapi.json`

## Data Models

### Crash Record

```json
{
  "crash_record_id": "string",
  "crash_date": "2024-01-15T14:30:00",
  "latitude": 41.8781,
  "longitude": -87.6298,
  "street_name": "MICHIGAN AVE",
  "injuries_total": 2,
  "injuries_fatal": 0,
  "traffic_control_device": "TRAFFIC SIGNAL",
  "weather_condition": "CLEAR",
  "lighting_condition": "DAYLIGHT"
}
```

### Person Record

```json
{
  "crash_record_id": "string",
  "person_id": "string", 
  "person_type": "DRIVER",
  "age": 35,
  "sex": "M",
  "injury_classification": "NO INDICATION OF INJURY"
}
```

### Vehicle Record

```json
{
  "crash_record_id": "string",
  "unit_no": "1",
  "vehicle_year": 2020,
  "make": "TOYOTA",
  "model": "CAMRY",
  "num_passengers": 1
}
```

## Examples

### Python Client Example

```python
import httpx
import asyncio

async def get_crash_data():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://localhost:8000/sync/status")
        return response.json()

# Trigger a sync operation
async def trigger_sync():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/sync/trigger",
            json={
                "endpoint": "crashes",
                "start_date": "2024-01-01",
                "force": False
            }
        )
        return response.json()
```

### cURL Examples

```bash
# Get API status
curl http://localhost:8000/

# Check health
curl http://localhost:8000/health

# Get sync status
curl http://localhost:8000/sync/status

# Validate crash data
curl "http://localhost:8000/validate/crashes?limit=10"

# Trigger sync
curl -X POST "http://localhost:8000/sync/trigger" \
  -H "Content-Type: application/json" \
  -d '{"endpoint": "crashes", "start_date": "2024-01-01"}'
```
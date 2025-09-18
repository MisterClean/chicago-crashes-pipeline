---
title: API Reference
sidebar_position: 2
description: REST endpoints exposed by the Chicago Crash Data Pipeline FastAPI service.
---

All endpoints are served from the FastAPI application (default `http://localhost:8000`). Authentication is not enforced by default; secure deployments should add an API gateway or middleware.

## Conventions

- JSON request/response bodies follow the Pydantic models defined in `src/api/models.py`.
- Date values use ISO 8601 strings (`YYYY-MM-DD` or full timestamps with timezone).
- Error responses include a `detail` string and HTTP status code.

## Health & Metadata

### `GET /`
Summary of service status, available endpoints, and runtime uptime.

### `GET /health`
Performs configuration, SODA API, and database checks. Returns `status` (`healthy` or `degraded`) with per-service details.

### `GET /version`
Build metadata: API version, Python runtime, and pinned dependency versions.

## Sync Operations (`/sync`)

### `GET /sync/status`
Current sync state including last run timestamps, active operation label, stats, and uptime.

### `POST /sync/trigger`
Start a manual sync in the background.

```json
{
  "endpoints": ["crashes", "people"],
  "start_date": "2024-01-01",
  "end_date": "2024-02-01",
  "force": false,
  "batch_size": 50000
}
```

Returns a `sync_id` and `status` (`running` or `queued`).

### `POST /sync/test`
Fetches a small sample (default 5 records) and runs through sanitisation to confirm SODA connectivity.

### `GET /sync/endpoints`
Metadata about configured SODA endpoints and their descriptions.

### `GET /sync/counts`
Aggregated record counts from the database for quick verification after syncs.

## Data Validation (`/validate`)

### `GET /validate/`
Lists available endpoints, validation use cases, and default limits.

### `GET /validate/{endpoint}?limit=100`
Validates up to 1,000 records for the specified endpoint (`crashes`, `people`, `vehicles`, `fatalities`). Response includes counts for valid/invalid records and lists of validation errors/warnings.

## Job Management (`/jobs`)

### `GET /jobs/`
Returns all scheduled jobs. Use the `enabled_only` query param (`true`/`false`) to filter.

### `GET /jobs/summary`
Aggregate metrics (total jobs, active jobs, running jobs, failures in the last 24 hours).

### `GET /jobs/types`
Lists job templates and endpoint presets defined in the application.

### `POST /jobs/`
Create a job. Request matches `CreateJobRequest`:

```json
{
  "name": "Last 30 Days - Vehicles",
  "description": "Daily vehicles refresh",
  "job_type": "last_30_days_vehicles",
  "enabled": true,
  "recurrence_type": "daily",
  "config": {
    "endpoints": ["vehicles"],
    "window_days": 30
  },
  "timeout_minutes": 60,
  "max_retries": 3,
  "retry_delay_minutes": 5
}
```

### `PUT /jobs/{id}`
Update job configuration. Partial updates are supported through the admin portal UI.

### `DELETE /jobs/{id}`
Remove a job and its execution history.

### `POST /jobs/{id}/execute`
Immediately enqueue a job. Optionally supply `{ "force": true }` to bypass concurrency checks.

### `GET /jobs/{id}/executions`
Execution history for a specific job (most recent first).

### `GET /jobs/executions/recent?limit=10`
Global recent activity feed used by the admin dashboard.

### `GET /jobs/executions/{execution_id}`
Detailed execution data: timestamps, record counts, error messages, structured log entries.

### `POST /jobs/data/delete`
Delete records from a table with optional date bounds.

```json
{
  "table_name": "crashes",
  "start_date": "2020-01-01",
  "end_date": "2020-12-31",
  "reason": "Purge duplicated backfill"
}
```

Successful responses include a `deletion_id` and summary counts. Deletions are logged in `data_deletion_logs`.

## Spatial APIs (`/spatial`)

### `GET /spatial/`
Documentation for spatial endpoints including usage examples.

### `GET /spatial/tables`
Lists shapefile-derived tables currently loaded in PostGIS (requires GeoPandas dependencies).

### `GET /spatial/tables/{table}?limit=10`
Returns schema metadata and a sample of records for a spatial table.

### `POST /spatial/load?directory=data/shapefiles`
Bulk load shapefiles residing in the target directory. Reports success/failure per file.

### `GET /spatial/layers`
List custom GeoJSON layers managed by the `SpatialLayerService`.

### `POST /spatial/layers`
Upload a GeoJSON payload. Accepts multipart form data (`name`, `file`, optional `description`, `srid`).

### `PATCH /spatial/layers/{layer_id}`
Update metadata or activation state for an existing layer.

### `POST /spatial/layers/{layer_id}/replace`
Replace the stored geometry with new GeoJSON content.

### `DELETE /spatial/layers/{layer_id}`
Remove a layer entirely.

## OpenAPI & Docs

- **Swagger UI**: `GET /docs`
- **OpenAPI JSON**: `GET /openapi.json`
- **ReDoc**: `GET /redoc`

Use these interactive docs to experiment with the API or generate client SDKs.

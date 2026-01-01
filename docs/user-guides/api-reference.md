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

## Dashboard APIs (`/dashboard`)

Frontend-facing endpoints for the public crash dashboard and location reports.

### `GET /dashboard/stats`
Get aggregate statistics for dashboard metric cards.

**Query Parameters:**
- `start_date` (optional): ISO 8601 date to filter from
- `end_date` (optional): ISO 8601 date to filter to (inclusive, end of day)

**Response:**
```json
{
  "total_crashes": 45000,
  "total_injuries": 12000,
  "total_fatalities": 150,
  "pedestrians_involved": 2500,
  "cyclists_involved": 1200,
  "hit_and_run_count": 8000
}
```

### `GET /dashboard/trends/weekly`
Get weekly crash trends for charts.

**Query Parameters:**
- `weeks` (optional, 1-104): Number of weeks to look back (default: 52)
- `start_date` / `end_date` (optional): Explicit date range (takes precedence over weeks)

**Response:**
```json
[
  {"week": "2024-01-01", "crashes": 850, "injuries": 220, "fatalities": 3},
  {"week": "2024-01-08", "crashes": 920, "injuries": 245, "fatalities": 2}
]
```

### `GET /dashboard/crashes/geojson`
Get crashes as GeoJSON FeatureCollection for map display.

**Query Parameters:**
- `start_date` / `end_date` (optional): Date range filter
- `limit` (optional, 1-50000): Maximum records (default: 10000)

**Response:** GeoJSON FeatureCollection with crash points and properties (crash_record_id, crash_date, injuries, severity, etc.)

### `GET /dashboard/crashes/by-hour`
Get crash counts grouped by hour of day for time-of-day analysis.

### `GET /dashboard/crashes/by-cause`
Get top crash causes by count.

**Query Parameters:**
- `limit` (optional, 1-50): Number of causes to return (default: 10)

### `POST /dashboard/location-report`
Generate a comprehensive crash report for a specific geographic area.

**Request Body (choose one spatial query method):**
```json
{
  "latitude": 41.9032,
  "longitude": -87.6315,
  "radius_feet": 1320,
  "start_date": "2023-01-01",
  "end_date": "2024-01-01"
}
```

Or polygon query:
```json
{
  "polygon": [[-87.63, 41.90], [-87.62, 41.90], [-87.62, 41.91], [-87.63, 41.91]],
  "start_date": "2023-01-01"
}
```

Or predefined place:
```json
{
  "place_type": "wards",
  "place_id": "44",
  "start_date": "2023-01-01"
}
```

**Response:**
- `stats`: Aggregate statistics including crash counts, injuries, fatalities, pedestrians, cyclists, hit-and-runs, and **cost estimates** (economic damages and societal costs based on FHWA KABCO methodology)
- `cost_breakdown`: Detailed per-injury-classification costs showing unit costs and subtotals
- `causes`: Top contributory causes with percentages
- `monthly_trends`: 12-month trend data for sparklines
- `crashes_geojson`: GeoJSON of crash points in the area
- `query_area_geojson`: GeoJSON of the queried boundary

**Cost Estimation Methodology:**
Costs are calculated using FHWA 2024 crash cost factors:
- Fatal (K): $1.6M economic / $11.3M societal
- Incapacitating (A): $172K / $1.1M
- Non-incapacitating (B): $44K / $225K
- Possible Injury (C): $26K / $111K
- Property Damage Only vehicles: $6,269 / $10,196

## Places APIs (`/places`)

Endpoints for accessing predefined geographic boundaries (wards, community areas, districts) and user-uploaded spatial layers.

### `GET /places/types`
List all available place types.

**Response:**
```json
[
  {"id": "wards", "name": "Wards", "source": "native", "feature_count": 50},
  {"id": "community_areas", "name": "Community Areas", "source": "native", "feature_count": 77},
  {"id": "house_districts", "name": "IL House Districts", "source": "native", "feature_count": 23},
  {"id": "senate_districts", "name": "IL Senate Districts", "source": "native", "feature_count": 12},
  {"id": "police_beats", "name": "Police Beats", "source": "native", "feature_count": 277},
  {"id": "layer:5", "name": "My Custom Zones", "source": "uploaded", "feature_count": 15}
]
```

### `GET /places/types/{place_type}/items`
List all places within a place type.

**Response:**
```json
[
  {"id": "1", "name": "Ward 1", "display_name": "Ward 1 - Ald. Daniel La Spata"},
  {"id": "2", "name": "Ward 2", "display_name": "Ward 2 - Ald. Brian Hopkins"}
]
```

### `GET /places/types/{place_type}/items/{place_id}/geometry`
Get the GeoJSON geometry for a specific place.

**Response:**
```json
{
  "place_type": "wards",
  "place_id": "44",
  "name": "Ward 44",
  "geometry": {"type": "MultiPolygon", "coordinates": [...]}
}
```

## OpenAPI & Docs

- **Swagger UI**: `GET /docs`
- **OpenAPI JSON**: `GET /openapi.json`
- **ReDoc**: `GET /redoc`

Use these interactive docs to experiment with the API or generate client SDKs.

---
title: Admin Portal
sidebar_position: 1
description: Operate and monitor the pipeline through the built-in admin portal.
---

The admin portal is a single-page application served from `/admin` by the FastAPI service. It provides live visibility into scheduled jobs, execution history, data volumes, and spatial assets.

Access the portal after starting the API:

```
http://localhost:8000/admin
```

## Dashboard

The landing view surfaces real-time metrics pulled from the REST API:

- **Total Jobs / Active Jobs** – counts from `GET /jobs/summary`.
- **Running Jobs** – active executions reported by the scheduler.
- **Failed Jobs (24h)** – execution failures recorded during the last day.
- **Quick Actions** – buttons that trigger the default sync jobs (e.g., `full_refresh`, `last_30_days_crashes`). These map to the job type identifiers defined in `src/models/jobs.py`.
- **Recent Activity** – rolling feed of the last ten executions with status, record counts, and timestamps.

Use the toolbar refresh button or enable auto-refresh (30 second interval) to keep data current.

## Scheduled Jobs

The **Scheduled Jobs** tab lists every entry in the `scheduled_jobs` table.

Capabilities:

- **Create Job** – launches a modal to configure job type, recurrence (once/daily/weekly/cron), endpoints, and execution window. Jobs default to enabled with calculated `next_run` when the recurrence is not `once`.
- **Enable / Disable** – toggle the `enabled` flag for any job.
- **Execute Now** – initiates an immediate run via `POST /jobs/{id}/execute` (uses the same background task pipeline as scheduled runs).
- **Edit** – update recurrence, timeout, retry policy, or endpoint configuration.
- **Delete** – removes the job and associated execution history.

Filter the jobs table with the “Enabled only” switch to focus on active schedules.

## Execution History

Select **Execution History** to inspect past runs:

- **Filters** – narrow by job or status (running, completed, failed).
- **Details Drawer** – clicking a row opens a modal with logs, per-endpoint statistics, retry counts, and timestamps. Live executions poll `/jobs/executions/{execution_id}` every five seconds until completion.
- **Download Logs** – copy structured log entries for further analysis.

## Data Management

The data management tab interacts with helper endpoints in `src/api/routers/sync.py` and `src/api/routers/jobs.py`.

- **Record Counts** – `GET /sync/counts` summarises table totals for quick validation after syncs.
- **Data Deletion** – submit a scoped deletion request (table + optional date range) to purge data. The UI enforces a confirmation checkbox and calls `POST /jobs/data/delete` to ensure deletions are logged.
- **Health Indicators** – badges reflect responses from `GET /health` and database connectivity checks.

## Spatial Layers

Spatial content is managed via the `SpatialLayerService` and `/spatial/layers` endpoints.

- **Upload GeoJSON** – drag-and-drop files (or use the upload modal) to create new layers. Files are stored in the database with metadata and SRID 4326 by default.
- **Activate / Deactivate** – control layer visibility for downstream consumers by toggling the `is_active` flag.
- **Replace Geometry** – upload a replacement GeoJSON for an existing layer without changing its ID.
- **Delete Layers** – remove obsolete assets with a single click.

Shapefile ingestion through `POST /spatial/load` remains available for bulk loading of official boundary datasets (see [Spatial Operations](../operations/operations-overview.md#spatial-assets)).

## Tips

- The portal gauges API connectivity and surfaces errors via toast notifications; investigate the browser console for stack traces during debugging.
- Permissions are currently open. Place the admin portal behind authentication or a VPN when deploying to shared environments.
- Pair the portal with external monitoring (Prometheus, Grafana, etc.) to capture infrastructure-level metrics such as database load or queue depth.

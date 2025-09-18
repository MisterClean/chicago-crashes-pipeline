---
title: Services & Modules
sidebar_position: 2
description: Deep dive into the internal services, modules, and execution flow.
---

## Data Ingestion Flow

1. **SODA Client (`src/etl/soda_client.py`)** – wraps HTTP access to the Chicago Open Data API with retry logic, pagination, and rate limiting aligned with `config/config.yaml`.
2. **Data Sanitizer (`src/validators/data_sanitizer.py`)** – normalises raw payloads, converts numeric fields, constrains geographic bounds, and strips invalid values.
3. **Crash Validator (`src/validators/crash_validator.py`)** – enforces domain rules for crash records (age ranges, coordinate bounds, enumerations) and surfaces warnings vs. hard errors.
4. **Sync Service (`src/services/sync_service.py`)** – orchestrates ETL runs, persists progress, and streams batches into SQLAlchemy bulk loaders.
5. **Database Service (`src/services/database_service.py`)** – centralises SQLAlchemy session handling and bulk insert/update helpers, including PostGIS geometry conversions.

## Job Scheduler

- **Scheduled Jobs** – modelled in `src/models/jobs.py` with recurrence types (`once`, `daily`, `weekly`, `cron`).
- **JobService (`src/services/job_service.py`)** – CRUD operations, execution history, retry logic, and default job bootstrapping.
- **Scheduler (`src/services/job_scheduler.py`)** – async loop that evaluates due jobs, coordinates concurrency via Redis locks, and invokes the sync service.
- **Executions** – tracked with `JobExecution` records containing duration, record counts, and structured log fragments consumed by the admin portal.

## REST API

- **Entry Point (`src/api/main.py`)** – wires dependency injection, mounts `/admin`, and registers routers.
- **Routers** – modular endpoints under `src/api/routers/` for health, sync, validation, spatial layers, and job management.
- **Models (`src/api/models.py`)** – Pydantic schemas providing strong typing for request/response payloads.

## Spatial Capabilities

- **SimpleShapefileLoader (`src/spatial/simple_loader.py`)** – loads shapefiles into PostGIS tables using GeoPandas/Shapely when available.
- **SpatialLayerService (`src/services/spatial_layer_service.py`)** – stores custom GeoJSON layers in the database for use in the admin portal.
- **Admin Portal UI** – integrates shapefile upload, layer activation toggles, and sample queries through `/spatial` endpoints.

## Command Line Interface

- **`src/cli/pipeline.py`** – thin wrapper around the sync service offering `initial-load` and `delta` commands with optional endpoint filtering.
- **Makefile Targets** – convenience commands (`make sync`, `make initial-load`, `make load-shapefiles`) that forward to the CLI or supporting scripts.

## Logging & Observability

- All modules use `src.utils.logging` to emit JSON structured logs to rotating files (`logs/app.log`, `logs/etl.log`, `logs/api.log`).
- Health checks (`GET /health`) verify configuration, SODA connectivity, and database readiness.
- Job executions capture timing, record counts, and error logs that surface in the admin portal for lightweight monitoring.

This modular approach keeps ingestion, orchestration, and presentation concerns isolated while sharing configuration and logging infrastructure.

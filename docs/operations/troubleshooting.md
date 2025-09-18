---
title: Troubleshooting
sidebar_position: 3
description: Diagnose and resolve common issues with the pipeline.
---

Use this checklist when something goes wrong. Commands assume you are in the project root.

## Quick Diagnostics

```bash
# API health
curl http://localhost:8000/health

# Service status (Docker Compose)
docker compose -f docker/docker-compose.yml ps

# Tail API logs
docker compose -f docker/docker-compose.yml logs -f app

# Check database readiness
docker compose -f docker/docker-compose.yml exec postgres pg_isready -U postgres
```

## Database Issues

### "Connection refused" or authentication failures

1. Ensure the container is running:
   ```bash
   docker compose -f docker/docker-compose.yml ps postgres
   ```
2. Validate credentials in `.env` and `docker/docker-compose.yml`.
3. Reset the database password and recreate the container if necessary:
   ```bash
   docker compose -f docker/docker-compose.yml down postgres
   docker compose -f docker/docker-compose.yml up -d postgres
   ```

### PostGIS extension missing

```bash
docker compose -f docker/docker-compose.yml exec postgres \
  psql -U postgres -d chicago_crashes -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

## API Fails to Start

- **Import errors / missing dependencies** – rebuild the image or reinstall requirements:
  ```bash
  pip install -r requirements.txt
  ```
- **Port already in use** – check and free port 8000:
  ```bash
  lsof -i :8000
  kill <PID>
  ```
- **Configuration errors** – validate `config/config.yaml` (YAML syntax, environment placeholders). The API logs the offending key when configuration parsing fails.

## Sync Failures

1. Inspect the execution detail dialog in the admin portal for error messages.
2. Review `logs/etl.log` for stack traces or rate-limit warnings.
3. Confirm SODA API availability:
   ```bash
   curl "https://data.cityofchicago.org/resource/85ca-t3if.json?$limit=1"
   ```
4. Retry with a smaller `batch_size` or restricted endpoint list to isolate the failing dataset.

## Slow Sync Performance

- Provide an API token (`CHICAGO_API_TOKEN`) to raise rate limits.
- Temporarily reduce `sync.max_concurrent` or `sync.chunk_size` for environments with limited memory.
- Run heavy backfills outside peak hours and disable non-essential scheduled jobs during the backfill.

## Admin Portal Errors

- Check browser developer tools for failed HTTP calls (most issues trace back to API availability or CORS settings).
- Ensure the API static mount points to `src/static/admin` (custom deployments must include these assets).
- Refresh the page after redeploying the API to clear cached assets.

## Spatial Layer Problems

- Confirm GeoPandas/Shapely dependencies are installed if you rely on shapefile ingestion.
- Ensure uploaded GeoJSON uses SRID 4326 by default; specify a different SRID in the upload form if needed.
- Use `GET /spatial/layers` and `GET /spatial/tables` to verify what the API sees.

## Reset the Environment

```bash
# Stop containers and remove volumes
docker compose -f docker/docker-compose.yml down -v

# Clear generated Python caches
make clean

# Reinstall dependencies
pip install -r requirements.txt
```

Document any new failure modes you encounter so they can be added to this playbook.

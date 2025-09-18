---
title: Configuration Reference
sidebar_position: 2
description: Understand the environment variables and YAML settings that control the pipeline.
---

The pipeline reads configuration from two sources:

1. **Environment variables** – quick overrides for secrets and runtime tuning
2. **`config/config.yaml`** – structured configuration committed to the repository

Both layers are merged through the `src.utils.config` module. Environment variables take precedence over YAML defaults.

## Environment Variables

Create a `.env` file (see `.env.example`) and load it before starting the API or CLI. Key values include:

| Variable | Description |
| --- | --- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection details used by SQLAlchemy |
| `CHICAGO_API_TOKEN` | Optional token for the SODA API. Greatly increases rate limits |
| `ENVIRONMENT` | Free-form environment name used in logging (`development`, `staging`, `production`, …) |
| `LOG_LEVEL` | Overrides logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `API_HOST`, `API_PORT` | Binds FastAPI when running outside Docker |

When running under Docker Compose these values can be supplied via `docker compose --env-file` or by editing the service `environment` block.

## `config/config.yaml`

`config/config.yaml` contains the full application configuration. Highlights:

### API Endpoints

```yaml
api:
  endpoints:
    crashes: "https://data.cityofchicago.org/resource/85ca-t3if.json"
    people: "https://data.cityofchicago.org/resource/u6pd-qa9d.json"
    vehicles: "https://data.cityofchicago.org/resource/68nd-jvt3.json"
    fatalities: "https://data.cityofchicago.org/resource/gzaz-isa6.json"
  rate_limit: 1000   # Requests per hour
  timeout: 30        # Seconds per HTTP request
  max_retries: 3
  backoff_factor: 2
  batch_size: 50000
  max_concurrent: 5
```

Adjust `batch_size` and `max_concurrent` if you hit API throttling or need to reduce memory pressure.

### Database

```yaml
database:
  host: ${DB_HOST:localhost}
  port: ${DB_PORT:5432}
  database: ${DB_NAME:chicago_crashes}
  username: ${DB_USER:postgres}
  password: ${DB_PASSWORD:}
  pool_size: 10
  max_overflow: 20
  bulk_insert_size: 1000
  use_copy: true
```

Values wrapped in `${…}` interpolate environment variables with fallbacks. Connection pooling values directly influence SQLAlchemy engine configuration.

### Sync Engine

```yaml
sync:
  default_start_date: "2017-09-01"
  sync_interval: 6          # Hours between recurring syncs
  chunk_size: 50000
  progress_bar: true
  log_retention_days: 30
```

`default_start_date` is used when running the initial backfill from the admin portal or CLI without an explicit range.

### Validation Rules

```yaml
validation:
  bounds:
    min_latitude: 41.6
    max_latitude: 42.1
    min_longitude: -87.95
    max_longitude: -87.5
  age_range:
    min: 0
    max: 120
  vehicle_year_range:
    min: 1900
    max: 2025
  required_fields:
    crashes: ["crash_record_id", "crash_date"]
    people: ["crash_record_id", "person_id"]
    vehicles: ["crash_record_id", "unit_no"]
    fatalities: ["person_id"]
```

These settings are consumed by the `DataSanitizer` and `CrashValidator` classes.

### Spatial Data

```yaml
spatial:
  shapefiles:
    wards: "data/shapefiles/chicago_wards.shp"
    community_areas: "data/shapefiles/community_areas.shp"
    census_tracts: "data/shapefiles/census_tracts.shp"
    police_beats: "data/shapefiles/police_beats.shp"
    house_districts: "data/shapefiles/house_districts.shp"
    senate_districts: "data/shapefiles/senate_districts.shp"
  srid: 4326
```

The admin portal uploads GeoJSON layers through `/spatial/layers`. Shapefile ingestion uses the paths above.

### Logging & Monitoring

```yaml
logging:
  level: INFO
  format: json
  files:
    app: "logs/app.log"
    etl: "logs/etl.log"
    api: "logs/api.log"
  max_bytes: 10485760
  backup_count: 5

monitoring:
  health_check_timeout: 5
  enable_metrics: true
  metrics_port: 9090
```

Logs are rotated when the files exceed `max_bytes`. Metrics are exposed via the Prometheus-style endpoint (see `src/services/metrics_service.py` if you extend telemetry).

## Reloading Configuration

`settings` are cached when the application starts. After updating `config/config.yaml` restart the API and any background workers to pick up changes.

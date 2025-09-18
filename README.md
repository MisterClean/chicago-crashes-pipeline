# Chicago Traffic Crash Data Pipeline

A Python-based data pipeline that ingests, validates, and serves Chicago traffic crash data from multiple SODA APIs, supporting spatial analysis and automated refresh workflows.

## Overview

The service orchestrates end-to-end ETL for four interconnected datasets from the Chicago Open Data Portal, keeps them synchronized in PostgreSQL/PostGIS, and exposes a FastAPI layer with an admin UI and documentation.

## Quick Start

**Prerequisites**: Python 3.11+, pip, Docker, Node 18+, npm, and GNU Make.

```bash
git clone https://github.com/<your-org>/chicago-crashes-pipeline.git
cd chicago-crashes-pipeline
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env  # update credentials as needed
make docker-up  # start Postgres/PostGIS and supporting services
make migrate
make serve  # FastAPI + admin portal at http://localhost:8000
```

## Datasets

1. **Traffic Crashes – Crashes**: Primary crash records (~1M+ rows)
2. **Traffic Crashes – People**: Person-level injury details
3. **Traffic Crashes – Vehicles**: Vehicle and unit information
4. **Traffic Crashes – Vision Zero Fatalities**: Curated fatality data

## Architecture

```mermaid
graph TB
    subgraph External["External Data Sources"]
        CDA[Chicago Data Portal - SODA API]
        SHP[Shapefiles - Geographic Boundaries]
    end
    
    subgraph WebUI["Web Interface"]
        ADMIN[Admin Portal]
        API_DOCS[API Documentation]
    end
    
    subgraph API["API Layer"]
        FASTAPI[FastAPI Application]
        SYNC_R[Sync Router]
        JOBS_R[Jobs Router]
        HEALTH_R[Health Router]
        SPATIAL_R[Spatial Router]
    end
    
    subgraph Services["Business Logic"]
        ETL[ETL Service]
        VALIDATOR[Data Validator]
        JOB_SVC[Job Service]
        SCHEDULER[Job Scheduler]
        DB_SVC[Database Service]
        SPATIAL_SVC[Spatial Service]
    end
    
    subgraph Processing["Data Processing"]
        SANITIZER[Data Sanitizer]
        RATE_LIMITER[Rate Limiter]
    end
    
    subgraph Storage["Data Storage"]
        PG[(PostgreSQL with PostGIS)]
        CRASHES[(Crashes Table)]
        PEOPLE[(People Table)]
        VEHICLES[(Vehicles Table)]
        FATALITIES[(Fatalities Table)]
        JOBS[(Jobs Table)]
        EXECUTIONS[(Executions Table)]
    end
    
    subgraph Infra["Infrastructure"]
        DOCKER[Docker Container]
        VENV[Python Environment]
    end

    ADMIN --> FASTAPI
    API_DOCS --> FASTAPI
    FASTAPI --> SYNC_R
    FASTAPI --> JOBS_R
    FASTAPI --> HEALTH_R
    FASTAPI --> SPATIAL_R
    
    SYNC_R --> ETL
    JOBS_R --> JOB_SVC
    SPATIAL_R --> SPATIAL_SVC
    
    ETL --> CDA
    ETL --> RATE_LIMITER
    ETL --> VALIDATOR
    VALIDATOR --> SANITIZER
    
    JOB_SVC --> SCHEDULER
    JOB_SVC --> DB_SVC
    SCHEDULER --> ETL
    
    SPATIAL_SVC --> SHP
    SPATIAL_SVC --> DB_SVC
    
    DB_SVC --> PG
    PG --> CRASHES
    PG --> PEOPLE
    PG --> VEHICLES
    PG --> FATALITIES
    PG --> JOBS
    PG --> EXECUTIONS
    
    PG -.-> DOCKER
    FASTAPI -.-> VENV
```

**Key components**
- **FastAPI service** exposing sync controls, health checks, and spatial endpoints
- **Admin portal** for job orchestration and monitoring
- **Async ETL pipeline** with rate limiting, validation, and sanitization stages

## License

Released under the MIT License. See `LICENSE` for details.
- **Scheduler and job tracking** with retries and execution history
- **PostgreSQL/PostGIS storage** optimised for spatial and analytic workloads

## Highlights

- Automated initial/backfill loads plus incremental syncs with progress tracking
- Batch ingestion (~50k rows per request) using connection pooling and COPY for heavy loads
- Spatial enrichment via PostGIS and shapefile lookups
- Dockerised local stack with reproducible Python environment
- Structured logging and metrics for observability

## Data Quality & Reliability

**Validation & sanitization**
- Geographic bounds, date parsing, age and vehicle year checks
- Duplicate pruning, Unicode handling, and whitespace cleanup

**Resilience**
- Circuit breaker with exponential backoff to respect API limits
- Partial failure recovery to keep ingestion moving
- Detailed error reporting to the job history tables

## API Surface

- `GET /sync/status` – Current sync status and last run time
- `POST /sync/trigger` – Manual sync trigger with optional date range
- `GET /health` – Service health check

## Documentation

- Run the docs locally:
  ```bash
  npm install
  npm run start
  npm run build
  ```
  `npm run build` outputs static assets in `src/static/documentation`, served by FastAPI at http://localhost:8000/documentation/.

- Reference guides:
  - **[API Reference](docs/API_REFERENCE.md)**
  - **[Development Guide](docs/DEVELOPMENT_GUIDE.md)**
  - **[Deployment Guide](docs/DEPLOYMENT_GUIDE.md)**
  - **[Troubleshooting Guide](docs/TROUBLESHOOTING.md)**

## Development

```bash
make install        # Install dependencies
make test           # Run tests
make lint           # Lint the codebase
make format         # Apply formatting
make docker-build   # Build Docker images
make migrate        # Run database migrations
```

```
chicago-crash-pipeline/
├── src/
│   ├── api/          # FastAPI service
│   ├── etl/          # ETL pipeline modules
│   ├── models/       # SQLAlchemy models
│   ├── validators/   # Data validation rules
│   ├── spatial/      # Spatial data handlers
│   └── utils/        # Shared helpers
├── migrations/       # Alembic migrations
├── tests/
├── config/
├── docker/
└── docs/
```

## Data Sources

- [Traffic Crashes – Crashes](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Crashes/85ca-t3if)
- [Traffic Crashes – People](https://data.cityofchicago.org/Transportation/Traffic-Crashes-People/u6pd-qa9d)
- [Traffic Crashes – Vehicles](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Vehicles/68nd-jvt3)
- [Vision Zero Fatalities](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Vision-Zero-Chicago-Traffic-Fatali/gzaz-isa6)

## Troubleshooting

**Import errors with relative imports**
- Run Python commands from the repository root so `src` stays on the path
- For ad-hoc scripts, add `sys.path.append("src")`

**Database connection issues**
- Confirm `.env` contains valid credentials
- Verify PostgreSQL/PostGIS is running and the `postgis` extension is enabled

**API rate limits**
- Default configuration respects the 1000 requests/hour cap
- Request a Chicago Data Portal token for higher throughput

**Large data loads**
- Tune the `batch_size` configuration and container memory for initial loads

## License

MIT License - see `LICENSE` for details.

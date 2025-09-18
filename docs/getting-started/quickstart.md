---
title: Quick Start
sidebar_position: 1
description: Set up a local Chicago Crash Data Pipeline environment and run the core services in minutes.
---

The Chicago Crash Data Pipeline ships with everything you need to run the REST API, admin portal, and ETL jobs locally. This guide walks through the fastest path to a working system.

## Prerequisites

- Python **3.11** or later (aligns with the production Docker image)
- PostgreSQL **15** with the PostGIS extension (or use the bundled Docker Compose services)
- Redis **7** (also bundled with Docker Compose)
- [Git](https://git-scm.com/) for source control
- Optional: [Make](https://www.gnu.org/software/make/manual/) for convenience commands

## 1. Clone the Repository

```bash
git clone https://github.com/MisterClean/chicago-crashes-pipeline.git
cd chicago-crashes-pipeline
```

## 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

If you plan to contribute code, also install the editable package and dev tools:

```bash
make dev-install
```

## 4. Configure Environment Variables

Copy the example environment file and adjust values as needed:

```bash
cp .env.example .env
```

At minimum set your database password (`DB_PASSWORD`) and optional Chicago Data Portal token (`CHICAGO_API_TOKEN`) for higher rate limits.

## 5. Provision the Database

If you have PostgreSQL running locally, ensure PostGIS is enabled:

```bash
createdb chicago_crashes
psql -d chicago_crashes -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

The API automatically runs `Base.metadata.create_all` on startup, so no migrations are required for an empty database. To apply future migrations use:

```bash
alembic upgrade head
```

## 6. Start the API & Admin Portal

```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/admin to access the admin portal UI. API documentation is available at http://localhost:8000/docs.

## 7. Run a Test Sync

With the API running you can trigger syncs either through the admin portal or directly via HTTP:

```bash
curl -X POST http://localhost:8000/sync/test
```

For full data pulls the CLI provides fine-grained control:

```bash
# Run a historical backfill starting on 2017-09-01
python -m src.cli.pipeline initial-load --start-date 2017-09-01

# Refresh the last 7 days of data across all endpoints
python -m src.cli.pipeline delta --window-days 7
```

The CLI relies on the same configuration as the API, including environment variables and `config/config.yaml`.

## 8. Optional: Start Everything with Docker Compose

If you prefer containers, use the bundled Compose stack which runs PostgreSQL, Redis, and the FastAPI service together:

```bash
docker compose -f docker/docker-compose.yml up --build
```

The application listens on port `8000`, PostgreSQL on `5432`, and Redis on `6379`. Logs stream to your terminal; use `-d` to run in the background.

## Next Steps

- Review the [Configuration Reference](configuration.md) to tailor API access, rate limits, and logging.
- Explore the [Admin Portal guide](../user-guides/admin-portal.md) for day-to-day operations.
- Learn how to deploy the stack using the [Operations Handbook](../operations/deployment.md).

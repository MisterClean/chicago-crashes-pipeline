---
title: Docker Compose
sidebar_position: 3
description: Launch PostgreSQL, Redis, and the FastAPI service with the bundled Docker Compose stack.
---

The repository ships with a Docker Compose file that provisions the complete stack for development or lightweight demos. It builds the FastAPI image from `docker/Dockerfile` and mounts your local source code for instant reloads.

## Services

| Service | Image | Ports | Purpose |
| --- | --- | --- | --- |
| `postgres` | `postgis/postgis:15-3.3` | `5432:5432` | PostgreSQL + PostGIS with initialization script `docker/init.sql` |
| `redis` | `redis:7-alpine` | `6379:6379` | In-memory cache and job coordination |
| `app` | Built from project root | `8000:8000` | FastAPI application serving the REST API and admin portal |

`app` mounts your local `src`, `config`, and `logs` directories. Code changes refresh automatically thanks to Uvicorn's `--reload` flag in the Compose command.

## Start the Stack

```bash
docker compose -f docker/docker-compose.yml up --build
```

- Use `-d` to run in detached mode.
- The first build installs Python dependencies inside the image; subsequent runs are fast.

## Environment Overrides

Edit the `environment` blocks in `docker/docker-compose.yml` or supply an env file:

```bash
docker compose --env-file .env -f docker/docker-compose.yml up
```

The `.env` file can reuse the same variables used for local development (`DB_*`, `CHICAGO_API_TOKEN`, etc.).

## Database Initialization

`docker/init.sql` creates the `chicago_crashes` database and enables PostGIS. If you need a clean reset:

```bash
docker compose -f docker/docker-compose.yml down -v
```

This removes the `postgres_data` and `redis_data` volumes.

## Useful Commands

```bash
# Tail API logs
docker compose -f docker/docker-compose.yml logs -f app

# Run migrations inside the container
docker compose -f docker/docker-compose.yml exec app alembic upgrade head

# Open a psql shell
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes
```

## Production Considerations

The provided Compose file targets local development. For production:

- Supply strong credentials via environment variables.
- Disable the `--reload` flag and mount volumes read-only or bake the code into the image.
- Front the API with a reverse proxy (e.g., NGINX or a cloud load balancer) for TLS termination.
- Add health-check monitoring and metrics scraping.

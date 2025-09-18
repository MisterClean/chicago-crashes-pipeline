---
title: Deployment Guide
sidebar_position: 2
description: Deploy the pipeline with Docker Compose or production-ready infrastructure.
---

This guide covers deployment patterns for the Chicago Crash Data Pipeline. Choose the approach that matches your hosting environment and operational maturity.

## Option 1: Docker Compose (Small Teams / Demos)

Use the repo's Compose stack for quick deployments on a single host.

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

Recommendations:

- Populate an `.env` file with strong credentials and pass it via `--env-file`.
- Remove the `--reload` flag from the `app` service command for production stability.
- Add a reverse proxy in front of the FastAPI container for TLS termination (NGINX, Traefik, Caddy).
- Configure host-level backups for the `postgres_data` volume.

## Option 2: Container Orchestrator (Kubernetes, ECS, Nomad)

1. Build and push the application image:

   ```bash
   docker build -t <registry>/chicago-crashes-api:latest -f docker/Dockerfile .
   docker push <registry>/chicago-crashes-api:latest
   ```

2. Provision managed PostgreSQL (with PostGIS enabled) and Redis. For AWS:
   - Amazon RDS for PostgreSQL (enable PostGIS extension)
   - Amazon ElastiCache for Redis

3. Deploy the API container with environment variables stored in Secrets/ConfigMaps. Mount the `config/config.yaml` file via a ConfigMap or baked into the image.

4. Expose port 8000 via an ingress controller or application load balancer.

5. Configure horizontal pod autoscaling based on CPU or request latency if you expect spikes during heavy sync windows.

## Option 3: VM / Bare Metal

- Install Python 3.11, PostgreSQL 15 + PostGIS, and Redis 7.
- Create a systemd service that runs `uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4` inside a virtual environment.
- Use `supervisord` or systemd timers to run scheduled sync jobs if you prefer OS-level scheduling over the built-in job scheduler (disable the internal scheduler by omitting it from startup).

## Deployment Pipeline Extras

| Concern | Recommendation |
| --- | --- |
| **Configuration** | Store `.env` values in a secret manager (AWS Secrets Manager, HashiCorp Vault, Doppler). Commit only non-sensitive defaults in Git. |
| **Database Migrations** | Run `alembic upgrade head` during release pipelines before starting new application instances. |
| **Logging** | Ship `logs/api.log`, `logs/etl.log`, and `logs/app.log` to a central aggregator (CloudWatch, ELK, Loki). |
| **Metrics** | Scrape `GET /health`, track sync durations via executed job metadata, and expose container metrics via cAdvisor or node exporter. |
| **Alerting** | Create alerts for failed executions, high job latency, database replication lag, and approaching SODA rate limits. |

## Zero-Downtime Tips

- Run multiple API instances behind a load balancer; the admin portal is static so it scales trivially.
- Coordinate job scheduler ownership (only one instance should run the scheduler). Use an environment flag or leader-election mechanism if you run multiple API replicas.
- Perform backfills during off-peak hours or on dedicated workers to avoid blocking routine incremental jobs.

## Deployment Verification Checklist

- [ ] `GET /health` returns `healthy`
- [ ] Admin portal loads and displays live job statistics
- [ ] Test sync (`POST /sync/test`) succeeds
- [ ] Database contains expected tables with PostGIS extension enabled (`SELECT PostGIS_full_version();`)
- [ ] Logs flow to the configured aggregation system

Once these checks pass you are ready to hand over the environment to operators and analysts.

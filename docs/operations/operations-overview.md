---
title: Operations Overview
sidebar_position: 1
description: Operational responsibilities for running the Chicago Crash Data Pipeline in production.
---

Operations teams oversee deployments, monitoring, spatial assets, and data lifecycle management. This chapter outlines the key tasks and recommended tooling.

## Core Responsibilities

- **Deploy & Upgrade** – roll out the FastAPI service, database migrations, and admin portal assets (see [Deployment](deployment.md)).
- **Monitor Health** – track API uptime, scheduler status, sync throughput, and data quality.
- **Manage Spatial Assets** – keep shapefiles and custom GeoJSON layers current.
- **Audit Data Loads** – verify record counts, investigate anomalies, and coordinate corrective actions.

## Monitoring Checklist

| Task | Tooling |
| --- | --- |
| API uptime & latency | Reverse proxy logs, Load balancer health checks, `GET /health` |
| Job scheduler progress | Admin portal dashboard, `GET /jobs/summary` |
| Execution failures | Admin portal toasts, `job_executions` table, alerting on `status = 'FAILED'` |
| Database health | `pg_isready`, Cloud provider metrics, disk utilisation alarms |
| External API quota | Chicago Data Portal account dashboard, application logs containing `rate limit` warnings |

Integrate key endpoints into your monitoring stack (Prometheus exporters, Datadog checks, etc.).

## Spatial Assets

Spatial data powers map overlays and joins. Maintain two sets of assets:

1. **Reference Shapefiles** – load official wards, community areas, precincts, etc. with `POST /spatial/load` or `make load-shapefiles`.
2. **Custom Layers** – upload curated GeoJSON via the admin portal when business users need bespoke boundaries.

When new shapefiles are released, place them in `data/shapefiles/` and re-run the loader. The loader replaces existing tables with fresh content.

## Backups & Disaster Recovery

- **Database Backups** – schedule regular `pg_dump` exports or rely on managed Postgres snapshotting.
- **Log Retention** – rotate `logs/*.log` off-host for compliance where required.
- **Config Snapshots** – version `config/config.yaml` changes via Git, and secure `.env` files using a secret manager.

## Incident Runbook

1. **Identify** – use alerts or portal signals to detect outages or data drift.
2. **Stabilise** – disable failing jobs in the portal to stop repeated failures.
3. **Diagnose** – inspect ETL logs, examine the offending batches, and verify upstream API status.
4. **Remediate** – re-run targeted jobs, backfill missing data, or roll back configuration changes.
5. **Review** – document the incident, compare observed behaviour with expectations, and update this runbook as needed.

Maintain strong communication between development and operations teams—most configuration changes require coordination to avoid unnecessary downtime.

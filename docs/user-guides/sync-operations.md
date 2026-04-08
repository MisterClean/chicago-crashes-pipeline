---
title: Sync Operations
sidebar_position: 3
description: Manage one-off and scheduled data synchronisation tasks.
---

The pipeline ingests crash data through two primary channels: **scheduled jobs** stored in the database and **manual runs** triggered via the CLI or API. This guide explains the available job types, how scheduling works, and how to monitor progress.

## Default Jobs

On startup (`src/api/main.py`) the application seeds a set of jobs defined in `src/models/jobs.py:get_default_jobs()`:

| Job Type | Description | Enabled | Recurrence |
| --- | --- | --- | --- |
| `full_refresh` | Complete backfill across crashes, people, vehicles, fatalities | Disabled | Manual |
| `last_30_days_core_data` | Rolling 30-day refresh for crashes, people, and vehicles in dependency order | Enabled | Daily |
| `last_30_days_people` | Legacy people-only 30-day refresh retained for manual use | Disabled | Daily |
| `last_30_days_vehicles` | Legacy vehicle-only 30-day refresh retained for manual use | Disabled | Daily |
| `last_6_months_fatalities` | Fatality refresh with a six-month window | Enabled | Weekly |

Adjust these defaults by editing `get_default_jobs()` or managing them from the admin portal.

## Manual Syncs via CLI

The CLI wraps the same sync service used by the API. Run commands from the project root with your environment configured.

```bash
# Historical backfill starting September 2017
python -m src.cli.pipeline initial-load --start-date 2017-09-01

# Rolling seven-day window (default) across all endpoints
python -m src.cli.pipeline delta

# Target specific endpoints with custom ranges
python -m src.cli.pipeline delta \
  --endpoints crashes people \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --batch-size 20000

# Backfill missing crash_date values on existing people rows
python -m src.cli.pipeline backfill-people-crash-dates \
  --batch-size 50000

# Re-sync historical people fields in dependency order after deploying the sanitizer fix
python -m src.cli.pipeline initial-load \
  --endpoints crashes people \
  --start-date 2017-09-01
```

CLI runs log progress to `logs/etl.log` and update the shared job execution history so the admin portal reflects manual operations.

## Manual Syncs via API

Trigger one-off runs without the CLI:

```bash
curl -X POST http://localhost:8000/sync/trigger \
  -H "Content-Type: application/json" \
  -d '{
        "endpoints": ["crashes"],
        "start_date": "2024-02-01",
        "end_date": "2024-02-15",
        "force": true
      }'
```

Use `GET /sync/status` to monitor state or poll the job executions list for completion.

## Monitoring Progress

- **Admin Portal** – displays running jobs, execution counts, errors, and duration charts.
- **Logs** – monitor `logs/api.log` and `logs/etl.log` (or container logs if using Docker).
- **Database** – inspect `job_executions` and `job_execution_logs` tables for historical data.

## Handling Failures

1. Review the execution modal or API response for stack traces.
2. Check the ETL log for the specific batch that failed (look for `error` entries keyed by `sync_id`).
3. Restart the job with `force=true` to bypass idempotency guards when safe.
4. If data corruption occurred, use the [Data Management](admin-portal.md#data-management) tools to delete affected ranges before re-running.

## Best Practices

- Keep the default rolling jobs enabled to minimise the size of manual refreshes.
- Use smaller `batch_size` values during daytime hours to respect SODA API rate limits.
- Store your `CHICAGO_API_TOKEN` in `.env` to unlock significantly higher throughput.
- Schedule heavy backfills during off-peak hours to reduce contention with production workloads.
- Repairing legacy people data is a two-step process: backfill `crash_date` from `crashes`, then run a historical `crashes -> people` sync to repopulate source-backed fields like `vehicle_id`, `driver_action`, and `driver_vision` without hitting foreign key violations.

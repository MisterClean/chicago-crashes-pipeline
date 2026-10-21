# Fresh portal facts with the existing uploaded boundaries

This procedure creates fresh facts from the Chicago portal's complete CSV exports and preserves the existing uploaded boundary catalog. It does not import PostgreSQL crash rows or historical operational state. Keep the old service and its data available until the replacement has passed verification and the agreed rollback window has ended.

The temporary [bootstrap configuration](../docker/railway.bootstrap.toml) builds the normal Rust image but starts `crashes-bootstrap`. This process gives `/data` private permissions, initializes its ownership and waits as UID/GID 10001. It starts no DuckDB connection, HTTP listener, ingestion worker or scheduler. The normal root `railway.toml` remains unchanged.

## Capture only the uploaded boundaries

Freeze boundary edits during the final capture and import. Supply `PG_MIGRATION_URL` securely to the capture process, with an optional trusted PEM `PG_MIGRATION_CA_CERT`. Use verified TLS and a read-only PostgreSQL role. The command opens a repeatable-read, read-only transaction and captures layer metadata, feature properties and original WKB; it does not copy crash facts or operational tables.

Choose a new private local directory:

```sh
umask 077
target/release/crashes-server export-postgres-layers \
  --output .local/boundary-cutover \
  --allow-production-read
```

The result's `boundaries/manifest.json` and associated files belong together. Record the layer and feature counts, original IDs, labels, sorting, timestamps, hashes and capture receipt. Transfer the complete `boundaries` directory through an authenticated private channel to `/data/bootstrap/boundaries` on the replacement service. Do not expose it through a public bucket or put connection URLs, access keys or signed transfer URLs in Git or logs.

## Start the private hold

Use one replacement backend replica with one persistent volume mounted at `/data`. Select `/docker/railway.bootstrap.toml` as its temporary config file. Leave public domains and TCP proxies detached. Clear any existing service-level healthcheck path: this TOML intentionally contains no `healthcheckPath`, and omitting it does not establish readiness for an HTTP server. Disable service sleeping while performing SSH maintenance.

The deployment's expected log is `Private bootstrap hold ready as uid/gid 10001; HTTP and scheduling are stopped.` No `/ready` endpoint exists in this phase. The image retains its normal Docker healthcheck for regular serving; a standalone local hold test should use Docker's `--no-healthcheck`. Railway's activation checks are configured separately by its service healthcheck path, as described in [Railway healthchecks](https://docs.railway.com/deployments/healthchecks) and [custom config files](https://docs.railway.com/config-as-code).

Set backend service variables through the platform's secret/configuration manager:

| Variable | Bootstrap and initial private verification |
| --- | --- |
| `DATA_DIR` | `/data` |
| `APP_ENV` | `production` |
| `BIND_ADDRESS`, `PORT` | `0.0.0.0`, `8000` for the later serving phase |
| `DAILY_SYNC` | `false` until source publication, boundaries and backup are verified |
| `DUCKDB_MEMORY_LIMIT`, `DUCKDB_THREADS` | `192MB`, `2` |
| `PUBLIC_CACHE_BYTES` | `16777216` |
| `API_KEY` | New cryptographically random server/admin secret, at least 32 bytes |
| `EXPORT_ENDPOINT`, `EXPORT_BUCKET` | Private S3-compatible endpoint and bucket |
| `EXPORT_ACCESS_KEY_ID`, `EXPORT_SECRET_ACCESS_KEY` | Private bucket credentials |
| `EXPORT_REGION` | Provider region; `auto` when supported |
| `EXPORT_ADDRESSING_STYLE` | Omit for virtual-host addressing; `path` only when required by the provider |

Set an outer memory limit and reserve disk for all source CSVs, the database, native spill, exports and a paired backup. A 192 MB SQL buffer does not bound process or cgroup memory. Source download limits must accommodate the real complete exports; do not replace a rejected input with a subset or enable profiling mode to pass a gate.

Open an SSH session using explicit generic targets; obtain their values from the operator's current project context:

```sh
railway ssh --project "$RAILWAY_PROJECT" \
  --environment "$RAILWAY_ENVIRONMENT" --service "$RAILWAY_SERVICE"
```

Run maintenance commands as the application user even if the SSH shell is root. Use a persistent SSH/tmux session for long downloads or inspect the saved receipts after reconnecting. Never run two database owners against the same volume.

## Download, seed, import and back up

Inside the hold container, download complete CSVs; `download` without `--api` selects the bulk CSV path:

```sh
gosu 10001:10001 /usr/local/bin/crashes-server download \
  --directory /data/bootstrap/sources \
  --datasets crashes,people,vehicles,fatalities

gosu 10001:10001 /usr/local/bin/crashes-server seed \
  --source-dir /data/bootstrap/sources \
  --datasets crashes,people,vehicles,fatalities \
  --operation-id fresh-portal-cutover

gosu 10001:10001 /usr/local/bin/crashes-server import-layers \
  --snapshot /data/bootstrap/boundaries

gosu 10001:10001 /usr/local/bin/crashes-server backup \
  --output /data/backups
```

Inspect every command's exit status and durable receipt before proceeding. Downloads must pass schema, content hash, row-count and stable source-revision checks. The seed must publish all four datasets with `production_complete=true` and `profiling_only=false`; do not pass `--profiling`. Complete CSV exports are acquired independently and do not establish one cross-dataset snapshot. Reusing the same operation ID is only appropriate for replaying the same verified inputs.

If a portal CSV lags behind the API and fails the count proof, keep that attempt quarantined for review. Use `download --api --directory /data/bootstrap/sources-api --datasets crashes,people,vehicles,fatalities` to acquire complete datasets in a new directory, then seed from that directory. This ordered API fallback still requires exact counts and a stable revision; never use a partial CSV as production data. Allow sufficient volume capacity for a rejected bulk attempt and its replacement.

Seed initializes an empty spatial catalog. Boundary import accepts that empty initialized catalog and refuses to overwrite populated catalog tables. Verify the imported layer/feature counts against the capture, including exact IDs, WKB geometries, properties, labels, active flags, sort order and timestamps. A previously populated or partially failed candidate needs explicit recovery; do not delete its catalog to make an import pass.

The backup command checkpoints and verifies paired DuckDB/SQLite files and publishes a manifest only after successful verification. With the configured private storage, require a successful remote backup receipt under the separate `backups/` object prefix. Retain the verified boundary archive and source receipts through cutover. Only clean up the dedicated source staging directory after successful publication, boundary verification and backup.

For a replacement-volume drill, retrieve one complete paired snapshot privately into a new directory and run `crashes-server --data-dir NEW_EMPTY_DIRECTORY restore --snapshot SNAPSHOT_DIRECTORY`. Restore refuses populated or live targets; an interrupted restore must resume from the same snapshot. Verify the restored facts, layers and operational state before relying on that recovery path.

## Verify privately, then change traffic

Change the service config path back to `/railway.toml`, preserving the same volume and one replica. Keep `DAILY_SYNC=false` and networking private during verification. The normal start command serves the application and `/ready` checks the imported production data. Wait for the exact submitted deployment to succeed and verify `/health`, `/ready`, fact counts, uploaded places, a location report, the admin execution history and one signed private export. Fresh portal counts may differ from the retired database; compare against the validated source receipts rather than expecting historical database parity.

Build the frontend with `BACKEND_URL` pointing to the replacement backend's private hostname and port, and `NEXT_PUBLIC_API_URL=/api`. Set `BACKEND_URL` both during the build and at runtime. Basemap precedence is explicit `NEXT_PUBLIC_BASEMAP_URL`, then browser-visible `NEXT_PUBLIC_PROTOMAPS_KEY`, then keyless CARTO Positron. Keep the style URL empty when selecting Protomaps by key; both are build-time values and require a rebuild after changes. Never expose the backend `API_KEY` as a `NEXT_PUBLIC_*` value.

After private checks pass, switch the frontend/backend routing and verify the public pages and authenticated export flow. Enable daily scheduling in two explicit steps: the initial `DAILY_SYNC=false` startup persists `scheduler_enabled=false`, and a later startup with `DAILY_SYNC=true` installs the defaults without clearing that operator pause.

1. Set `DAILY_SYNC=true` and restart/redeploy the normal backend. Wait for that deployment's readiness check. While the persisted scheduler gate is still stopped, review the default jobs through authenticated `GET /jobs` and `GET /jobs/schedules`; retain the documented holds on unsupported historical correction jobs.
2. From a trusted backend maintenance shell with the existing `API_KEY` available, explicitly start future schedule dispatch and read its persisted status. These administrative routes require the `X-API-Key` header; do not put the key in a URL or a public frontend variable.

   ```sh
   BASE_URL="http://127.0.0.1:${PORT:-8000}"
   printf 'X-API-Key: %s\n' "$API_KEY" | \
     curl --fail-with-body --silent --show-error --header @- --request POST \
       "$BASE_URL/jobs/scheduler/start"
   printf 'X-API-Key: %s\n' "$API_KEY" | \
     curl --fail-with-body --silent --show-error --header @- \
       "$BASE_URL/jobs/scheduler/status"
   ```

   Require `scheduler_enabled=true`, `is_running=true` and `status="running"`. A successful start enables checking due jobs on the next worker tick; it does not require a job to be running immediately.

3. Observe the first due daily publication through authenticated `GET /jobs/executions` and any linked admin execution history. Require a completed durable publication receipt for the intended endpoints/window and matching processed/inserted/updated/skipped counters; a valid no-change run may have zero inserts and updates. Investigate a failed, held or missing publication before considering daily updates operational.

Retire old services only after the first daily publication, rollback and backup requirements are met.

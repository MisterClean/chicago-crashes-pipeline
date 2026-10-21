# Migration and operations

The application runs one Rust backend owner with DuckDB 2.0.0 facts/boundaries and SQLite operational state. Next.js is the frontend. Use the [README](../README.md) for installation and a new portal bootstrap.

## Runtime invariants

- Run one backend process and one replica per persistent data directory. An OS owner lock and DuckDB's file lock reject a second owner. Never mount the same writable database into independent workers.
- Queries share a serialized SQL lane, two SQL threads, a default 120-second statement deadline and a 4 GB spill ceiling. The CLI defaults to a 256 MB buffer; the production image uses 192 MB. Buffer budgets and total process RSS are different limits.
- Facts, publication receipts and source checkpoints commit transactionally. An immutable operation ID reconciles a crash between DuckDB publication and SQLite job completion before work is repeated.
- Public caching defaults to a 300-second TTL, 16 MiB total payloads, 4 MiB per entry and 256 entries. Mutations invalidate cached reads. Operational routes, exports and errors are not cached. `PUBLIC_CACHE_BYTES=0` disables the cache for measurements.
- Crash timestamps are Chicago local wall time. Operational timestamps and source modification checkpoints are UTC. Radius selection uses WGS84 spheroid distance with longitude/latitude axes. Polygon selection excludes edges and holes.
- Report totals and export membership use the full selection. Only report map points are capped at 5,000.

## Preserve an existing deployment

Capture a consistent read-only PostgreSQL snapshot when replacing an existing installation. Independent current portal exports can have different historical rows, null person dates, source corrections or fatality identities. The importer preserves captured values instead of applying current sanitization again.

Drain the old ingestion/export writers before the final capture. Supply `PG_MIGRATION_URL` through a secure environment manager and optionally `PG_MIGRATION_CA_CERT` for a trusted PEM CA. Use verified TLS with a valid hostname and a read-only capture role. Never put a live connection URL in documentation, Git or command history.

From the repository root, with those variables already set:

```sh
target/release/crashes-server --data-dir .local/capture-tool \
  export-postgres-snapshot --output .local/cutover-snapshot \
  --allow-production-read

target/release/crashes-server --data-dir .local/candidate \
  import-fact-snapshot --snapshot .local/cutover-snapshot
target/release/crashes-server --data-dir .local/candidate \
  import-layers --snapshot .local/cutover-snapshot/boundaries
target/release/crashes-server --data-dir .local/candidate \
  import-legacy-control --snapshot .local/cutover-snapshot
```

The capture verifies `REPEATABLE READ` and `READ ONLY`, streams COPY into typed Parquet, and publishes its manifest last. Facts, original boundary WKB and metadata, schedules, execution history, configuration, checkpoints and completed artifact pointers come from that transaction. Snapshot directories/files are created with private permissions.

Import validates containment, hashes, counts, physical types and metadata. Existing targets are not overwritten. Active legacy jobs require draining or explicit resolution. Unknown recurrence types and fabricated source checkpoints fail for review. Boundaries retain their original IDs, properties, labels, sorting and timestamps.

Compare all authoritative table counts and relevant metrics, exact boundary geometries and labels, retained history and artifact access before changing traffic. A profiling CSV import does not establish that parity.

## Schedules and publication guards

Automatic scheduling is off in the local CLI; the production image sets `DAILY_SYNC=true`. Review imported jobs, enabled states, next-run times, retries and timeouts before enabling it. `DAILY_SYNC=false` keeps scheduling off. An operator's pause and intentional schedule removals survive restart. Defaults install once for an empty operational store; imported schedules do not acquire duplicates.

The daily core job uses a 30-day event-date API window for crashes, people and vehicles. It preserves historical null person dates and enforces the default 25,000 changed-row publication guard. A date window does not prove full historical completeness or advance a global modification watermark.

Fatality incremental updates require an actual source-update checkpoint. Core modification-watermark jobs and historical person-date repair remain held until a reviewed baseline/policy is provided. `force` does not bypass holds, disabled flags or the change guard. Empty or unstable API windows do not erase facts.

The audited [mapping](../rust/crashes-server/resources/csv_column_mapping.json) owns CSV display-header/API-name/type conversion. Downloads validate schema, transport, content hashes, counts and source revisions. New or renamed columns fail for review. Successful staging is removed after durable publication; source disk budget, retention and attempt counts are bounded.

## Boundaries and uploads

A new portal seed creates an empty spatial catalog. Existing migrations import the captured catalog. Use `/admin` to preview label fields and upload GeoJSON or a complete zipped shapefile. Shapefile archives require `.shp`, `.shx`, `.dbf` and `.prj`; GDAL must be available on `PATH`.

GeoJSON/ZIP validation rejects unsafe paths, symlinks, unsupported geometry, missing components and oversized expansion. Foreign CRS and shapefile conversions use a bounded GDAL process with a deadline, finite output and process limits. Labels and properties are treated as text in the embedded admin UI.

## Production configuration

The root `railway.toml` builds `docker/Dockerfile.rust`, starts the entrypoint wrapper and checks `/ready`. The image uses one Rust owner, the pinned native engine, GDAL and system CA certificates. The wrapper initializes mounted-volume ownership as needed and drops to UID 10001. For fresh portal CSV facts while retaining uploaded boundaries, follow the [private bootstrap procedure](railway-bootstrap.md).

Required settings:

| Setting | Purpose |
| --- | --- |
| `APP_ENV=production` | Enforces production startup checks |
| `DATA_DIR=/data` | Persistent volume containing imported facts and operational state |
| `API_KEY` | Secret of at least 32 bytes |
| `EXPORT_ENDPOINT`, `EXPORT_BUCKET` | Private S3-compatible delivery and recovery storage |
| `EXPORT_ACCESS_KEY_ID`, `EXPORT_SECRET_ACCESS_KEY` | Bucket credentials |
| `EXPORT_REGION` | Bucket region; default `auto` |
| `DAILY_SYNC` | Enable only after reviewing imported schedules |

The image's starting buffer configuration is `DUCKDB_MEMORY_LIMIT=192MB`, `DUCKDB_THREADS=2` and a 16 MiB response cache. Do not use a 128 MB buffer with exports: it is smaller than an observed native allocation. The local low-traffic trial passed with a 512 MiB backend cap, but reached that cap with reclaim pressure. Validate the actual host architecture, storage, traffic and upload envelope before selecting limits.

Serve the frontend separately with a private `BACKEND_URL` and `NEXT_PUBLIC_API_URL=/api`. Set `BACKEND_URL` when building and at runtime; changing it requires rebuilding compiled rewrites. `NEXT_PUBLIC_BASEMAP_URL` optionally selects a public style at build time. No server secret belongs in a `NEXT_PUBLIC_*` setting.

Readiness performs database checks and can wait behind a heavy query. Liveness `/health` avoids that SQL work. Keep health timeouts/retry windows consistent with the workload. Retain a finite outer container memory limit and enough disk for source staging, native spill, pending exports and a paired backup; the SQL buffer setting does not bound all allocations.

## Exports and recovery

Exports freeze submitted geometry, read a consistent transaction, stream schema-v1 CSVs and ZIP compression, verify artifact size/hash, then publish an attempt-fenced pointer. Queue size, rows, bytes and duration are bounded. Production uses private signed S3 downloads. Local development can use short-lived signed local downloads. Leases, retries, cancellation, expiry and restart fencing are durable.

Full paired snapshots are scheduled daily and after journaled data/layer changes when offsite storage is configured. Hourly SQLite copies retain smaller operational state. Remote retention keeps seven full and 48 hourly snapshots; one completed full snapshot remains locally after offsite publication. Cleanup scans bounded pages of expired attempts and unpublished objects.

```sh
target/release/crashes-server --data-dir .local/candidate \
  backup --output .local/backups
# Replace SNAPSHOT_ID with the identifier from the completed backup receipt.
target/release/crashes-server --data-dir .local/restore-drill \
  restore --snapshot .local/backups/SNAPSHOT_ID
target/release/crashes-server --data-dir .local/restore-drill inspect
```

Backup holds the owner lock over checkpoint, fact-file copy and SQLite's online backup. Manifests publish after file verification. Restore verifies both files, refuses an occupied/live target, fences restored leases and records an interruption marker until both files are installed. An interrupted restore can resume only from that same verified snapshot.

Use the paired full snapshot for automatic recovery. Combining an hourly control file with older facts needs explicit publication reconciliation; it is not an automatic restore path. Rehearse recovery against the actual replacement volume and private bucket before cutover.

## Release and rollback

1. Build and test the candidate without modifying the running deployment.
2. Drain old writers, capture/import the authoritative snapshot and review schedules.
3. Run facts/layers/operational parity and a replacement-volume recovery drill.
4. Observe freshness, failed jobs, first-visitor reports, exports, disk and metered resource use.
5. Change traffic only after validation; retain the old database and revision during the rollback window.

The [recorded measurements](research/rust-migration-results-2026-10-21.md) establish local feasibility, not a production bill or latency SLO. Service consolidation, bounded work, daily scheduling and response caching are the cost pathway. A Rust rewrite alone does not establish lower native analytics memory.

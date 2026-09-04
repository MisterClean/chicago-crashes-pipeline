# Durable location-report exports

The API queues an export in PostgreSQL and returns immediately. A worker reads one
consistent PostgreSQL snapshot, writes CSV/ZIP to temporary disk, uploads the final
artifact to private S3-compatible storage, verifies its length/checksum metadata,
and publishes the download. The browser obtains a signed URL and downloads directly
from storage, without buffering the archive in JavaScript.

## API contract

All `/exports` routes require the existing API authentication.

- `POST /exports`: existing `LocationReportExportRequest` JSON; returns HTTP 202
  with `id`, `status`, `created_at`, `expires_at`, `error`, `manifest`, `download_url`.
- `GET /exports/{id}`: poll the same representation. Status is `queued`, `running`,
  `completed`, `failed`, or `expired`.
- `GET /exports/{id}/download`: authenticated request returns `{ "url": "https://..." }`.
  Navigate the browser to this signed URL. It expires after at most five minutes
  and never exceeds the job retention deadline. Not ready returns 409; expired
  returns 410. Polling status never returns storage credentials.

Single datasets produce CSV; multiple datasets produce ZIP containing CSV files and
`manifest.json`. The status response includes the manifest in either case. It records
filters, a snapshot identifier, row counts, per-file SHA256, byte counts and schema
version. Public columns are explicitly listed in `EXPORT_COLUMNS`; internal ORM
columns do not silently become part of downloaded data.

Named places are resolved and frozen at submission. The worker preserves their
`ST_Contains` boundary semantics. Other selections share the dashboard's date/radius/
polygon helpers. Rows with missing geometry cannot appear in a spatial export.

## Worker integration

Import `ExportJob` before database schema setup/migration. Include the `exports`
router in FastAPI and protect its prefix. Run `process_one_export_job()` from the
separate worker, and call `cleanup_expired_exports()` periodically. Both return
without work when storage is unconfigured. These are synchronous functions; do not
call them directly on the API event loop.

Claims use PostgreSQL `SKIP LOCKED`, an advisory transaction lock for global queue
capacity/concurrency, and renewable leases. Every attempt gets a unique token and
object key. A stale worker cannot publish after its lease is lost or overwrite a
replacement's object. Interrupted jobs are reclaimed up to the attempt limit.
Temporary directories are cleaned in `finally` context management. Failed uploads
are deleted; expiry cleanup additionally sweeps old objects under the reserved
`exports/` prefix to recover objects orphaned by killed processes.

Reserve the bucket's `exports/` prefix exclusively for this feature. Cleanup marks
expired job records and deletes their objects; audit records remain in PostgreSQL.
An old-objects sweep checks each candidate against the job record before deletion,
retaining unexpired queued/running/completed jobs even if retention settings change.

## Railway configuration

Set these variables on API and export worker using Railway references to bucket
credentials (never commit values):

| Variable | Default / meaning |
| --- | --- |
| `EXPORT_ENDPOINT` | Required S3 endpoint |
| `EXPORT_BUCKET` | Required actual S3 bucket name |
| `EXPORT_ACCESS_KEY_ID` | Required credential |
| `EXPORT_SECRET_ACCESS_KEY` | Required credential |
| `EXPORT_REGION` | `auto` |
| `EXPORT_LEASE_SECONDS` | `180`; heartbeat every third of this interval |
| `EXPORT_TIMEOUT_SECONDS` | `1800`; generation deadline / SQL statement timeout |
| `EXPORT_RETENTION_HOURS` | `24`, measured from submission |
| `EXPORT_MAX_ATTEMPTS` | `3` |
| `EXPORT_MAX_PENDING` | `100` queued/running jobs |
| `EXPORT_MAX_CONCURRENT` | `1` across all export workers |
| `EXPORT_MAX_ROWS` | `5000000` **per dataset** |
| `EXPORT_MAX_BYTES` | `2000000000` total uncompressed CSV bytes |

Allow enough ephemeral worker disk for CSVs plus their ZIP. A citywide all-time people
export may exceed the default row limit: either raise it after measuring resources
or request yearly partitions. Size checks run every 2,000 rows and on file completion,
so an intermediate write can exceed the configured budget by a batch before aborting.
Upload duration also depends on SDK request timeouts; the deadline is checked before
and after upload. No public bucket policy is required. SDK uses virtual-host addressing.

Keep API/worker/PostgreSQL on Railway private networking. Railway buckets use their
public S3 endpoint; worker upload counts as service egress, while direct bucket
downloads have free bucket egress under current Railway billing.

## Consistency and caching limits

Queries use a read-only REPEATABLE READ transaction and server-side cursors fetching
2,000 rows at a time. Tests verify that an update committed between two dataset reads
does not leak into the export. The selected-crash CTE is materialized separately per
query; no unbounded Python list of IDs is created.

A PostgreSQL snapshot is not an immutable ingestion release. If ingestion has already
partially committed when the export begins, that committed state is what it sees.
`data_version` is deliberately null and request hashes do **not** enable cache reuse.
A reliable cache needs an atomic published generation shared by ingestion, reporting
and export. Once available, cache on normalized filters + generation + schema version.

## Verification

`tests/test_durable_exports.py` uses a fresh isolated schema per test. Set
`EXPORT_TEST_DATABASE_URL` to a disposable PostgreSQL/PostGIS instance and run:

```sh
venv/bin/python -m pytest tests/test_durable_exports.py -q
```

Tests cover spatial relationship filtering, consistent snapshots, leases and stale
worker fencing, byte bounds, successful publication/expiry, and failed uploads.
Storage transport is replaced in worker tests; real bucket delivery requires a
separate deployment smoke test before enabling the frontend feature.

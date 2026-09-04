# Hybrid ingestion and durable workers

Branch: `codex/hybrid-ingestion-worker-exports`. These changes are implemented and
locally verified; they have not been deployed to production.

## What changes

Full refreshes stream the portal CSV exports, apply the checked-in display-header
to API-field mapping, normalize records, and COPY into PostgreSQL staging tables.
The loader verifies source revision/count, headers and primary keys before atomic,
parent-first publication across the requested datasets. Set-based upserts update
only changed rows. It does not delete records absent from the source.

Full refresh establishes a checkpoint and immediately catches up source changes
through SODA. Incrementals use bounded `:updated_at, :id` keyset pagination with a
five-minute overlap, rather than filtering on the crash event date. An initial full
refresh is required for each endpoint. If catch-up fails, the validated full
publication remains available and the checkpoint supports a later retry. Historical
window commands continue to use API mode. Inclusive end dates include the whole day.

The API queues work in PostgreSQL. Dedicated workers claim with leases, retry within
configured budgets and enforce execution deadlines in supervised child processes.
A child watchdog exits if its lease is lost. A database advisory lock serializes
publication. API requests no longer host multi-hour ingestion jobs.

Exports use a separate durable queue, a consistent database snapshot, bounded-memory
CSV/ZIP generation and private object storage. The frontend polls and downloads from
a short-lived signed URL. The former inline export route returns 410; deploy frontend
and backend together. See [export configuration](durable-exports.md).

The report adds an hour/day heatmap and road-user injury table from the complete
filtered selection. Monthly charts now cover the selected date range, including
zero months and partial-month indicators. Map truncation is explicitly labelled.

## Railway activation sequence

1. Take a database backup and rehearse the migration against a restored staging
   database. Inspect `alembic current` and existing tables first: older deployments
   may have used `create_all` without an Alembic revision. Do not blindly stamp an
   existing database. Reconcile its baseline before `alembic upgrade head`.
   New revision `b73a91d8e402` adds checkpoints, exports and execution leases; it
   tolerates pre-existing legacy job tables.
2. Stop old ingestion execution and disable the API scheduler during the coordinated
   cutover. Set `JOB_SCHEDULER_ENABLED=false` on the API (also the new default).
   Do not run old inline workers concurrently with the new publisher.
3. Deploy the API and two services from the same revision. Select
   `railway.worker.toml` for ingestion and `railway.exports.toml` for exports.
   Worker services have no HTTP health endpoint or public domain. Supply the same
   database configuration through Railway private networking. Start with one replica
   per lane. Separate lanes prevent a full refresh delaying exports.
4. Provision a private Railway bucket and wire `EXPORT_*` credentials on the API
   and export worker as described in the export guide. Verify an actual small upload,
   signed download and expiry cleanup in staging. Storage tests use a fake transport;
   live bucket delivery has not been verified by the local suite.
5. Bootstrap a full refresh for all four endpoints via a queued full-refresh job
   (`POST /sync/trigger` with `{"mode":"full"}`), then verify the catch-up and
   checkpoint before enabling incremental schedules. Existing customized window jobs
   retain their configuration; review their modes explicitly. Full refresh jobs
   should have timeouts sized for observed portal download and database merge time.
6. Deploy the matching frontend. Exports retain API-key authentication; the report
   accepts a key in memory for export requests. Confirm the intended public/private
   access policy before exposing downloads to unauthenticated site visitors.

For manual maintenance, `python -m src.cli.pipeline full-refresh` and `incremental`
run directly. Prefer queued jobs in production for leases and durable execution
history. Optional `INGESTION_ARCHIVE_DIR` retains validated CSVs and provenance on
a mounted volume; without it downloads are temporary. Set a retention policy for
that volume. Ensure workers have disk for staging CSVs plus ZIPs, and PostgreSQL
has room for staging tables, indexes and WAL during full publication.

## Verification and performance

The production Docker image passed 200 Python tests, including real PostGIS tests
for atomic rollback, spatial filtering, snapshot consistency, leases and migrations.
Frontend production build and two export-client tests passed. Browser QA used a
synthetic 500-crash dataset; no synthetic records were written to production.
The actual incremental client was read-only probed against all four portal datasets.

A single local synthetic 5,000-row trial compared the old per-record ORM algorithm
with COPY publication: initial load 26.49s to 1.07s; unchanged refresh 39.91s to 0.53s;
changed refresh 32.52s to 1.29s. Stored-data hashes matched in all three phases.
These timings isolate database loading, exclude portal transfer, and are not a
prediction of the production full-refresh duration. Reproduce with
`scripts/benchmark_ingestion.py`; it requires a disposable test database.
Detailed evidence lives in `docs/research/2026-09-04-data-engineering-review/`.

## Remaining deliberate limits

Source deletions are not propagated. Source revision changes during a CSV download
abort rather than publish an uncertain snapshot. Invalid keys/schema changes abort
rather than silently drop rows. Individual source datasets do not offer one shared
transactional snapshot, although local publication is atomic. Common-download caches
and prebuilt citywide artifacts await an explicit immutable publication version.
Measure production download, normalization, COPY and merge timings before setting
refresh targets or increasing concurrency. No Dagster or additional queue broker is
required for this implementation.

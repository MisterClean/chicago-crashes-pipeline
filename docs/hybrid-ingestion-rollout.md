# Hybrid ingestion and durable workers

Branch: `codex/hybrid-ingestion-worker-exports`. These changes are implemented and
deployed to production for the API, export worker and frontend. Ingestion activation is in progress on the existing 5 GB Hobby volume.

## What changes

Full refreshes stream the portal CSV exports, apply the checked-in display-header
to API-field mapping, normalize records, and validate them in a worker-local SQLite spool. Publication uses COPY through reusable PostgreSQL temporary tables capped at 5,000 rows.
The loader verifies source revision/count, headers and primary keys before atomic,
parent-first publication across the requested datasets. Set-based upserts update
only changed rows. It does not delete records absent from the source.

Full refresh establishes a checkpoint and immediately catches up source changes
through SODA. The three large datasets use bounded `:updated_at, :id` keyset pagination with a
five-minute overlap, rather than filtering on the crash event date. The small
fatalities dataset is re-read through SODA to detect conflicting identities across
the full source: 25 missing-ID rows and nine rows with four reused IDs were
explicitly excluded from its 1,048-row rollout rehearsal. Existing ambiguous
destination rows remain unchanged. The validation manifest records exclusions. An initial full
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
3. Deploy the API and two services from the same revision. Configure the ingestion service start command as
   `python -m src.worker --lane ingestion` and the export service as
   `python -m src.worker --lane exports`, both using `docker/Dockerfile`.
   Railway now rejects opting new services into legacy TOML configuration; deploy
   workers from a clean package without those files and retain these settings on
   the services (or migrate the whole project to reviewed Railway IaC).
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
has room for changed rows, indexes and WAL during full publication. Set `INGESTION_MAX_CHANGED_ROWS=25000` on the constrained production ingestion worker: a complete insert/update count runs before destination mutation. This is a row guard, not a byte guarantee. Unchanged rows are filtered before conflict handling to avoid unnecessary tuple locks and WAL. Worker scratch files are removed when supervised jobs exit. The existing `copy` timing currently measures spool serialization; PostgreSQL COPY is included in publication timing.

## Verification and performance

The production Docker image passed 209 Python tests, including real PostGIS tests
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
abort rather than publish an uncertain snapshot. Schema changes and invalid keys in the main crash datasets abort publication.
The small curated fatalities dataset has explicit missing/conflicting-identity
rejection accounting; source limitations and retained legacy rows are recorded in
its validation manifest. Individual source datasets do not offer one shared
transactional snapshot, although local publication is atomic. Common-download caches
and prebuilt citywide artifacts await an explicit immutable publication version.
Measure production download, normalization, COPY and merge timings before setting
refresh targets or increasing concurrency. No Dagster or additional queue broker is
required for this implementation.

## Production storage maintenance (2026-09-04)

The three main tables contain 5,719,379 rows. Before maintenance they occupied
3,801 MiB including 1,593 MiB of indexes. A verified 453,526,232-byte custom
backup was saved in the private bucket at `backups/2026-09-04/pre-hybrid-rollout.dump`
(SHA-256 `ee599bda2792b8934677b573939bee3635ca825b76a2dd0bf80c77a7fb505741`).
Migration `c94f5a271d08` removes unused latitude/longitude B-tree indexes while
retaining the spatial GiST index, and lowers autovacuum/analyze thresholds.
Production migration and VACUUM ANALYZE reclaimed 85 MiB of files and made dead
row space reusable; database size became 3,804 MiB. No plan upgrade was made.
The 128-character source crash identifier repeated across parent and child
records and their indexes is a substantial remaining cost. Replacing internal
join keys with bigint IDs is a future migration, not part of this release.

Production export queue/worker/bucket/signed-download smoke passed with a ZIP
containing one crash, two people, two vehicles and a manifest. Browser QA of
the Loop report reconciled the heatmap total to the summary (3,652 crashes).

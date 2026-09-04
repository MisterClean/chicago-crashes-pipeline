# Hybrid ingestion and durable workers

Branch: `codex/hybrid-ingestion-worker-exports`. These changes are implemented and
deployed to production for the API, export worker, frontend and ingestion worker. The existing 5 GB Hobby volume is retained. Routine schedules are active; the large historical people backfill is held as described below.

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

The production Docker image passed 215 Python tests, including real PostGIS tests
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

A separate local restore of the production backup loaded all 5,719,379 core
records and rebuilt their indexes into a 3,126 MiB database (including the old
coordinate indexes). This suggests about 678 MiB of additional compaction
potential relative to production after maintenance. The only restore warning
was an incompatible `topology.topology.useslargeids` extension column on the
older local PostGIS image; the source topology table is empty. A real cutover
must use the matching production PostGIS version and validate all objects.
No production rebuild or source-ID migration has been performed.

Ingestion worker revision `c08b80a` deployment
`dcd66004-5ed7-47b2-88ea-427488cb211e` reached SUCCESS. First full refresh
execution `exec_6_c18061bd1dfa41e79b363b9fa0ed2aa9` validated all sources but was stopped by the mutation guard. Its pending retry was explicitly cancelled before publication.

### Bootstrap result and active operating mode

The full-source comparison found 2,276,795 proposed changes: crashes 188 new /
1,279 updated; people 1,446 new / 2,271,554 updated; vehicles 1,312 new / 2
updated; fatalities 1 new / 1,013 updated. The 25,000-row guard rejected this
publication before destination writes. Production has 2,274,426 person records
with null crash_date and 2,278,016 with null vehicle_id; a 30-record CSV sample
confirmed these and some driver fields are now available from the portal. This
is a substantial historical backfill, not merely a transport-format mismatch.
The full-source download/staging reached comparison in about 21 minutes. That
is not a successful full-refresh duration: publication was deliberately held.

Routine updates were validated and restored:
- Daily core job 2 temporarily retains the legacy 30-day API window (`mode=api`).
  Execution `exec_2_7551db3ac85240b1aacd8b0662dbee8a` completed in 45.9 seconds:
  47,688 records checked, zero inserts/updates because the window was current.
- Fatalities full CSV plus SODA catch-up execution
  `exec_7_7ea0871727354446806f9973a395cdcf` completed in 19.5 seconds,
  inserting 1 and updating 1,013 valid records. The checkpoint is established;
  weekly job 5 remains `mode=incremental` and enabled. The 34 identity exclusions
  were recorded. Final database size was 3,805 MiB.

Next recommended operation: prepare a fresh 5 GB database with compact tables,
perform the historical backfill there with measured disk/WAL headroom, verify
counts, source fields and dashboard/export results, then perform a controlled
connection cutover. Retain the old database for rollback. Do not simply raise
the production mutation guard or drop/reload its live people table. Numeric
internal crash join keys are a separate structural space optimization.

Release routing: API/export/frontend were manually deployed from `ff1503e`;
ingestion worker from `c08b80a`. The existing API/frontend GitHub source settings
remain on main, so a later main deployment must include these changes to avoid
reverting the manual release. Workers were deployed from clean CLI packages.

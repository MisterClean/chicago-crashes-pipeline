# Data engineering and dashboard architecture review

Reviewed September 4, 2026. Scope: local backend/frontend source, live production location report in Browser, Railway service state and bounded logs/metrics, live Chicago dataset metadata and CSV headers, and the O’Hare Flyer / Smart Streets website source. No application code, database data, or deployment was changed. Companion `csv-api-column-mapping.json` contains verified source mappings.

## Assessment

The application has a sound foundation for its scale: PostgreSQL/PostGIS, separate crash/person/vehicle records, centralized source configuration, reusable sanitizers, batch transactions, persistent job summaries, shared report/export filters, and transparent cost calculations. Keep these. The highest-value refactor is the execution and persistence path, rather than replacing FastAPI or PostgreSQL.

The reported six-hour full refresh was not reproduced. Current code gives strong reasons to expect avoidable overhead, especially per-record database lookups. Railway’s production backend, frontend, and PostGIS services reported SUCCESS. Hourly samples over 24 hours showed low backend CPU and roughly 0.32 GB memory; these sparse samples do not diagnose a historical full refresh or exclude short spikes. Recent logs showed sequential 30-day core-data fetches, consistent with the source code. Local Python configuration imported successfully; Docker was not running, so no local database benchmark was performed.

## Priority findings

| Priority | Evidence | Consequence | Recommendation |
|---|---|---|---|
| High | `src/services/database_service.py:165` calls `session.get` for every record before ORM updates/inserts | Millions of database round trips during full refresh | COPY into staging, then set-based insert/update; avoid rewriting unchanged records |
| High | `src/etl/soda_client.py:339` estimates 10,000 records or zero after a count failure; `:124` uses count to determine page count | An incomplete extraction can appear successful | Count is progress-only; exhaust deterministic pages and fail explicitly on extraction errors |
| High | `src/services/job_service.py:584` scans recent crash dates; modified-record helper is not used | Corrections to older crashes/persons/vehicles can be missed | Per-source modification watermark, overlap and durable checkpoints, plus periodic reconciliation |
| High | `src/services/job_service.py:315` uses in-process tasks; `src/services/sync_service.py:140` performs synchronous processing in the coroutine | Refreshes compete with web requests and active execution is lost on restart | Separate Railway worker and durable leased jobs |
| High for CSV migration | `src/validators/data_sanitizer.py:403` uses `%H` together with `%p` | PM CSV timestamps silently become morning times | Use `%I`, unify normalization across sources, test midnight/noon/PM |
| Medium | `src/etl/soda_client.py:118` orders by event date alone, using OFFSET | Ties and source changes make pagination unstable | Stable compound ordering and keyset pagination for deltas |
| Medium | Full refresh is an all-history upsert, without removal reconciliation | Source deletions persist locally | Reconcile absence only after a complete, validated full snapshot |
| Medium | Config exposes COPY/concurrency settings that this path does not use | Settings imply optimizations that do not occur | Implement deliberately or remove misleading settings |

The CSV timestamp issue was reproduced using an actual first CSV record: `07/28/2020 09:37:00 PM` parses to `09:37` with the current format and `21:37` with the correct format. Existing JSON ISO timestamps are a different path; this does not establish that production hours are currently corrupted.

## Hybrid full/incremental ingestion

Full refresh: download CSV → retain raw artifact and metadata/checksum → map headers and normalize types → validate/quarantine → COPY staging → validate snapshot → merge/reconcile → publish generation → catch up changes → refresh summaries/exports.

Incremental: SODA modification query → same canonical contract and bulk sink → commit → advance checkpoint.

PostgreSQL specifically recommends COPY for bulk loading: https://www.postgresql.org/docs/17/populate.html. CSV helps extraction, but keeping the existing per-record ORM sink would retain substantial overhead. Benchmark API+current sink, API+bulk sink, and CSV+bulk sink separately on the same data and resources. Measure elapsed time, rows/second, request count, parse/validation/load/merge seconds, peak memory, database work and dashboard latency while ingestion runs. Do not promise a full-refresh duration before measuring.

For each source, store the last successful source watermark and stable tie-breaker. Bound each run, overlap the preceding successful interval, and only advance after committed work. First verify live `:updated_at` behavior for each dataset; a publisher replacing the dataset can mark every row updated. Modifications do not necessarily convey deletions. Socrata reference: https://dev.socrata.com/docs/system-fields.html.

Coordinate full and incremental publishers using a database lock/lease so an older bulk snapshot cannot overwrite newer applied deltas. Four independent CSV downloads are not one atomic source snapshot. Capture extraction start/end per source, use a catch-up overlap, and publish a coherent generation after checks. Keep serving the prior generation during preparation. A generation design must account for foreign keys, indexes, views and rollback; casually renaming tables is insufficient.

Snapshot gates: required headers/types, unique keys, plausible volume relative to prior snapshot, date range, null/rejection rates, parent-child coverage, geometry validity, and complete download/parse success. Quarantine invalid records with reasons. Never interpret a failed or partial extract as evidence to delete production records. Source discrepancies should be visible, not silently forced to agree.

## Verified CSV/API mappings

The companion JSON includes metadata-derived mappings and actual observed CSV headers for all four datasets. All 157 headers matched, with no unmapped or duplicate CSV headers in this check.

| Dataset | Socrata ID | Verified columns | Example |
|---|---|---:|---|
| Crashes | 85ca-t3if | 49 | CRASH_RECORD_ID → crash_record_id |
| People | u6pd-qa9d | 29 | INJURY_CLASSIFICATION → injury_classification |
| Vehicles | 68nd-jvt3 | 71 | CRASH_UNIT_ID → crash_unit_id |
| Fatalities | gzaz-isa6 | 8 | Person_ID → person_id |

CSV endpoint: `https://data.cityofchicago.org/api/views/{id}/rows.csv?accessType=DOWNLOAD`. Metadata: `https://data.cityofchicago.org/api/views/{id}.json`. Metadata provides display `name`, API `fieldName`, and `dataTypeName`.

Version these contracts. Validate actual headers on each run; explicitly handle renamed, missing, duplicate and new fields. Preserve identifier precision, empty-vs-null semantics, quoted multiline CSV, floating local timestamps, booleans and location/geometry representation. Header matching alone does not establish row-value parity or compatibility with the narrower local model. Sample CSV/API records by primary key before rollout. Do not assume every API field belongs in the database or that lowercasing labels remains sufficient forever.

## Worker and database architecture

Use the current repo/image with distinct API and worker entry points. Start with a Postgres-backed job queue, atomic claims, leases/heartbeats, bounded retries and resumable checkpoints. Avoid duplicate scheduling across replicas; scheduled and manual jobs should use the same coordination. Redis or a larger orchestration framework can be evaluated if queue volume or dependency complexity justifies them.

Track inserted, changed, unchanged, rejected and deleted separately; the current updated counter largely means the primary key existed. Expose last successful publication and source freshness independently of the latest event timestamp. Add per-stage progress so a slow download is distinguishable from a slow merge.

Keep API, worker and database on Railway private networking where configured. Limit ingestion/export DB concurrency to preserve interactive latency. Profile representative radius, polygon and named-place queries before adding indexes; inspect whether geography casts match available indexes. Reuse a selected crash-ID relation and preaggregate people/vehicles independently to prevent join fan-out. Add named-place summaries keyed by boundary version and data generation after measuring query demand. Arbitrary polygons still require spatial queries. Partitioning or a second analytical database should follow evidence, not precede these changes.

## Export architecture and Smart Streets comparison

Current strengths: shared location/date filters, related records selected through matching crashes, ZIP written to a temporary file, and export of the displayed report selection. Preserve the existing access policy.

Current weaknesses: `src/api/routers/dashboard.py:1220` builds ZIPs synchronously before the response; `:1211` executes without server-side streaming; `frontend/lib/api.ts:267` buffers the entire response as a Blob. HTTP iteration alone does not make database fetching bounded-memory. Cleanup is registered after generation, so exceptions can leave temporary files. Multiple queries also need a shared snapshot if ETL can update the tables during an export. Public column lists should be explicit and versioned instead of automatically following every ORM column.

Smart Streets already implements the right delivery pattern in `/Users/mmclean/dev/website/mclean-website/services/source-assets-proxy/server.js`: allowlisted stable route → short-lived signed URL → browser downloads directly from Railway Bucket. The source archive architecture is documented in that repo’s `docs/smart-streets-data.md`. The mclean-website Railway project currently includes the source-assets-proxy service.

For filtered crash exports:

1. API accepts canonical report filters and returns an export job ID with HTTP 202.
2. A worker claims the job and pins a consistent read snapshot or published generation.
3. Materialize selected crash IDs once. Export via COPY TO STDOUT, or a true server-side cursor if transformation is necessary. Stream to a temporary ZIP or multipart upload with bounded disk/memory use.
4. Include CSVs and a manifest containing filters/geometry, source versions, timestamps, row counts, schema version and checksums.
5. Upload and verify the completed object, then mark the job ready. Retry interrupted generation/upload safely.
6. Browser polls status and navigates to a signed download URL. Download retries reuse the artifact.
7. Cache by canonical selection + data generation + export schema version; expire ad hoc artifacts using scheduled cleanup.

Prebuild common citywide/year/named-area downloads after refresh. Reuse the Smart Streets stable-route pattern for those; dynamic job downloads belong behind job lookup rather than thousands of static manifest entries. Apply size, time, queue and concurrency limits. Keep a tiny synchronous CSV path only if it is demonstrably bounded.

Railway currently has free bucket egress, but service-to-bucket uploads incur service egress and buckets are on the public network: https://docs.railway.com/storage-buckets/billing. Direct bucket downloads avoid repeatedly routing all bytes through the API. Storage/download guide: https://docs.railway.com/guides/storage-buckets-guide.

## Production dashboard observations and priorities

Browser displayed the Loop report for September 4, 2025–September 4, 2026 with 3,652 crashes. The map and explicit cost methodology are useful; cost presentation and repeated metric blocks occupy considerable space before time patterns.

Existing correctness/presentation improvements:

- The summary displayed 49 incapacitating injuries while the cost table displayed 52. Source code uses crash summary counts for one and person classifications for the other. Reconcile on crash IDs and label source/definition differences; this review did not establish which is authoritative or the cause of the discrepancy.
- Monthly trends intersect selected dates with a hardcoded last-12-month filter (`dashboard.py:1054`). Older selected periods can yield no trend. Generate a complete selected-range calendar, mark partial periods, and distinguish zero from unavailable data.
- `TrendSparklines.tsx:26` parses `YYYY-MM-01` as a UTC date then formats locally, which can label the previous month in Chicago. Format year/month components directly. The live chart showed Sep 25–Aug 26 while the selection extended into September 2026; local code provides a concrete mechanism to verify and fix.
- The map query caps results at 5,000 while summary statistics cover the full selection. Show plotted/total counts or use clustered/vector-tile delivery for large selections. Never calculate new charts from this truncated GeoJSON.
- Display place name, filter range, source coverage and last successful refresh prominently. The live page still says “Select Area” above an already generated Loop report.

Recommended additions in order:

| Chart/table | Question answered | Implementation / cautions |
|---|---|---|
| 7×24 hour/weekday heatmap | When do crashes and severe outcomes occur? | SQL over the complete filtered crash set; Chicago wall time; zero-fill 168 cells; total crashes / injury crashes / fatal-or-incapacitating crashes; label event vs person counts |
| Road-user × injury severity table | Who is harmed, and how seriously? | Aggregate person records separately; pedestrian, cyclist, driver/passenger; counts and within-group shares; explicit unknowns |
| Selected-period monthly trend + prior comparable period | Is the pattern changing? | Complete calendar, consistent exposure periods, visible incomplete recent data; do not label partial-month declines as improvement |
| Street segment/intersection ranking | Where should a reader investigate? | Rank severe outcomes and crash counts; minimum counts and canonical segment/intersection IDs; street text alone is not a reliable intersection identifier |
| Crash type × severity | What kinds of events drive harm? | Distinguish reported crash type from reported contributing cause; show unknowns |
| Data coverage panel | How much confidence should I place in this report? | Source refresh times, geocoded share where measurable, unmatched children, injury discrepancies and available period |

Reuse the O’Hare heatmap design from `/Users/mmclean/dev/website/mclean-website/ohare-flyer-demand-2025.js:493`: semantic table, keyboard navigation, useful cell labels, row/column totals, compact mobile labels and legend. Rebuild it as a reusable React component. Offer counts and within-selection percentages; mean count per occurrence of weekday is useful for unequal date windows. These describe frequency, not risk per trip without traffic exposure denominators. Derive the weekday consistently from local crash timestamps, rather than assuming portal weekday numbering equals PostgreSQL numbering.

Recommended report order: selected place and freshness → concise injury/crash summary → map → timing heatmap → trends → road users and hotspots → causes → expandable cost detail/methodology and exports.

## Delivery sequence

1. Fix extraction completeness, timestamp/date-boundary handling and misleading metric labels; add phase timings and meaningful regression checks.
2. Benchmark and replace the row-by-row sink with staging/COPY and changed-only merges.
3. Introduce CSV full loads and validate CSV/API parity and snapshot publication/rollback.
4. Move execution into a durable worker; implement true deltas, catch-up and reconciliation. Worker separation can be brought forward if web responsiveness is the immediate problem.
5. Move large exports to worker + bucket; prebuild common snapshots.
6. Correct the existing trend/map semantics, then add the heatmap and road-user severity table. Add aggregate caching only against measured needs.

Acceptance checks should cover identical snapshot row/key coverage across CSV and API, noon/midnight/PM, count failure without silent truncation, restart/resume, old-record correction, deleted-source reconciliation, concurrent publication/export consistency, and dashboard responsiveness during bulk work. This is a proposed implementation sequence, not a production benchmark or completed refactor.

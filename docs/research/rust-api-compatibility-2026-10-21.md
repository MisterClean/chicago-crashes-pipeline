# Rust API compatibility inventory — 2026-10-21

This inventory documents the Rust application contracts retained from the previous public API. Retired diagnostics return explicit responses rather than silently implying support.

The embedded admin calls `/admin/api/*`. This alias retains the same authentication and upload handling as the root API, and works directly or through the Next.js `/admin/*` proxy.

| Routes | Rust behavior | Authentication when API_KEY is configured |
| --- | --- | --- |
| `GET /`, `/health`, `/version` | Local runtime identity, engine/source hash and health; health does not make an external portal request on every probe. | Public |
| `GET /runtime/info` | Protected PID, engine/resource/cache settings and source hash for reproducible profiling. | Required |
| `GET /dashboard/stats`, `/dashboard/trends/weekly`, `/dashboard/crashes/geojson`, `/dashboard/crashes/by-hour`, `/dashboard/crashes/by-cause`; `POST /dashboard/location-report` | Existing JSON contracts and date/geometry semantics; all 11 real-data comparison cases passed. Only map results are capped. Optional bounded cache covers public reads only. | Public |
| `POST /dashboard/location-report/export` | Explicitly retired synchronous export; use durable `/exports`. | Required |
| `GET /places/types`, `/places/types/{type}/items`, `/places/types/{type}/items/{id}/geometry` | Native and uploaded place identifiers, including URL-encoded `layer:` IDs; labels and geometry retained. | Public |
| `POST /exports`; `GET /exports/{id}`, `/exports/{id}/download` | Durable bounded queue, frozen selection, schema-v1 columns, expiry and signed downloads; no credential in download URL. | Required; signed artifact URL authorizes only that download |
| `GET /exports`; `POST /exports/{id}/cancel`, `/jobs/{id}/cancel` | Added queue listing/cancellation; active attempt fencing retained. | Required |
| `GET /admin`, `/admin/`, `/admin/app.js`, `/admin/styles.css` | Embedded deployed admin UI with HTML escaping fixes; UI submits header credentials to protected APIs. | Public assets |
| `GET /sync/status` | Existing dashboard counts plus legacy `status`, `current_operation`, `last_sync`, `stats`, `uptime`. Imported execution history and current queue records are reconciled without duplicate counting. Public error summaries omit private details. | Public |
| `GET /sync/counts`, `/sync/endpoints` | Four canonical dataset counts, legacy admin table-name aliases, total counted once, timestamp; four configured source endpoints. | Required |
| `POST /sync/trigger` | Legacy singular endpoint, explicit dates, mode and force retained in durable request and linked legacy execution history. Accepted response includes legacy message/sync_id/status/started_at and queue_id. See guards below. | Required |
| `POST /sync/test` | HTTP 410 with an explicit replacement message. Legacy live-portal test-sync diagnostic is retired; no local result is presented as validation of portal data. | Required |
| `GET /validate`, `/validate/` | Describes retired portal validation and its replacement, rather than inventing a local validation result. | Required |
| `GET /validate/{endpoint}` | HTTP 410, explicitly retired live-portal validation. | Required |
| `GET /jobs`, `/jobs/`; `POST /jobs`, `/jobs/`; `GET`, `PUT`, `DELETE /jobs/{integer_id}` | Legacy scheduled job definitions and identifiers, disabled state/configuration, CRUD and execution history retained in SQLite. | Required |
| `GET /jobs/summary`, `/jobs/types`; `POST /jobs/{integer_id}/execute`; `GET /jobs/{integer_id}/executions`, `/jobs/executions/recent`, `/jobs/executions/{id}` | Legacy admin metadata and execution contracts, linked to fenced queue attempts. | Required |
| `POST /jobs/data/delete`; `GET /jobs/data/deletions` | Confirmed optional date-bounded deletion of the selected facts table; backup by default, atomic DuckDB mutation journal and idempotent SQLite deletion audit. | Required |
| `GET /jobs/schedules`; `POST /jobs/schedules/{id}` | Added explicit fixed-UTC native schedule definitions, bounded queue and claim fencing. | Required |
| `GET /jobs/scheduler/status`; `POST /jobs/scheduler/start`, `/jobs/scheduler/stop` | Added durable scheduler gate; worker rereads it every tick. Stop pauses future schedule dispatch and preserves queued/running work. This is additive: audited Python router revisions do not define these HTTP handlers. | Required |
| `POST /jobs/backup` | Added recovery backup operation. | Required |
| `GET /spatial`, `/spatial/` | Capabilities and upload/table/place usage. | Required |
| `GET /spatial/tables`, `/spatial/tables/{table}?limit=10` | Existing spatial tables only; identifier allowlist, bounded sample (1–100), summarized geometry. Includes facts/uploads and six native boundary names if they exist; no download or recreation of boundaries. | Required |
| `POST /spatial/load` | HTTP 410: server-directory loading retired, use authenticated GeoJSON/shapefile ZIP upload. | Required |
| `GET /spatial/layers`, `/spatial/layers/{id}`; `POST /spatial/layers/preview-fields`, `/spatial/layers`, `/spatial/layers/{id}/replace`; `PATCH`, `DELETE /spatial/layers/{id}` | Legacy multipart metadata/label preview, configured labels, replacement identity, activity/description/sort updates and deletion. Same-transaction mutation receipt invalidates public cache. | Required |
| `GET /spatial/layers/{id}/geojson` | Added geometry collection response. | Required |
| `/docs`, `/openapi.json`, `/documentation` | Python-generated schema/docs bundle is not embedded in the Rust backend. Existing repository documentation and this explicit route inventory describe the replacement. | Not served |

## Manual sync guards and request resolution

An omitted endpoint means exactly the reviewed daily core datasets (`crashes`, `people`, `vehicles`) in API mode over the previous 30 event-date days. It never implicitly adds fatalities or starts a full refresh. A singular `endpoint: fatalities` stays singular. Explicit dates are resolved once when queued and select API event-date mode; the originally requested mode is retained for audit. `force` remains visible and does not override a hold, disabled flag, historical people-date-repair hold, or changed-row publication guard.

Unknown, duplicate or conflicting selectors, malformed/reversed dates and conflicting full/date options return 400 before queue/history insertion. Full refresh needs an explicit reviewed `allow_full_refresh` guard. Core source-modification incremental ingestion remains held (409); fatalities incremental needs a bootstrap checkpoint (409 if absent). Held/disabled/people-date-repair requests return 409. Accepted queue insertion and manual scheduled-job/execution history commit together in one SQLite transaction, respecting the shared queue cap; full queues return 429.

## Local verification

The real DuckDB 2.0 HTTP fixture owns a fresh temporary database and SQLite store. Its 26 tests passed after this compatibility work, including admin counts/aliases, exact singular sync/date/force preservation, default core window, rejection before queueing, explicit 410 diagnostics, allowlisted spatial samples, scheduler authentication and idempotent persisted start/stop without cancelling work. Three pure sync normalization tests cover resolved date/default/hold cases. Existing fixtures cover native SQL errors, sanitized responses, cancellation, memory limits, rollback/panic guards, cache invalidation and durable exports. No production PostgreSQL mutation tests were run.

Rust alone does not remove native SQL scan costs. The real-data parity and separate uncached/cached workload measurements, rather than route inventory or language choice, determine performance and memory conclusions. Billing savings remain an estimate until actual infrastructure usage is observed.

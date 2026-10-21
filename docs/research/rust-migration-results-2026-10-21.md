# Rust and DuckDB measurements — October 21, 2026

These measurements describe a local migration candidate using DuckDB **2.0.0**. The backend API, ingestion, spatial uploads, schedules, durable exports, migration reader and recovery run in Rust; Next.js remains the frontend. They do not establish production deployment, a latency SLO or a billing reduction.

The design targets modest traffic and daily updates. One backend owner replaces an independently running database/backend/worker arrangement. The cost target is at least 50% project savings, to be verified through actual hosting measurements after an authoritative migration.

## Full CSV bootstrap

The same 2,073,941,118 bytes of retained public portal CSVs were imported on macOS ARM64 with a 256 MB DuckDB buffer and two SQL threads. Download time is excluded; OS caches were not evicted. Each column is an individual observation.

| Measurement | Earlier prototype | Rust seed |
| --- | ---: | ---: |
| Wall time | 49.245 s | 34.005 s |
| Process CPU | 70.948 s | 55.828 s |
| Lifetime peak RSS | 561.2 MiB | 461.7 MiB |
| Sampled peak spill | 961.3 MiB | 304.5 MiB |

The fixture contained 1,105,499 crashes, 2,426,951 people, 2,254,477 vehicles and 1,014 accepted fatalities. Eight boundary layers with 941 features retained their original IDs, labels, properties, timestamps and WKB. The resulting fact file was 579,874,816 bytes.

This was a **profiling-only population**: its crash CSV lagged the audited portal count by 329 rows. It was never declared an authoritative replacement. Existing installations can contain historical values absent from independent portal exports; migrate those through the consistent snapshot reader.

## Native HTTP comparison

On the same macOS host, 100 mixed requests from five clients overlapped a verified Loop export. The buffer was 256 MB with two SQL threads. The earlier prototype and Rust held the same logical population but used their own physical table layouts. Warm-up preceded measurement; filesystem caches and allocator state were not controlled.

| Measurement | Earlier prototype | Rust, cache off | Rust, 16 MiB cache |
| --- | ---: | ---: | ---: |
| Total wall time including verified export | 95.451 s | 57.872 s | 3.646 s |
| API process CPU in measured window | 162.206 s | 99.200 s | 5.040 s |
| Sampled API peak RSS | 595.4 MiB | 615.4 MiB | 605.0 MiB |
| Mixed HTTP p95 | 6.251 s | 7.128 s | 0.606 s |
| HTTP success | 100/100 | 100/100 | 100/100 |

Uncached Rust reduced elapsed time by 39.4% and process CPU by 38.8%, while sampled peak RSS increased 3.4% and p95 increased 14.0%. The language change alone does not demonstrate lower analytics memory. Warm repeated-response caching changes the workload substantially; oversized map responses bypass it.

## Linux memory trials

ARM64 Linux containers used two CPUs, no swap and independent copies of the Rust-seeded facts. Each case made 24 mixed HTTP requests from one client with a simultaneous queued export and one warm-up per route.

| RAM cap | DuckDB buffer | Cache | Outcome | Native peak RSS | HTTP p95 |
| --- | --- | --- | --- | ---: | ---: |
| 512 MiB | 128 MB | off | HTTP passes; export allocation fails | 356.2 MiB | 10.195 s |
| 512 MiB | 192 MB | off | All pass | 428.4 MiB | 9.638 s |
| 512 MiB | 256 MB | off | All pass | 496.5 MiB | 9.917 s |
| 768 MiB | 128 MB | off | HTTP passes; export allocation fails | 374.6 MiB | 11.129 s |
| 768 MiB | 192 MB | off | All pass | 433.4 MiB | 11.307 s |
| 768 MiB | 256 MB | off | All pass | 495.3 MiB | 10.639 s |
| 512 MiB | 192 MB | 16 MiB | All pass | 417.5 MiB | 0.297 s |
| 768 MiB | 192 MB | 16 MiB | All pass | 424.6 MiB | 2.195 s |

The 128 MB buffer is only 122 MiB, smaller than an observed 128 MiB native export allocation. Raising the outer container cap did not fix that buffer allocation failure. None of the cases suffered a kernel OOM/kill.

The cached 768 MiB control crossed a Chicago hour boundary during warm-up, invalidating report cache keys. Its first measured reports missed, so the slower result is not evidence that more RAM reduces performance. First-visitor and time-invalidated misses remain part of the resource budget.

A final-build repeat at 512 MiB/192 MB with a 16 MiB cache passed 24/24 requests and verified export in 5.051 seconds, with 405.8 MiB native peak RSS, 289.4 MiB idle RSS and 0.170-second mixed HTTP p95. Facts remained byte-identical, and shutdown was clean without OOM. An early five-second readiness probe timed out during warm-up; subsequent probes passed. Readiness shares the SQL lane.

Cgroup peaks reached configured caps with substantial reclaim pressure. Cgroup accounting included measurement helpers, the HTTP client and page cache; native RSS excluded them. These short trials establish successful execution, not spare headroom, indefinite stability or a hosting bill.

## Correctness and operations checks

- All 33 full-data API comparisons passed against the earlier oracle, including lists and exact first/last feature geometries for all eight layers.
- Browser checks loaded Loop and Ward 47 reports, boundaries and map points without console errors.
- A real 30-day daily core API window accepted 48,639 rows in 65.798 seconds, using 351.2 MiB native peak RSS inside a 512 MiB Linux container. It inserted 332 crashes and updated 8,855. The initial LOCATION updates were equivalent WKT/GeoJSON points; stored geometry did not change. A separate-copy repeat of the same source content inserted and changed zero facts. This proves the requested window rather than global completeness.
- A verified full-size paired backup/restore retained the byte-identical 579,874,816-byte fact file and all counts. An occupied restore destination was refused.
- A disposable PostgreSQL integration checked trusted TLS/hostname verification, read-only repeatable-read capture, typed historical values, null person dates, exact WKB, operational IDs and private file permissions under a permissive caller umask.
- Disposable MinIO checked authenticated PUT/HEAD/GET/LIST/DELETE, private access, invalid signature rejection and byte/hash verification. `bash scripts/test-s3.sh` reproduces that native signing check.
- Real GDAL converted foreign-CRS GeoJSON and a complete shapefile ZIP in an isolated 512 MiB Linux container. All small-fixture vertices and labels matched expectations; this does not establish large-upload capacity.
- The Node 22 standalone frontend passed six HTTP/SSR/proxy checks in a separate 256 MiB container without swap or OOM; server peak RSS was 98.6 MiB.

The measurement source fingerprints were `d43356b54a966229349c0d951e4e25e6871b2a44618ae2c36f03bb3abdf74b68` and `1184d7efcc9521a18091901c89a3f16147d142d11e31a5e2bb3fadc36d74092f`. The latter added only an administrative execution-counter fix. Subsequent repository cleanup moves the unchanged mapping into the Rust crate, makes native test setup portable, initializes new bootstrap catalogs, and removes the retired implementation. These measurements should not be represented as a fresh benchmark of every later commit. Use `build-info` and `/runtime/info` to identify a new run.

## Reproduction and release boundary

The repository-cleanup candidate has source fingerprint
`d068b98ddc25ba9d4fd3748c4a5e2ae40f1d924a6fb68a4c131ee405d266555b`.
An exact staged-source export passed a fresh native installation, strict Clippy,
121 Rust tests and a release build with library override variables unset. Four
Node tests, the disposable S3 signing test, a frontend build without local
environment files, and both production image builds passed. The Rust advisory
and frontend runtime audits were clean; the documented build-only findings
remain in the full frontend dependency audit.

A new full profiling seed started with an empty boundary catalog. The Node 22
container reached that backend through its proxy: dashboard SSR, runtime identity,
admin assets and place types passed; the protected admin summary rejected a
missing key and accepted the disposable test key. The candidate's staged tree
contained no Python files, machine paths or broken local Markdown links, and an
offline Gitleaks scan found no secrets. This records portability/packaging checks,
not a new performance comparison.

Follow the [README](../../README.md) for native setup and validation, and the [operations guide](../rust-migration.md) for migration and recovery. For resource measurements, build with `--release`, identify the source/engine/buffer/thread/cache settings, use immutable input copies, record failures and measure query misses as well as warm repeats. Record server RSS separately from container accounting, frontend usage and measurement-client usage.

Large input downloads, databases, raw local profiles, deployment identifiers, credentials and workstation paths are intentionally absent from the public repository. The earlier production application remains in Git history; raw prototype harnesses and local reports are not shipped.

Before cutover, validate the authoritative facts, boundaries and operational population on a replacement volume, rehearse private-bucket recovery and observe actual freshness/resource metering. Keep a rollback deployment until that review is complete. Consolidation, bounded work, daily scheduling and response caching remain the cost-optimization pathway.

# Contributing

Use the [README](README.md) to install Rust, the pinned native DuckDB library, Node and frontend dependencies. All commands run from the repository root. The backend is Rust and the frontend is TypeScript; no Python environment or PostgreSQL service is needed for ordinary development.

Create a topic branch, make the smallest coherent change, and run:

```sh
cargo fmt --all -- --check
cargo clippy --all-targets --all-features --locked -- -D warnings
cargo test --all-targets --locked
node --test rust/crashes-server/tests/admin-ui.test.cjs frontend/tests/export-api.test.cjs
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Native tests create temporary databases and require the real DuckDB 2.0.0 library and signed spatial extension. Missing setup must fail instead of silently skipping the assertions. `bash scripts/test-s3.sh` additionally runs a disposable localhost MinIO integration test when Docker is available.

Preserve the single-owner database model, bounded memory/disk/queue behavior, immutable operation IDs, transactional publication and attempt fencing. Do not introduce independent DuckDB writers or bypass authentication, source validation, historical completeness or ingestion holds to make tests pass.

Use `Result` for fallible application work, keep unsafe native bindings isolated in `db.rs`, and explain non-obvious safety invariants. Add meaningful regression tests for behavior changes. Frontend changes should preserve request cancellation, safe rendering of uploaded text and authenticated export polling.

Update documentation when commands, environment variables, API behavior or operating limits change. Use relative paths and generic configuration examples. Do not commit datasets, credentials, local measurements containing connection details, generated build output, editor settings or workstation-specific agent configuration. The CSV/API mapping is embedded from `rust/crashes-server/resources/`; schema changes require deliberate review.

A pull request should explain the concrete behavior change, validation and remaining operational risks. Use [SECURITY.md](SECURITY.md) to report vulnerabilities privately.

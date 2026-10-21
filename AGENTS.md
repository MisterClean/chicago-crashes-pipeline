# Repository guide

This is the Rust/DuckDB Chicago crashes application. Follow README.md for setup and docs/rust-migration.md for operational invariants. Ordinary development requires no Python environment or PostgreSQL service.

- Run commands from the repository root. Use `rg` for source searches.
- Rust source, SQL, embedded admin UI and CSV mapping live in `rust/crashes-server/`; the Next.js application lives in `frontend/`.
- Install native dependencies with `bash scripts/setup-rust-duckdb.sh`. Use the pinned Rust toolchain and Node 22. Never silently skip native tests when setup is missing.
- Validate Rust changes with formatting, strict Clippy and the relevant real-engine tests. Run the Node tests and frontend type check/build for affected UI work.
- Preserve one DuckDB owner/replica, transaction receipts, attempt fencing, source publication guards and historical value preservation. Keep native unsafe bindings in `db.rs`.
- Keep environment configuration generic and paths relative. Actual data, secrets, local reports and workstation-only agent files do not belong in commits.
- Infrastructure changes, production data migration and traffic cutover are separate from preparing or pushing source changes. Follow the user's authorization and verify actual results before claiming a deployment or savings.

# Dependencies

The backend uses Rust 1.99.1, Axum/Tokio for HTTP and background work, DuckDB 2.0.0 through its stable C API, and bundled SQLite through rusqlite for operational state. Reqwest and rusty-s3 implement bounded private object delivery. Native PostgreSQL/TLS dependencies serve only the explicit read-only migration command.

`Cargo.lock` pins the Rust dependency graph. `scripts/setup-rust-duckdb.sh` selects an official Linux/macOS x86-64/ARM64 shared library, verifies its checksum and installs the matching signed spatial extension. Set `DUCKDB_LIBRARY_PATH` and `DUCKDB_SPATIAL_PATH` to use another installation location. The runtime rejects other DuckDB versions.

GDAL's `ogr2ogr` handles shapefile and foreign-CRS conversion; the application bounds its lifetime and output. The container includes GDAL and system certificate roots. The Rust application does not require Python; a distribution's GDAL package may include its own language bindings.

The frontend uses Next.js 15, React 19, MapLibre 6, react-map-gl 8, Recharts and Tailwind. MapLibre 6 requires WebGL 2. `frontend/package-lock.json` pins the installed dependency graph. Node 22 is used in CI and the image; `frontend/.nvmrc` selects that development version.

Run the dependency audits described in [SECURITY.md](SECURITY.md). Review version changes with a clean install, native tests, frontend type checking/build and a real map/browser check. Do not replace pinned native binaries or disable signature/ABI validation to work around an extension mismatch.

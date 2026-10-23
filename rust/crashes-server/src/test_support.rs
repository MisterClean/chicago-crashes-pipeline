//! Shared native fixtures resolve the same installation on Linux and macOS.

use crate::db::{Database, sql_literal};
use std::path::{Path, PathBuf};

fn installation() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.local/rust-duckdb")
}

pub fn library() -> PathBuf {
    let filename = if cfg!(target_os = "macos") {
        "libduckdb.dylib"
    } else {
        "libduckdb.so"
    };
    let path = std::env::var_os("DUCKDB_LIBRARY_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| installation().join(filename));
    assert!(
        path.is_file(),
        "DuckDB 2.0.0 library missing at {}. Run bash scripts/setup-rust-duckdb.sh or set DUCKDB_LIBRARY_PATH",
        path.display()
    );
    path
}

pub fn load_spatial(database: &Database) {
    let path = std::env::var_os("DUCKDB_SPATIAL_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| installation().join("spatial.duckdb_extension"));
    let path = path
        .canonicalize()
        .expect("Install the signed spatial extension with bash scripts/setup-rust-duckdb.sh");
    database
        .execute(
            &format!(
                "LOAD {}",
                sql_literal(path.to_str().expect("UTF-8 extension path"))
            ),
            &[],
        )
        .expect("Load the signed DuckDB 2.0.0 spatial extension");
}

use sha2::{Digest, Sha256};
use std::{fs, path::Path};

fn hash_directory(path: &Path, digest: &mut Sha256) -> std::io::Result<()> {
    let mut entries = fs::read_dir(path)?.collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            hash_directory(&path, digest)?;
        } else {
            println!("cargo:rerun-if-changed={}", path.display());
            digest.update(entry.file_name().as_encoded_bytes());
            digest.update(fs::read(path)?);
        }
    }
    Ok(())
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut digest = Sha256::new();
    for path in ["src", "sql", "static"] {
        hash_directory(Path::new(path), &mut digest)?;
    }
    for path in [
        "Cargo.toml",
        "build.rs",
        "../../Cargo.lock",
        "resources/csv_column_mapping.json",
    ] {
        println!("cargo:rerun-if-changed={path}");
        digest.update(fs::read(path)?);
    }
    println!(
        "cargo:rustc-env=CRASHES_SOURCE_SHA256={:x}",
        digest.finalize()
    );
    Ok(())
}

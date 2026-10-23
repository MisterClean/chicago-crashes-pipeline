use anyhow::{Context, Result};
use serde_json::Value;
use std::{
    path::Path,
    process::{Command, Output},
};

fn probe(data: &Path, scratch: &Path, limit: &str, argument: bool) -> Result<Output> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .context("Rust workspace parent")?
        .parent()
        .context("repository root")?;
    let mut command = Command::new(env!("CARGO_BIN_EXE_crashes-server"));
    command
        .current_dir(root)
        .arg("--data-dir")
        .arg(data)
        .env("DUCKDB_MAX_TEMP_DIRECTORY_SIZE", limit)
        .env_remove("DUCKDB_TEMP_DIRECTORY");
    if argument {
        command.arg("--temp-directory").arg(scratch);
    } else {
        command.env("DUCKDB_TEMP_DIRECTORY", scratch);
    }
    Ok(command.arg("probe").output()?)
}

#[test]
fn native_cli_uses_configured_private_scratch_and_finite_cap_without_default_spill() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let data = directory.path().join("data");
    let scratch = directory.path().join("ephemeral-scratch");
    std::fs::create_dir(&data)?;
    // A file blocks the legacy default; reaching the real engine requires the override.
    std::fs::write(data.join("spill"), "must remain untouched")?;
    for argument in [false, true] {
        let output = probe(&data, &scratch, "8GB", argument)?;
        assert!(output.status.success(), "{output:?}");
        let report: Value = serde_json::from_slice(&output.stdout)?;
        assert_eq!(report[0]["max_temp_directory_size"], "7.4 GiB");
        assert_eq!(
            std::fs::read_to_string(data.join("spill"))?,
            "must remain untouched"
        );
        assert!(scratch.join(".crashes-scratch.owner.lock").is_file());
    }
    // Startup reclamation follows the configured directory rather than DATA_DIR/spill.
    let abandoned = scratch.join("point-preservation-ABC123");
    std::fs::create_dir(&abandoned)?;
    std::fs::write(abandoned.join("location.differences.csv"), "interrupted")?;
    let output = probe(&data, &scratch, "4GB", false)?;
    assert!(output.status.success(), "{output:?}");
    assert!(!abandoned.exists());
    Ok(())
}

#[test]
fn native_cli_rejects_unbounded_or_overflowing_scratch_limits() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for limit in [
        "-1",
        "unlimited",
        "0GB",
        "18446744073709551615GB",
        "18446744073709551615B",
    ] {
        let output = probe(
            &directory.path().join("data"),
            &directory.path().join("scratch"),
            limit,
            false,
        )?;
        assert!(!output.status.success());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("DUCKDB_MAX_TEMP_DIRECTORY_SIZE"),
            "{output:?}"
        );
    }
    Ok(())
}

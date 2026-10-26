//! Consistent single-owner snapshots and fail-closed offline restore.
use crate::{control::ControlStore, db::Database, exports::file_sha256, storage::ObjectStorage};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::Write,
    path::Path,
};

/// Verify publication receipts rather than trusting the existence of fact tables.
pub fn assert_complete(db: &Database) -> Result<()> {
    let tables = db.query(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'",
        &[],
    )?;
    let has = |name: &str| tables.iter().any(|r| r["table_name"] == name);
    let mut complete = std::collections::HashMap::new();
    let mut events = Vec::new();
    if has("ingestion_publications") {
        events.push("SELECT committed_at AS event_at,operation_id AS id,'publication' AS kind,receipt FROM ingestion_publications");
    }
    if has("fact_snapshot_imports") {
        events.push("SELECT imported_at AS event_at,import_id AS id,'snapshot' AS kind,receipt FROM fact_snapshot_imports");
    }
    let rows = if events.is_empty() {
        Vec::new()
    } else {
        db.query(
            &format!(
                "SELECT kind,receipt FROM ({}) events ORDER BY event_at,id",
                events.join(" UNION ALL ")
            ),
            &[],
        )?
    };
    for row in rows {
        let receipt: Value = match &row["receipt"] {
            Value::String(s) => serde_json::from_str(s)?,
            v => v.clone(),
        };
        if row["kind"] == "snapshot" {
            let valid = receipt["production_snapshot"] == true
                && receipt["source_kind"] == "postgresql_repeatable_read";
            for dataset in crate::sources::DATASETS {
                complete.insert(dataset.to_owned(), valid);
            }
        } else if let Some(sources) = receipt.get("datasets").and_then(Value::as_object) {
            for (dataset, result) in sources {
                let valid = receipt["production_complete"] == true
                    && receipt["profiling_only"] == false
                    && result["source_manifest"]["profiling_only"] != true;
                // A daily filtered acquisition updates an established history; it
                // cannot prove that a newly created table contains full history.
                if matches!(
                    result["source_manifest"]["source_scope"].as_str(),
                    Some("event_date_window" | "event_date_window_with_history")
                ) {
                    if !valid {
                        complete.insert(dataset.to_owned(), false);
                    }
                } else {
                    complete.insert(dataset.to_owned(), valid);
                }
            }
        }
    }
    ensure!(
        crate::sources::DATASETS
            .iter()
            .all(|d| complete.get(*d) == Some(&true)),
        "latest complete production publication receipts required for all four sources; seed strictly reconciled inputs or import a verified production snapshot"
    );
    Ok(())
}

/// Hold DuckDB admission across checkpoint+copy and SQLite's online backup.
/// The publication ledger makes unfinished operations replayable after restore.
pub fn backup(
    db: &Database,
    control: &ControlStore,
    root: &Path,
    storage: Option<&ObjectStorage>,
) -> Result<Value> {
    static BACKUP_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
    let _backup_guard = BACKUP_LOCK
        .lock()
        .map_err(|_| anyhow::anyhow!("backup lock poisoned"))?;
    fs::create_dir_all(root)?;
    ensure!(
        fs2::available_space(root)? > db.path.metadata()?.len() + 268_435_456,
        "insufficient free space for a consistent recovery snapshot"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    }
    let id = uuid::Uuid::new_v4().to_string();
    let pending = root.join(format!(".{id}.partial"));
    fs::create_dir(&pending)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&pending, fs::Permissions::from_mode(0o700))?;
    }
    let result = (|| {
        db.with_session(|session| {
            session.execute("CHECKPOINT", &[])?;
            fs::copy(&db.path, pending.join("current.duckdb"))?;
            File::open(pending.join("current.duckdb"))?.sync_all()?;
            control.backup(&pending.join("control.sqlite"))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(
                    pending.join("current.duckdb"),
                    fs::Permissions::from_mode(0o600),
                )?;
            }
            Ok(())
        })?;
        let mut files = Vec::new();
        for name in ["current.duckdb", "control.sqlite"] {
            let path = pending.join(name);
            files.push(
                json!({"name":name,"bytes":path.metadata()?.len(),"sha256":file_sha256(&path)?}),
            );
        }
        let manifest = json!({"schema_version":1,"id":id,"engine":"2.0.0","created_at":chrono::Utc::now(),"files":files,"restore_tested":false});
        let mut file = File::create(pending.join("manifest.json"))?;
        file.write_all(&serde_json::to_vec_pretty(&manifest)?)?;
        file.sync_all()?;
        let destination = root.join(&id);
        fs::rename(&pending, &destination)?;
        File::open(root)?.sync_all()?;
        if let Some(storage) = storage {
            for entry in manifest["files"].as_array().context("snapshot files")? {
                let name = entry["name"].as_str().context("snapshot filename")?;
                storage.upload(
                    &destination.join(name),
                    &format!("backups/{id}/{name}"),
                    entry["sha256"].as_str().context("snapshot hash")?,
                )?;
            }
            let path = destination.join("manifest.json");
            storage.upload(
                &path,
                &format!("backups/{id}/manifest.json"),
                &file_sha256(&path)?,
            )?;
        }
        retain_full_backups(control, root, &manifest, storage)?;
        Ok(manifest)
    })();
    if result.is_err() {
        if pending.exists() {
            let _ = fs::remove_dir_all(&pending);
        }
        let destination = root.join(&id);
        let retained = control
            .configuration("full_backup_history")?
            .and_then(|v| v.as_array().cloned())
            .is_some_and(|history| history.iter().any(|m| m["id"] == id));
        if destination.exists() && !retained {
            let _ = fs::remove_dir_all(destination);
        }
    }
    result
}

fn retain_full_backups(
    control: &ControlStore,
    root: &Path,
    manifest: &Value,
    storage: Option<&ObjectStorage>,
) -> Result<()> {
    let mut history = control
        .configuration("full_backup_history")?
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default();
    history.push(manifest.clone());
    while history.len() > 7 {
        let oldest = history.remove(0);
        let id = oldest["id"].as_str().context("backup history ID")?;
        uuid::Uuid::parse_str(id)?;
        if let Some(storage) = storage {
            for name in ["manifest.json", "control.sqlite", "current.duckdb"] {
                storage.delete(&format!("backups/{id}/{name}"))?;
            }
        }
        let path = root.join(id);
        if path.is_dir() {
            fs::remove_dir_all(path)?;
        }
    }
    // Remote history provides retention; one full local snapshot leaves room for
    // native spill, ingestion staging and a pending backup on a small volume.
    if storage.is_some() {
        for old in history.iter().take(history.len().saturating_sub(1)) {
            if let Some(id) = old["id"].as_str() {
                uuid::Uuid::parse_str(id)?;
                let path = root.join(id);
                if path.is_dir() {
                    fs::remove_dir_all(path)?;
                }
            }
        }
    }
    control.set_configuration("full_backup_history", &json!(history))?;
    control.set_configuration(
        "last_full_backup_at",
        &json!(chrono::Utc::now().timestamp()),
    )?;
    Ok(())
}

/// Small hourly control snapshots avoid retaining full fact copies every hour.
pub fn backup_control(
    control: &ControlStore,
    root: &Path,
    storage: Option<&ObjectStorage>,
) -> Result<Value> {
    fs::create_dir_all(root)?;
    let id = uuid::Uuid::new_v4().to_string();
    let path = root.join(format!("{id}.sqlite"));
    control.backup(&path)?;
    let key = format!("backups/control/{id}.sqlite");
    let sha = file_sha256(&path)?;
    if let Some(storage) = storage {
        storage.upload(&path, &key, &sha)?;
    }
    let receipt = json!({"id":id,"key":key,"bytes":path.metadata()?.len(),"sha256":sha,"created_at":chrono::Utc::now()});
    let mut history = control
        .configuration("control_backup_history")?
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default();
    history.push(receipt.clone());
    while history.len() > 48 {
        let old = history.remove(0);
        let id = old["id"].as_str().context("control backup ID")?;
        uuid::Uuid::parse_str(id)?;
        if let Some(storage) = storage {
            storage.delete(old["key"].as_str().context("control backup key")?)?;
        }
        let old = root.join(format!("{id}.sqlite"));
        if old.exists() {
            fs::remove_file(old)?;
        }
    }
    if storage.is_some() {
        fs::remove_file(path)?;
    }
    control.set_configuration("control_backup_history", &json!(history))?;
    Ok(receipt)
}

/// Remove only unpublished backups in this service's UUID namespace.
pub fn cleanup_orphan_backups(control: &ControlStore, storage: &ObjectStorage) -> Result<usize> {
    let mut retained = std::collections::HashSet::new();
    for item in control
        .configuration("full_backup_history")?
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
    {
        if let Some(id) = item["id"].as_str() {
            for name in ["manifest.json", "current.duckdb", "control.sqlite"] {
                retained.insert(format!("backups/{id}/{name}"));
            }
        }
    }
    for item in control
        .configuration("control_backup_history")?
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
    {
        if let Some(key) = item["key"].as_str() {
            retained.insert(key.to_owned());
        }
    }
    let before = chrono::Utc::now() - chrono::Duration::hours(25);
    let mut cursor = None;
    let mut removed = 0;
    for _ in 0..10 {
        let page = storage.list_page("backups/", cursor.as_deref(), 1000)?;
        for object in page.objects {
            let parts: Vec<_> = object.key.split('/').collect();
            let owned = match parts.as_slice() {
                ["backups", "control", name] => name
                    .strip_suffix(".sqlite")
                    .is_some_and(|id| uuid::Uuid::parse_str(id).is_ok()),
                ["backups", id, name] => {
                    uuid::Uuid::parse_str(id).is_ok()
                        && ["manifest.json", "current.duckdb", "control.sqlite"].contains(name)
                }
                _ => false,
            };
            if owned && object.last_modified < before && !retained.contains(&object.key) {
                storage.delete(&object.key)?;
                removed += 1;
            }
        }
        cursor = page.next_continuation_token;
        if cursor.is_none() {
            break;
        }
    }
    Ok(removed)
}

/// Restore only into an empty destination after verifying every file and SQLite.
pub fn restore(snapshot: &Path, destination: &Path) -> Result<()> {
    let manifest: Value = serde_json::from_reader(File::open(snapshot.join("manifest.json"))?)?;
    ensure!(
        manifest["schema_version"] == 1 && manifest["engine"] == "2.0.0",
        "unsupported backup format or engine"
    );
    let entries = manifest["files"]
        .as_array()
        .context("snapshot files missing")?;
    ensure!(
        entries.len() == 2,
        "snapshot needs exactly fact and control files"
    );
    let mut names = std::collections::HashSet::new();
    for entry in entries {
        let name = entry["name"]
            .as_str()
            .context("snapshot filename missing")?;
        ensure!(
            matches!(name, "current.duckdb" | "control.sqlite") && names.insert(name),
            "invalid or duplicate snapshot path"
        );
        let path = snapshot.join(name);
        ensure!(
            path.is_file() && !path.is_symlink(),
            "snapshot must contain regular files"
        );
        ensure!(
            entry["bytes"].as_u64() == Some(path.metadata()?.len())
                && entry["sha256"] == file_sha256(&path)?,
            "snapshot checksum mismatch"
        );
    }
    fs::create_dir_all(destination)?;
    let lock = File::options()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(destination.join("current.owner.lock"))?;
    fs2::FileExt::try_lock_exclusive(&lock).context("cannot restore over an active owner")?;
    let marker = destination.join(".restore-in-progress");
    if marker.exists() {
        let pending: Value = serde_json::from_reader(File::open(&marker)?)?;
        ensure!(
            pending == manifest,
            "an interrupted restore must resume from the same verified snapshot"
        );
    } else {
        ensure!(
            !destination.join("current.duckdb").exists()
                && !destination.join("control.sqlite").exists(),
            "restore requires an empty data directory"
        );
        let mut options = File::options();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&marker)?;
        file.write_all(&serde_json::to_vec_pretty(&manifest)?)?;
        file.sync_all()?;
        File::open(destination)?.sync_all()?;
    }
    let stage = tempfile::TempDir::new_in(destination)?;
    fs::copy(
        snapshot.join("current.duckdb"),
        stage.path().join("current.duckdb"),
    )?;
    ControlStore::restore(
        &snapshot.join("control.sqlite"),
        &stage.path().join("control.sqlite"),
    )?;
    for name in ["current.duckdb", "control.sqlite"] {
        File::open(stage.path().join(name))?.sync_all()?;
        fs::rename(stage.path().join(name), destination.join(name))?;
    }
    fs::write(
        destination.join("restored-from.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    File::open(destination.join("restored-from.json"))?.sync_all()?;
    fs::remove_file(marker)?;
    File::open(destination)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn restore_rejects_path_traversal() {
        let root = tempfile::tempdir().unwrap();
        fs::write(root.path().join("manifest.json"),r#"{"schema_version":1,"engine":"2.0.0","files":[{"name":"../escape"},{"name":"control.sqlite"}]}"#).unwrap();
        assert!(restore(root.path(), &root.path().join("out")).is_err());
    }
}

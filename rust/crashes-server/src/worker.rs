//! One durable background lane shares the database owner's bounded SQL memory.
use crate::{
    api::AppState,
    exports::{ExportLimits, generate_export},
    queries::LocationRequest,
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    path::Path,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

pub fn start(state: AppState, stop: Arc<AtomicBool>) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut last_control_backup = Instant::now();
        let mut last_maintenance = Instant::now() - Duration::from_secs(60);
        let mut prefer_ingestion = false;
        let mut last_orphan_cleanup = Instant::now() - Duration::from_secs(3600);
        while !stop.load(Ordering::Acquire) {
            if state.production && last_maintenance.elapsed() >= Duration::from_secs(60) {
                let maintenance = (|| -> Result<()> {
                    let revision = crate::mutations::revision(&state.db)?;
                    let backed = state
                        .control
                        .configuration("backed_up_revision")?
                        .and_then(|v| v.as_str().map(str::to_owned));
                    let last = state
                        .control
                        .configuration("last_full_backup_at")?
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0);
                    if revision != backed || chrono::Utc::now().timestamp() - last >= 86400 {
                        crate::recovery::backup(
                            &state.db,
                            &state.control,
                            &state.directory.join("backups"),
                            state.storage.as_deref(),
                        )?;
                        state
                            .control
                            .set_configuration("backed_up_revision", &json!(revision))?;
                    }
                    if last_control_backup.elapsed() >= Duration::from_secs(3600) {
                        crate::recovery::backup_control(
                            &state.control,
                            &state.directory.join("control-backups"),
                            state.storage.as_deref(),
                        )?;
                        last_control_backup = Instant::now();
                    }
                    if let Some(storage) = &state.storage {
                        storage.cleanup_orphans(
                            chrono::Utc::now() - chrono::Duration::hours(25),
                            |key| state.control.retains_artifact(key),
                            10,
                        )?;
                        crate::recovery::cleanup_orphan_backups(&state.control, storage)?;
                    }
                    Ok(())
                })();
                if let Err(error) = maintenance {
                    tracing::error!(error=%error,"recovery maintenance failed");
                }
                last_maintenance = Instant::now();
            }
            let result = (|| -> Result<bool> {
                if state.control.configuration("scheduler_enabled")? == Some(json!(true)) {
                    state.control.enqueue_due()?;
                    crate::admin::enqueue_due(&state.control)?;
                }
                cleanup(&state)?;
                if last_orphan_cleanup.elapsed() >= Duration::from_secs(3600) {
                    cleanup_local_attempts(&state.directory.join("exports"), &state.control)?;
                    last_orphan_cleanup = Instant::now();
                }
                prefer_ingestion = !prefer_ingestion;
                let (first, second) = if prefer_ingestion {
                    ("ingestion", "export")
                } else {
                    ("export", "ingestion")
                };
                let job = if let Some(job) = state.control.claim(first)? {
                    Some(job)
                } else {
                    state.control.claim(second)?
                };
                let Some(job) = job else { return Ok(false) };
                let token = job
                    .attempt_token
                    .as_deref()
                    .context("claimed attempt token missing")?;
                ensure!(
                    job.lease_until.is_some(),
                    "claimed job has no lease deadline"
                );
                let heartbeat = Mutex::new(Instant::now() - Duration::from_secs(60));
                let check = || -> Result<()> {
                    ensure!(!stop.load(Ordering::Acquire), "owner is stopping");
                    let mut last = heartbeat
                        .lock()
                        .map_err(|_| anyhow::anyhow!("heartbeat lock"))?;
                    if last.elapsed() >= Duration::from_millis(250) {
                        state.control.check_attempt(&job.id, token)?;
                        state.control.heartbeat(&job.id, token)?;
                        *last = Instant::now();
                    }
                    Ok(())
                };
                let outcome = if job.kind == "export" {
                    (|| -> Result<(Option<String>, Value)> {
                        let request: LocationRequest =
                            serde_json::from_value(job.request["location"].clone())?;
                        let datasets: Vec<String> =
                            serde_json::from_value(job.request["datasets"].clone())?;
                        let directory = state.directory.join("exports").join(&job.id).join(token);
                        let artifact = generate_export(
                            &state.db,
                            &request,
                            &datasets,
                            &directory,
                            &ExportLimits::default(),
                            &check,
                            None,
                        )?;
                        crate::exports::verify_artifact(
                            &artifact.path,
                            artifact.bytes,
                            &artifact.sha256,
                        )?;
                        check()?;
                        let pointer = if let Some(storage) = &state.storage {
                            let name = artifact
                                .path
                                .file_name()
                                .context("artifact filename")?
                                .to_string_lossy();
                            let key = format!("exports/{}/{token}/{name}", job.id);
                            storage.upload_guarded(
                                &artifact.path,
                                &key,
                                &artifact.sha256,
                                &check,
                            )?;
                            check()?;
                            key
                        } else {
                            artifact
                                .path
                                .canonicalize()?
                                .to_str()
                                .context("artifact UTF-8")?
                                .to_owned()
                        };
                        Ok((Some(pointer), artifact.manifest))
                    })()
                } else {
                    (|| -> Result<(Option<String>, Value)> {
                        let receipt = crate::ingestion::refresh_request_guarded(
                            &state.db,
                            &state.directory.join("ingestion"),
                            &job.request,
                            &job.id,
                            &check,
                        )?;
                        check()?;
                        Ok((None, receipt))
                    })()
                };
                match outcome {
                    Ok((artifact, manifest)) => {
                        state
                            .control
                            .finish(&job.id, token, artifact.as_deref(), &manifest)?;
                        if state.storage.is_some() {
                            let path = state.directory.join("exports").join(&job.id).join(token);
                            if path.exists() {
                                std::fs::remove_dir_all(path)?;
                            }
                        }
                    }
                    Err(error) => {
                        tracing::error!(job=%job.id,error=%error,"background job failed");
                        state
                            .control
                            .fail(&job.id, token, &error.to_string(), true)?;
                    }
                }
                Ok(true)
            })();
            match result {
                Ok(true) => continue,
                Err(error) => tracing::error!(error=%error,"background lane error"),
                _ => {}
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    })
}

fn cleanup(state: &AppState) -> Result<()> {
    for (id, pointer) in state.control.expired_artifacts(8)? {
        if let Some(storage) = &state.storage {
            storage.delete(&pointer)?;
        } else {
            let path = Path::new(&pointer);
            let root = state.directory.join("exports");
            if path.exists() && path.canonicalize()?.starts_with(root.canonicalize()?) {
                std::fs::remove_dir_all(path.parent().context("artifact parent")?)?;
            }
        }
        state.control.forget_expired_artifact(&id)?;
    }
    Ok(())
}

/// Reclaim abandoned files after a killed owner without removing a current
/// attempt or an unexpired local download. Only our UUID-shaped directories
/// are traversed; symlinks and unrelated files are never followed.
fn cleanup_local_attempts(root: &Path, control: &crate::control::ControlStore) -> Result<()> {
    if !root.exists() {
        return Ok(());
    }
    for entry in std::fs::read_dir(root)?.take(128) {
        let entry = entry?;
        let id = entry.file_name().to_string_lossy().into_owned();
        if !entry.file_type()?.is_dir() || uuid::Uuid::parse_str(&id).is_err() {
            continue;
        }
        let job = control.get(&id)?;
        for attempt in std::fs::read_dir(entry.path())?.take(16) {
            let attempt = attempt?;
            let token = attempt.file_name().to_string_lossy().into_owned();
            if !attempt.file_type()?.is_dir() || uuid::Uuid::parse_str(&token).is_err() {
                continue;
            }
            let age = attempt
                .metadata()?
                .modified()?
                .elapsed()
                .unwrap_or_default();
            let absolute = attempt.path().canonicalize()?;
            let protected = job.as_ref().is_some_and(|job| {
                (job.status == "running" && job.attempt_token.as_deref() == Some(&token))
                    || (job.status == "completed"
                        && job.expires_at > chrono::Utc::now().timestamp()
                        && job
                            .artifact_path
                            .as_deref()
                            .is_some_and(|pointer| Path::new(pointer).starts_with(&absolute)))
            });
            if !protected && age >= Duration::from_secs(25 * 3600) {
                std::fs::remove_dir_all(attempt.path())?;
            }
        }
        match std::fs::remove_dir(entry.path()) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs::{self, File, FileTimes},
        time::SystemTime,
    };

    fn old_directory(path: &Path) -> Result<()> {
        fs::create_dir_all(path)?;
        File::open(path)?.set_times(
            FileTimes::new().set_modified(SystemTime::now() - Duration::from_secs(26 * 3600)),
        )?;
        Ok(())
    }

    #[test]
    fn orphan_cleanup_preserves_running_attempts_and_live_downloads() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().join("exports");
        let control =
            crate::control::ControlStore::open(directory.path().join("control.sqlite"), 4, 30)?;
        let queued = control.enqueue(&json!({}))?;
        let claimed = control.claim("export")?.context("claimed")?;
        let token = claimed.attempt_token.as_deref().context("token")?;
        let live = root.join(&queued.id).join(token);
        old_directory(&live)?;
        let orphan = root.join(&queued.id).join(uuid::Uuid::new_v4().to_string());
        old_directory(&orphan)?;
        let recent = root
            .join(uuid::Uuid::new_v4().to_string())
            .join(uuid::Uuid::new_v4().to_string());
        fs::create_dir_all(&recent)?;
        cleanup_local_attempts(&root, &control)?;
        assert!(live.exists());
        assert!(!orphan.exists());
        assert!(recent.exists());
        let artifact = live.canonicalize()?.join("export.zip");
        fs::write(&artifact, b"test")?;
        old_directory(&live)?;
        control.finish(&queued.id, token, artifact.to_str(), &json!({}))?;
        cleanup_local_attempts(&root, &control)?;
        assert!(artifact.exists());
        Ok(())
    }

    #[cfg(unix)]
    #[test]
    fn orphan_cleanup_does_not_follow_symlinks() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().join("exports");
        let external = directory.path().join("external");
        let target = external.join(uuid::Uuid::new_v4().to_string());
        old_directory(&target)?;
        fs::create_dir_all(&root)?;
        std::os::unix::fs::symlink(&external, root.join(uuid::Uuid::new_v4().to_string()))?;
        let control =
            crate::control::ControlStore::open(directory.path().join("control.sqlite"), 4, 30)?;
        cleanup_local_attempts(&root, &control)?;
        assert!(target.exists());
        Ok(())
    }
}

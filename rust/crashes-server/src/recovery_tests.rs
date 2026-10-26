//! Native-engine failure tests for paired backups and offline recovery.

use crate::{control::ControlStore, db::Database, recovery};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};

struct Fixture {
    directory: tempfile::TempDir,
    library: PathBuf,
    database: Database,
    control: ControlStore,
}

fn fixture() -> Result<Option<Fixture>> {
    let library = crate::test_support::library();
    let directory = tempfile::tempdir()?;
    let database = Database::open(
        &directory.path().join("current.duckdb"),
        &library,
        "256MB",
        1,
        &directory.path().join("spill"),
    )?;
    let control = ControlStore::open(directory.path().join("control.sqlite"), 8, 180)?;
    database.execute("CREATE TABLE crashes(crash_record_id VARCHAR PRIMARY KEY,crash_date TIMESTAMP,injuries_total INTEGER)",&[])?;
    database.execute("INSERT INTO crashes VALUES ('original','2024-01-15 12:30:45',NULL),('second','2024-02-29 00:00:00',2)",&[])?;
    Ok(Some(Fixture {
        directory,
        library,
        database,
        control,
    }))
}

fn backup(fixture: &Fixture) -> Result<(PathBuf, Value)> {
    let root = fixture.directory.path().join("backups");
    let manifest = recovery::backup(&fixture.database, &fixture.control, &root, None)?;
    let path = root.join(manifest["id"].as_str().context("backup id missing")?);
    Ok((path, manifest))
}

fn open_restored(fixture: &Fixture, path: &Path) -> Result<Database> {
    Database::open(
        &path.join("current.duckdb"),
        &fixture.library,
        "256MB",
        1,
        &path.join("spill"),
    )
}

#[test]
fn native_paired_backup_restores_fact_snapshot_and_original_queue_ids_with_fenced_leases()
-> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let expected = fixture
        .database
        .query("SELECT * FROM crashes ORDER BY crash_record_id", &[])?;
    let submitted=fixture.control.enqueue(&json!({"location":{"resolved_area":{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]}}},"datasets":["crashes"]}))?;
    let first = fixture.control.claim("export")?.context("first attempt")?;
    let (snapshot, manifest) = backup(&fixture)?;
    assert_eq!(
        manifest["files"].as_array().context("backup files")?.len(),
        2
    );
    fixture.database.execute("DELETE FROM crashes", &[])?;
    fixture.control.cancel(&submitted.id)?;
    let later = fixture
        .control
        .enqueue(&json!({"location":"not present at backup"}))?;
    let destination = fixture.directory.path().join("restored");
    recovery::restore(&snapshot, &destination)?;
    let restored = open_restored(&fixture, &destination)?;
    assert_eq!(
        restored.query("SELECT * FROM crashes ORDER BY crash_record_id", &[])?,
        expected
    );
    let control = ControlStore::open(destination.join("control.sqlite"), 8, 180)?;
    let recovered = control
        .get(&submitted.id)?
        .context("original submission was lost")?;
    assert_eq!(recovered.request, submitted.request);
    assert_eq!(recovered.status, "queued");
    assert_eq!(recovered.deadline_at, submitted.deadline_at);
    assert!(control.get(&later.id)?.is_none());
    assert!(
        control
            .finish(
                &first.id,
                first.attempt_token.as_deref().context("old token")?,
                Some("private"),
                &json!({})
            )
            .is_err()
    );
    let next = control.claim("export")?.context("restored claim")?;
    assert_eq!(next.id, submitted.id);
    assert_eq!(next.attempt, 2);
    control.finish(
        &next.id,
        next.attempt_token.as_deref().context("new token")?,
        Some("private"),
        &json!({}),
    )?;
    assert!(!destination.join(".restore-in-progress").exists());
    Ok(())
}

#[test]
fn native_checkpoint_backup_never_copies_half_of_a_concurrent_publication() -> Result<()> {
    use std::sync::{
        Barrier,
        atomic::{AtomicBool, Ordering},
    };
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    fixture
        .database
        .execute("CREATE TABLE generation_receipts(generation INTEGER)", &[])?;
    let ready = Barrier::new(2);
    let stop = AtomicBool::new(false);
    let snapshot = std::thread::scope(|scope| -> Result<PathBuf> {
        let writer = scope.spawn(|| -> Result<()> {
            for generation in 0..100 {
                fixture.database.transaction(|session| {
                    session.execute(
                        "UPDATE crashes SET injuries_total=$1 WHERE crash_record_id='original'",
                        &[json!(generation)],
                    )?;
                    session.execute(
                        "UPDATE crashes SET injuries_total=$1 WHERE crash_record_id='second'",
                        &[json!(generation)],
                    )?;
                    session.execute(
                        "INSERT INTO generation_receipts VALUES($1)",
                        &[json!(generation)],
                    )
                })?;
                if generation == 0 {
                    ready.wait();
                }
                if stop.load(Ordering::Acquire) {
                    break;
                }
            }
            Ok(())
        });
        ready.wait();
        let result = backup(&fixture).map(|(snapshot, _)| snapshot);
        stop.store(true, Ordering::Release);
        writer
            .join()
            .map_err(|_| anyhow::anyhow!("native publication thread panicked"))??;
        result
    })?;
    let destination = fixture.directory.path().join("concurrent-restore");
    recovery::restore(&snapshot, &destination)?;
    let restored = open_restored(&fixture, &destination)?;
    let rows=restored.query("SELECT count(DISTINCT injuries_total) AS versions,min(injuries_total) AS version,(SELECT max(generation) FROM generation_receipts) AS receipt FROM crashes",&[])?;
    assert_eq!(rows[0]["versions"], 1);
    assert_eq!(rows[0]["version"], rows[0]["receipt"]);
    Ok(())
}

#[test]
fn restored_committed_deletion_receipt_reconciles_sqlite_audit_without_redeleting() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let request = json!({"table_name":"crashes","confirm":true,"backup":false,"operation_id":"deletion-before-control-ack"});
    crate::mutations::delete_data(&fixture.database, &request)?;
    assert!(
        !fixture
            .control
            .export_snapshot()?
            .records
            .contains_key("data_deletion_logs")
    );
    let (snapshot, _) = backup(&fixture)?;
    let destination = fixture.directory.path().join("receipt-restore");
    recovery::restore(&snapshot, &destination)?;
    let restored = open_restored(&fixture, &destination)?;
    let control = ControlStore::open(destination.join("control.sqlite"), 8, 180)?;
    crate::mutations::reconcile_deletions(&restored, &control)?;
    crate::mutations::reconcile_deletions(&restored, &control)?;
    let operations = control.export_snapshot()?;
    let audits = &operations.records["data_deletion_logs"];
    assert_eq!(audits.len(), 1);
    assert_eq!(audits[0]["operation_id"], "deletion-before-control-ack");
    assert_eq!(audits[0]["records_deleted"], 2);
    assert_eq!(
        restored.query("SELECT count(*) AS n FROM crashes", &[])?[0]["n"],
        0
    );
    Ok(())
}

#[test]
fn corrupt_native_snapshot_is_rejected_before_destination_is_created() -> Result<()> {
    use std::io::Write;
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let (snapshot, _) = backup(&fixture)?;
    fs::OpenOptions::new()
        .append(true)
        .open(snapshot.join("current.duckdb"))?
        .write_all(b"corruption")?;
    let destination = fixture.directory.path().join("corrupt-restore");
    assert!(recovery::restore(&snapshot, &destination).is_err());
    assert!(!destination.exists());
    Ok(())
}

#[test]
fn interrupted_restore_resumes_same_snapshot_after_only_first_file_was_installed() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let (snapshot, manifest) = backup(&fixture)?;
    let destination = fixture.directory.path().join("interrupted");
    fs::create_dir(&destination)?;
    fs::write(
        destination.join(".restore-in-progress"),
        serde_json::to_vec(&manifest)?,
    )?;
    fs::copy(
        snapshot.join("current.duckdb"),
        destination.join("current.duckdb"),
    )?;
    fs::write(
        destination.join("control.sqlite"),
        b"interrupted partial installation",
    )?;
    recovery::restore(&snapshot, &destination)?;
    let restored = open_restored(&fixture, &destination)?;
    assert_eq!(
        restored.query("SELECT count(*) AS n FROM crashes", &[])?[0]["n"],
        2
    );
    let control = ControlStore::open(destination.join("control.sqlite"), 8, 180)?;
    assert!(control.list(None, 10)?.is_empty());
    assert!(!destination.join(".restore-in-progress").exists());
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(destination.join("restored-from.json"))?)?,
        manifest
    );
    Ok(())
}

#[test]
fn interrupted_restore_rejects_a_different_snapshot_without_overwriting_partial_state() -> Result<()>
{
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let (_, first) = backup(&fixture)?;
    fixture
        .database
        .execute("INSERT INTO crashes VALUES ('new','2024-03-01',0)", &[])?;
    let (second_snapshot, _) = backup(&fixture)?;
    let destination = fixture.directory.path().join("wrong-resume");
    fs::create_dir(&destination)?;
    fs::write(
        destination.join(".restore-in-progress"),
        serde_json::to_vec(&first)?,
    )?;
    fs::write(
        destination.join("current.duckdb"),
        b"preserve partial first snapshot",
    )?;
    let before = fs::read(destination.join("current.duckdb"))?;
    assert!(recovery::restore(&second_snapshot, &destination).is_err());
    assert_eq!(fs::read(destination.join("current.duckdb"))?, before);
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(destination.join(".restore-in-progress"))?)?,
        first
    );
    Ok(())
}

#[test]
fn restore_cannot_overwrite_populated_or_live_owner_destinations() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    let (snapshot, _) = backup(&fixture)?;
    let occupied = fixture.directory.path().join("occupied");
    fs::create_dir(&occupied)?;
    fs::write(occupied.join("current.duckdb"), b"existing data")?;
    fs::write(occupied.join("control.sqlite"), b"existing control")?;
    assert!(recovery::restore(&snapshot, &occupied).is_err());
    assert_eq!(fs::read(occupied.join("current.duckdb"))?, b"existing data");
    assert_eq!(
        fs::read(occupied.join("control.sqlite"))?,
        b"existing control"
    );
    let error = recovery::restore(&snapshot, fixture.directory.path())
        .expect_err("live owner must reject restore");
    assert!(error.to_string().contains("active owner"));
    assert_eq!(
        fixture
            .database
            .query("SELECT count(*) AS n FROM crashes", &[])?[0]["n"],
        2
    );
    Ok(())
}

fn receipts(database: &Database) -> Result<()> {
    database.execute("CREATE TABLE ingestion_publications(operation_id VARCHAR PRIMARY KEY,committed_at TIMESTAMPTZ,receipt JSON)",&[])?;
    database.execute("CREATE TABLE fact_snapshot_imports(import_id VARCHAR PRIMARY KEY,imported_at TIMESTAMPTZ,receipt JSON)",&[])?;
    Ok(())
}

fn publication(
    database: &Database,
    id: &str,
    time: &str,
    datasets: &[&str],
    complete: bool,
    window: bool,
) -> Result<()> {
    let datasets=datasets.iter().map(|dataset|((*dataset).to_owned(),json!({"source_manifest":{"profiling_only":!complete,"source_scope":if window{"event_date_window"}else{"full_dataset"}}}))).collect::<serde_json::Map<_,_>>();
    let receipt = json!({"operation_id":id,"production_complete":complete,"profiling_only":!complete,"datasets":datasets});
    database.execute(
        "INSERT INTO ingestion_publications VALUES($1,CAST($2 AS TIMESTAMPTZ),$3)",
        &[json!(id), json!(time), json!(receipt.to_string())],
    )
}

fn snapshot_receipt(database: &Database, id: &str, time: &str, valid: bool) -> Result<()> {
    let receipt = json!({"import_id":id,"production_snapshot":valid,"source_kind":"postgresql_repeatable_read"});
    database.execute(
        "INSERT INTO fact_snapshot_imports VALUES($1,CAST($2 AS TIMESTAMPTZ),$3)",
        &[json!(id), json!(time), json!(receipt.to_string())],
    )
}

fn assert_incomplete(database: &Database) -> Result<()> {
    let error = recovery::assert_complete(database)
        .err()
        .context("incomplete source state was incorrectly accepted")?;
    ensure!(
        error
            .to_string()
            .contains("latest complete production publication receipts required"),
        "readiness rejected the fixture for an unrelated error: {error}"
    );
    Ok(())
}

#[test]
fn latest_profiling_publication_blocks_old_complete_history() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    receipts(&fixture.database)?;
    publication(
        &fixture.database,
        "old-complete",
        "2026-01-01T00:00:00Z",
        &crate::sources::DATASETS,
        true,
        false,
    )?;
    publication(
        &fixture.database,
        "new-incomplete",
        "2026-02-01T00:00:00Z",
        &["people"],
        false,
        false,
    )?;
    assert_incomplete(&fixture.database)?;
    Ok(())
}

#[test]
fn newer_verified_postgres_snapshot_supersedes_older_profiling_publication() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    receipts(&fixture.database)?;
    publication(
        &fixture.database,
        "old-profiling",
        "2026-01-01T00:00:00Z",
        &["people"],
        false,
        false,
    )?;
    snapshot_receipt(
        &fixture.database,
        "new-full-snapshot",
        "2026-02-01T00:00:00Z",
        true,
    )?;
    recovery::assert_complete(&fixture.database)?;
    Ok(())
}

#[test]
fn newer_invalid_snapshot_cannot_be_masked_by_old_complete_publications() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    receipts(&fixture.database)?;
    publication(
        &fixture.database,
        "old-complete",
        "2026-01-01T00:00:00Z",
        &crate::sources::DATASETS,
        true,
        false,
    )?;
    snapshot_receipt(
        &fixture.database,
        "new-invalid-snapshot",
        "2026-02-01T00:00:00Z",
        false,
    )?;
    assert_incomplete(&fixture.database)?;
    Ok(())
}

#[test]
fn complete_event_windows_cannot_bootstrap_without_full_historical_baseline() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    receipts(&fixture.database)?;
    publication(
        &fixture.database,
        "window-only",
        "2026-02-01T00:00:00Z",
        &crate::sources::DATASETS,
        true,
        true,
    )?;
    assert_incomplete(&fixture.database)?;
    let datasets = crate::sources::DATASETS
        .iter()
        .map(|dataset| {
            (
                dataset.to_string(),
                json!({"source_manifest":{"source_scope":"event_date_window_with_history"}}),
            )
        })
        .collect::<serde_json::Map<_, _>>();
    fixture.database.execute("UPDATE ingestion_publications SET receipt=json_merge_patch(receipt, ?::JSON) WHERE operation_id='window-only'", &[json!(json!({"datasets":datasets}).to_string())])?;
    assert_incomplete(&fixture.database)?;
    Ok(())
}

#[test]
fn valid_daily_window_updates_preserve_an_older_verified_full_snapshot() -> Result<()> {
    let Some(fixture) = fixture()? else {
        return Ok(());
    };
    receipts(&fixture.database)?;
    snapshot_receipt(
        &fixture.database,
        "historical-baseline",
        "2026-01-01T00:00:00Z",
        true,
    )?;
    publication(
        &fixture.database,
        "daily-core",
        "2026-02-01T00:00:00Z",
        &["crashes", "people", "vehicles"],
        true,
        true,
    )?;
    recovery::assert_complete(&fixture.database)?;
    Ok(())
}

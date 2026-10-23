//! Durable operational state. Analytical data never belongs in this SQLite file.

use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Utc};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use uuid::Uuid;

const COLUMNS: &str = "id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,attempt,max_attempts,attempt_token,lease_until,cancel_requested,artifact_path,manifest_json,error,started_at,completed_at";

fn operation_line(reader: &mut impl BufRead) -> Result<Option<String>> {
    let mut line = String::new();
    let size = std::io::Read::take(reader, 8 * 1_048_576 + 1).read_line(&mut line)?;
    ensure!(size <= 8 * 1_048_576, "operational record exceeds 8 MiB");
    Ok((size > 0).then_some(line))
}

/// A durable request. Attempt tokens and private object paths never enter public JSON.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    pub id: String,
    pub kind: String,
    pub status: String,
    pub request: Value,
    pub created_at: i64,
    pub updated_at: i64,
    pub deadline_at: i64,
    pub expires_at: i64,
    pub attempt: u32,
    pub max_attempts: u32,
    #[serde(skip_serializing)]
    pub attempt_token: Option<String>,
    #[serde(skip_serializing)]
    pub lease_until: Option<i64>,
    pub cancel_requested: bool,
    #[serde(skip_serializing)]
    pub artifact_path: Option<String>,
    pub manifest: Option<Value>,
    pub error: Option<String>,
    pub started_at: Option<i64>,
    pub completed_at: Option<i64>,
}

impl Job {
    /// Return the existing browser export status contract without credentials or paths.
    pub fn public_json(&self) -> Value {
        let mut value = serde_json::to_value(self).unwrap_or(Value::Null);
        if let Some(object) = value.as_object_mut() {
            object.remove("request");
            for (name, timestamp) in [
                ("created_at", self.created_at),
                ("updated_at", self.updated_at),
                ("deadline_at", self.deadline_at),
                ("expires_at", self.expires_at),
            ] {
                object.insert(
                    name.into(),
                    DateTime::<Utc>::from_timestamp(timestamp, 0)
                        .map(|time| Value::String(time.to_rfc3339()))
                        .unwrap_or(Value::Null),
                );
            }
            object.insert(
                "download_url".into(),
                if self.status == "completed" && self.kind == "export" {
                    Value::String(format!("/exports/{}/download", self.id))
                } else {
                    Value::Null
                },
            );
        }
        value
    }
}

/// One local durable queue, safe across threads and brief overlapping process handoffs.
#[derive(Debug, Clone)]
pub struct ControlStore {
    path: PathBuf,
    pub(crate) max_active: u32,
    lease_seconds: i64,
}

/// Submission limits. Deadlines span queue wait and all retries.
#[derive(Debug, Clone)]
pub struct JobOptions {
    pub timeout_seconds: i64,
    pub ttl_seconds: i64,
    pub max_attempts: u32,
}

/// A fixed UTC interval schedule. Legacy cron definitions are retained verbatim
/// in imported records until an operator explicitly maps them to this contract.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Schedule {
    pub id: String,
    pub kind: String,
    pub request: Value,
    pub enabled: bool,
    pub interval_seconds: i64,
    pub next_run_at: i64,
    pub timeout_seconds: i64,
    pub max_attempts: u32,
}

/// Offline migration envelope, including opaque production records and original IDs.
/// This file contains private operational data and must never be publicly served.
#[derive(Debug, Serialize, Deserialize)]
pub struct OperationalSnapshot {
    pub schema_version: u32,
    #[serde(serialize_with = "serialize_snapshot_jobs")]
    pub jobs: Vec<Job>,
    pub schedules: Vec<Schedule>,
    #[serde(default)]
    pub configurations: BTreeMap<String, Value>,
    #[serde(default)]
    pub records: BTreeMap<String, Vec<Value>>,
}

fn serialize_snapshot_jobs<S: serde::Serializer>(
    jobs: &[Job],
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    let records = jobs
        .iter()
        .map(|job| {
            let mut value = serde_json::to_value(job).map_err(serde::ser::Error::custom)?;
            if let Some(object) = value.as_object_mut() {
                object.insert(
                    "artifact_path".into(),
                    job.artifact_path
                        .as_ref()
                        .map(|path| Value::String(path.clone()))
                        .unwrap_or(Value::Null),
                );
            }
            Ok(value)
        })
        .collect::<std::result::Result<Vec<_>, S::Error>>()?;
    records.serialize(serializer)
}

impl Default for JobOptions {
    fn default() -> Self {
        Self {
            timeout_seconds: 600,
            ttl_seconds: 86400,
            max_attempts: 3,
        }
    }
}

fn now() -> Result<i64> {
    Ok(i64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
    )?)
}

fn legacy_time(value: &Value) -> Result<i64> {
    if let Some(timestamp) = value.as_i64() {
        return Ok(timestamp);
    }
    let raw = value
        .as_str()
        .context("legacy operational timestamp missing")?;
    if let Ok(time) = DateTime::parse_from_rfc3339(raw) {
        return Ok(time.timestamp());
    }
    Ok(
        chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f")
            .or_else(|_| chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f"))?
            .and_utc()
            .timestamp(),
    )
}

fn decode(row: &rusqlite::Row<'_>) -> rusqlite::Result<Job> {
    fn json(row: &rusqlite::Row<'_>, index: usize) -> rusqlite::Result<Value> {
        let raw: String = row.get(index)?;
        serde_json::from_str(&raw).map_err(|error| {
            rusqlite::Error::FromSqlConversionFailure(
                index,
                rusqlite::types::Type::Text,
                Box::new(error),
            )
        })
    }
    Ok(Job {
        id: row.get(0)?,
        kind: row.get(1)?,
        status: row.get(2)?,
        request: json(row, 3)?,
        created_at: row.get(4)?,
        updated_at: row.get(5)?,
        deadline_at: row.get(6)?,
        expires_at: row.get(7)?,
        attempt: row.get(8)?,
        max_attempts: row.get(9)?,
        attempt_token: row.get(10)?,
        lease_until: row.get(11)?,
        cancel_requested: row.get(12)?,
        artifact_path: row.get(13)?,
        manifest: if row.get::<_, Option<String>>(14)?.is_some() {
            Some(json(row, 14)?)
        } else {
            None
        },
        error: row.get(15)?,
        started_at: row.get(16)?,
        completed_at: row.get(17)?,
    })
}

fn import_legacy_record(
    connection: &Connection,
    table: &str,
    record: &Value,
    explicit_jobs: &[Job],
    time: i64,
) -> Result<()> {
    ensure!(
        matches!(
            table,
            "scheduled_jobs"
                | "job_executions"
                | "export_jobs"
                | "data_deletion_logs"
                | "ingestion_checkpoints"
                | "ingestion_runs"
                | "ingestion_sources"
                | "system_configurations"
                | "api_keys"
        ),
        "unsupported legacy operational table"
    );
    let mut record = record.clone();
    if table == "scheduled_jobs" {
        // Preserve the deployed cadence until an explicit cron edit.
        if record["recurrence_type"] == "custom_cron"
            && record.get("legacy_cron_daily_fallback").is_none()
        {
            record["legacy_cron_daily_fallback"] = Value::Bool(true);
        }
        crate::admin::validate_job_record(&record)?;
    }
    if table == "job_executions" && matches!(record["status"].as_str(), Some("pending" | "running"))
    {
        let execution_id = record["execution_id"]
            .as_str()
            .context("active execution identifier missing")?;
        ensure!(
            explicit_jobs.iter().any(|job| job.id == execution_id),
            "legacy active job executions must be drained or explicitly mapped before cutover"
        );
    }
    if table == "export_jobs"
        && !explicit_jobs
            .iter()
            .any(|job| record["id"].as_str() == Some(job.id.as_str()))
    {
        let id = record["id"].as_str().context("legacy export ID missing")?;
        let status = record["status"]
            .as_str()
            .context("legacy export status missing")?;
        ensure!(
            !matches!(status, "queued" | "running" | "pending"),
            "legacy active exports must be drained or explicitly mapped before cutover"
        );
        ensure!(
            matches!(status, "completed" | "failed" | "cancelled" | "expired"),
            "unknown legacy export status"
        );
        let created = legacy_time(&record["created_at"])?;
        let expires = legacy_time(&record["expires_at"])?;
        let status = if expires <= time { "expired" } else { status };
        let mut location = record["request"].clone();
        let datasets = location
            .as_object_mut()
            .and_then(|object| object.remove("datasets"))
            .unwrap_or_else(|| serde_json::json!(["crashes"]));
        let request = serde_json::json!({"location":location,"datasets":datasets});
        let manifest = record
            .get("manifest")
            .filter(|value| !value.is_null())
            .map(serde_json::to_string)
            .transpose()?;
        connection.execute("INSERT INTO rust_jobs(id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,attempt,max_attempts,artifact_path,manifest_json,error) VALUES (?,'export',?,?,?,?,?,?,?,?,?,?,?)",
            params![id,status,serde_json::to_string(&request)?,created,time,created+1800,expires,record["attempts"].as_i64().unwrap_or(0),3,record["object_key"].as_str(),manifest,record["error"].as_str()])?;
    }
    let id = record
        .get("id")
        .or_else(|| record.get("source_id"))
        .or_else(|| record.get("endpoint"))
        .context("legacy record requires its original ID")?;
    let id = id
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| id.to_string());
    connection.execute(
        "INSERT INTO rust_imported_records VALUES (?,?,?)",
        params![table, id, serde_json::to_string(&record)?],
    )?;
    Ok(())
}

impl ControlStore {
    /// Open/create a WAL queue. Mount its parent directory on the persistent volume.
    pub fn open(path: impl AsRef<Path>, max_active: u32, lease_seconds: i64) -> Result<Self> {
        ensure!(max_active > 0, "queue capacity must be positive");
        ensure!(
            (5..=3600).contains(&lease_seconds),
            "lease must be between 5 and 3600 seconds"
        );
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let store = Self {
            path,
            max_active,
            lease_seconds,
        };
        let connection = store.connect()?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.execute_batch("CREATE TABLE IF NOT EXISTS rust_jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
            ('queued','running','completed','failed','cancelled','expired')),
            request_json TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            deadline_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
            attempt_token TEXT, lease_until INTEGER, cancel_requested INTEGER NOT NULL DEFAULT 0,
            artifact_path TEXT, manifest_json TEXT, error TEXT, dedupe_key TEXT UNIQUE,
            not_before INTEGER NOT NULL DEFAULT 0, started_at INTEGER, completed_at INTEGER);
            CREATE INDEX IF NOT EXISTS rust_job_queue ON rust_jobs(kind,status,not_before,created_at);
            CREATE TABLE IF NOT EXISTS rust_schedules (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0, interval_seconds INTEGER NOT NULL,
            next_run_at INTEGER NOT NULL, timeout_seconds INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS rust_control_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rust_configuration (key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rust_imported_records (source_table TEXT NOT NULL,source_id TEXT NOT NULL,record_json TEXT NOT NULL,PRIMARY KEY(source_table,source_id));
            INSERT OR IGNORE INTO rust_control_metadata VALUES ('schema_version','1');")?;
        let existing = {
            let mut statement = connection.prepare("PRAGMA table_info(rust_jobs)")?;
            let rows = statement.query_map([], |row| row.get::<_, String>(1))?;
            rows.collect::<rusqlite::Result<Vec<_>>>()?
        };
        for name in ["started_at", "completed_at"] {
            if !existing.iter().any(|column| column == name) {
                connection.execute(
                    &format!("ALTER TABLE rust_jobs ADD COLUMN {name} INTEGER"),
                    [],
                )?;
            }
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&store.path, std::fs::Permissions::from_mode(0o600))?;
        }
        Ok(store)
    }

    pub(crate) fn connect(&self) -> Result<Connection> {
        let connection = Connection::open(&self.path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.pragma_update(None, "synchronous", "FULL")?;
        connection.pragma_update(None, "foreign_keys", true)?;
        Ok(connection)
    }

    /// Queue a frozen export request under the configured capacity bound.
    pub fn enqueue(&self, request: &Value) -> Result<Job> {
        self.enqueue_kind("export", request, &JobOptions::default())
    }

    /// Queue an export or ingestion operation. The request must already resolve geometry.
    pub fn enqueue_kind(&self, kind: &str, request: &Value, options: &JobOptions) -> Result<Job> {
        ensure!(
            matches!(kind, "export" | "ingestion"),
            "unsupported job kind"
        );
        ensure!(
            (1..=86400).contains(&options.timeout_seconds),
            "invalid deadline"
        );
        ensure!(
            (1..=2_592_000).contains(&options.ttl_seconds),
            "invalid expiry"
        );
        ensure!(
            (1..=10).contains(&options.max_attempts),
            "invalid retry budget"
        );
        let serialized = serde_json::to_string(request)?;
        ensure!(serialized.len() <= 1_048_576, "request exceeds 1 MiB");
        let time = now()?;
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        self.maintain(&transaction, time)?;
        let active: u32 = transaction.query_row(
            "SELECT count(*) FROM rust_jobs WHERE status IN ('queued','running')",
            [],
            |row| row.get(0),
        )?;
        ensure!(active < self.max_active, "queue full; retry later");
        let id = Uuid::new_v4().simple().to_string();
        transaction.execute(
            "INSERT INTO rust_jobs
            (id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,max_attempts)
            VALUES (?,?,'queued',?,?,?,?,?,?)",
            params![
                id,
                kind,
                serialized,
                time,
                time,
                time + options.timeout_seconds,
                time + options.ttl_seconds,
                options.max_attempts
            ],
        )?;
        let job = Self::read(&transaction, &id)?.context("new job missing")?;
        transaction.commit()?;
        Ok(job)
    }

    pub(crate) fn maintain(&self, connection: &Connection, time: i64) -> Result<()> {
        connection.execute("UPDATE rust_jobs SET status='failed',error='Job deadline exceeded',updated_at=?,completed_at=?,attempt_token=NULL,lease_until=NULL
            WHERE status IN ('queued','running') AND deadline_at<=?", params![time,time,time])?;
        connection.execute("UPDATE rust_jobs SET status='cancelled',updated_at=?,completed_at=?,attempt_token=NULL,lease_until=NULL
            WHERE status IN ('queued','running') AND cancel_requested=1", params![time,time])?;
        connection.execute("UPDATE rust_jobs SET status=CASE WHEN attempt<max_attempts THEN 'queued' ELSE 'failed' END,
            error='Worker lease expired',updated_at=?,completed_at=CASE WHEN attempt<max_attempts THEN NULL ELSE ? END,attempt_token=NULL,lease_until=NULL,not_before=?
            WHERE status='running' AND lease_until<=?", params![time,time,time,time])?;
        connection.execute("UPDATE rust_jobs SET status='expired',updated_at=? WHERE status='completed' AND expires_at<=?", params![time,time])?;
        Ok(())
    }

    fn read(connection: &Connection, id: &str) -> Result<Option<Job>> {
        Ok(connection
            .query_row(
                &format!("SELECT {COLUMNS} FROM rust_jobs WHERE id=?"),
                [id],
                decode,
            )
            .optional()?)
    }

    /// Claim one attempt. Expired leases are recovered without stealing active leases.
    pub fn claim(&self, kind: &str) -> Result<Option<Job>> {
        let time = now()?;
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        self.maintain(&transaction, time)?;
        let id: Option<String> = transaction.query_row("SELECT id FROM rust_jobs WHERE kind=? AND status='queued' AND not_before<=? ORDER BY created_at,id LIMIT 1", params![kind,time], |row| row.get(0)).optional()?;
        let result = if let Some(id) = id {
            transaction.execute("UPDATE rust_jobs SET status='running',attempt=attempt+1,attempt_token=?,lease_until=?,updated_at=?,started_at=COALESCE(started_at,?),completed_at=NULL,error=NULL WHERE id=?",
                params![Uuid::new_v4().simple().to_string(),time+self.lease_seconds,time,time,id])?;
            Self::read(&transaction, &id)?
        } else {
            None
        };
        transaction.commit()?;
        Ok(result)
    }

    /// Fence interrupted attempts immediately after acquiring the exclusive DuckDB
    /// owner lock and before starting workers or serving requests. Never call this
    /// from a second process while another owner can still publish analytical data.
    pub fn recover_interrupted(&self) -> Result<usize> {
        let time = now()?;
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let recovered=transaction.execute("UPDATE rust_jobs SET
            status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN attempt>=max_attempts OR deadline_at<=? THEN 'failed' ELSE 'queued' END,
            error='Owner restarted; previous attempt fenced',updated_at=?,
            completed_at=CASE WHEN cancel_requested=1 OR attempt>=max_attempts OR deadline_at<=? THEN ? ELSE NULL END,
            attempt_token=NULL,lease_until=NULL,not_before=? WHERE status='running'",
            params![time,time,time,time,time])?;
        self.maintain(&transaction, time)?;
        transaction.commit()?;
        Ok(recovered)
    }

    /// Page ingestion attempts whose analytical commit may precede queue finish.
    /// Unlike `list`, this does not expire their deadline before reconciliation.
    pub(crate) fn unreconciled_ingestion_ids(&self, after: &str) -> Result<Vec<String>> {
        let connection = self.connect()?;
        let mut statement = connection.prepare("SELECT id FROM rust_jobs WHERE kind='ingestion' AND status IN ('queued','running','failed') AND id>? ORDER BY id LIMIT 500")?;
        let rows = statement.query_map([after], |row| row.get(0))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Reconcile an immutable DuckDB publication while holding the exclusive
    /// owner lock, before workers start. A committed receipt is authoritative
    /// even after the final attempt or deadline, but cannot undo cancellation.
    pub(crate) fn reconcile_ingestion_publication(
        &self,
        id: &str,
        receipt: &Value,
    ) -> Result<usize> {
        ensure!(
            receipt["operation_id"].as_str() == Some(id)
                && receipt["production_complete"] == true
                && receipt["profiling_only"] == false,
            "invalid committed ingestion receipt"
        );
        let completed = DateTime::parse_from_rfc3339(
            receipt["committed_at"]
                .as_str()
                .context("publication commit time missing")?,
        )?
        .timestamp();
        Ok(self.connect()?.execute("UPDATE rust_jobs SET status='completed',updated_at=?,completed_at=?,manifest_json=?,error=NULL,attempt_token=NULL,lease_until=NULL WHERE id=? AND kind='ingestion' AND status IN ('queued','running','failed') AND cancel_requested=0",
            params![now()?,completed,serde_json::to_string(receipt)?,id])?)
    }

    /// Validate ownership before every batch, publication and upload.
    pub fn check_attempt(&self, id: &str, token: &str) -> Result<()> {
        let job = self.get(id)?.context("job missing")?;
        let time = now()?;
        ensure!(
            job.status == "running"
                && !job.cancel_requested
                && job.attempt_token.as_deref() == Some(token)
                && job.lease_until.is_some_and(|deadline| deadline > time),
            "job lease lost or cancelled"
        );
        Ok(())
    }

    /// Extend a live lease; a late heartbeat cannot revive an expired attempt.
    pub fn heartbeat(&self, id: &str, token: &str) -> Result<()> {
        let time = now()?;
        let count = self.connect()?.execute("UPDATE rust_jobs SET lease_until=MIN(?,deadline_at),updated_at=?
            WHERE id=? AND attempt_token=? AND status='running' AND cancel_requested=0 AND lease_until>? AND deadline_at>?",
            params![time+self.lease_seconds,time,id,token,time,time])?;
        ensure!(count == 1, "job lease lost or cancelled");
        Ok(())
    }

    /// Publish only an already verified private artifact under the current lease token.
    pub fn finish(
        &self,
        id: &str,
        token: &str,
        artifact: Option<&str>,
        manifest: &Value,
    ) -> Result<()> {
        let time = now()?;
        let count = self.connect()?.execute("UPDATE rust_jobs SET status='completed',updated_at=?,completed_at=?,artifact_path=?,manifest_json=?,attempt_token=NULL,lease_until=NULL
            WHERE id=? AND attempt_token=? AND status='running' AND cancel_requested=0 AND lease_until>? AND deadline_at>? AND expires_at>?",
            params![time,time,artifact,serde_json::to_string(manifest)?,id,token,time,time,time])?;
        ensure!(count == 1, "stale job attempt cannot publish");
        Ok(())
    }

    /// Retry with bounded backoff, or finish an exhausted/non-retryable failure.
    pub fn fail(&self, id: &str, token: &str, error: &str, retryable: bool) -> Result<()> {
        let time = now()?;
        let count = self.connect()?.execute("UPDATE rust_jobs SET
            status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN ? AND attempt<max_attempts AND deadline_at>? THEN 'queued' ELSE 'failed' END,
            updated_at=?,error=?,completed_at=CASE WHEN cancel_requested=0 AND ? AND attempt<max_attempts AND deadline_at>? THEN NULL ELSE ? END,attempt_token=NULL,lease_until=NULL,not_before=?+MIN(3600,MAX(1,COALESCE(json_extract(request_json,'$.retry_delay_seconds'),MIN(60,5*attempt))))
            WHERE id=? AND attempt_token=? AND status='running' AND lease_until>?",
            params![retryable,time,time,error.chars().take(2000).collect::<String>(),retryable,time,time,time,id,token,time])?;
        ensure!(count == 1, "stale job attempt cannot fail or retry");
        Ok(())
    }

    /// Find a job, applying deadline and lease recovery first.
    pub fn get(&self, id: &str) -> Result<Option<Job>> {
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        self.maintain(&transaction, now()?)?;
        let job = Self::read(&transaction, id)?;
        transaction.commit()?;
        Ok(job)
    }

    /// Latest jobs, optionally restricted to the public export lane.
    pub fn list(&self, kind: Option<&str>, limit: u32) -> Result<Vec<Job>> {
        ensure!((1..=100).contains(&limit), "limit must be 1..100");
        let connection = self.connect()?;
        self.maintain(&connection, now()?)?;
        let mut statement = connection.prepare(&format!("SELECT {COLUMNS} FROM rust_jobs WHERE (? IS NULL OR kind=?) ORDER BY created_at DESC,id DESC LIMIT ?"))?;
        let rows = statement.query_map(params![kind, kind, limit], decode)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Cancellation immediately fences the worker, including an upload in progress.
    pub fn cancel(&self, id: &str) -> Result<Option<Job>> {
        let time = now()?;
        self.connect()?.execute("UPDATE rust_jobs SET cancel_requested=1,status='cancelled',updated_at=?,completed_at=?,attempt_token=NULL,lease_until=NULL WHERE id=? AND status IN ('queued','running')", params![time,time,id])?;
        self.get(id)
    }

    /// Configure an opt-in fixed cadence. First occurrence is explicit UTC Unix time.
    /// Missed intervals coalesce into one job rather than replaying an unbounded backlog.
    pub fn put_schedule(
        &self,
        id: &str,
        request: &Value,
        next_run_at: i64,
        enabled: bool,
    ) -> Result<()> {
        ensure!(!id.is_empty() && id.len() <= 128, "invalid schedule id");
        ensure!(
            (0..=253_402_300_799).contains(&next_run_at),
            "invalid schedule next_run_at"
        );
        let setting = |key: &str, default: i64| -> Result<i64> {
            match request.get(key).filter(|value| !value.is_null()) {
                Some(value) => value
                    .as_i64()
                    .with_context(|| format!("schedule {key} must be an integer")),
                None => Ok(default),
            }
        };
        let interval = setting("interval_seconds", 86400)?;
        let timeout = setting("timeout_seconds", 7200)?;
        let attempts = setting("max_attempts", 3)?;
        ensure!(
            (60..=31_536_000).contains(&interval),
            "schedule interval_seconds must be 60..31536000"
        );
        ensure!(
            (1..=86400).contains(&timeout),
            "schedule timeout_seconds must be 1..86400"
        );
        ensure!(
            (1..=11).contains(&attempts),
            "schedule max_attempts must be 1..11"
        );
        let request = serde_json::to_string(request)?;
        ensure!(request.len() <= 1_048_576, "schedule request exceeds 1 MiB");
        self.connect()?.execute("INSERT INTO rust_schedules(id,kind,request_json,enabled,interval_seconds,next_run_at,timeout_seconds,max_attempts)
            VALUES (?,'ingestion',?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET request_json=excluded.request_json,enabled=excluded.enabled,next_run_at=excluded.next_run_at,interval_seconds=excluded.interval_seconds,timeout_seconds=excluded.timeout_seconds,max_attempts=excluded.max_attempts",
            params![id,request,enabled,interval,next_run_at,timeout,attempts])?;
        Ok(())
    }

    /// Inspect persisted schedules without modifying their cadence.
    pub fn schedules(&self) -> Result<Vec<Schedule>> {
        Self::read_schedules(&self.connect()?)
    }

    fn read_schedules(connection: &Connection) -> Result<Vec<Schedule>> {
        let mut statement = connection.prepare("SELECT id,kind,request_json,enabled,interval_seconds,next_run_at,timeout_seconds,max_attempts FROM rust_schedules ORDER BY id")?;
        let records = statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, bool>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, u32>(7)?,
            ))
        })?;
        records
            .map(|record| {
                let (
                    id,
                    kind,
                    raw,
                    enabled,
                    interval_seconds,
                    next_run_at,
                    timeout_seconds,
                    max_attempts,
                ) = record?;
                Ok(Schedule {
                    id,
                    kind,
                    request: serde_json::from_str(&raw)?,
                    enabled,
                    interval_seconds,
                    next_run_at,
                    timeout_seconds,
                    max_attempts,
                })
            })
            .collect()
    }

    /// Preserve server configuration in the transactional control store.
    pub fn set_configuration(&self, key: &str, value: &Value) -> Result<()> {
        ensure!(
            !key.is_empty() && key.len() <= 128,
            "invalid configuration key"
        );
        let raw = serde_json::to_string(value)?;
        ensure!(raw.len() <= 1_048_576, "configuration exceeds 1 MiB");
        self.connect()?.execute("INSERT INTO rust_configuration VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",params![key,raw])?;
        Ok(())
    }

    /// Retrieve a configuration value without falling back to an implicit default.
    pub fn configuration(&self, key: &str) -> Result<Option<Value>> {
        let raw: Option<String> = self
            .connect()?
            .query_row(
                "SELECT value_json FROM rust_configuration WHERE key=?",
                [key],
                |row| row.get(0),
            )
            .optional()?;
        raw.map(|raw| serde_json::from_str(&raw).map_err(Into::into))
            .transpose()
    }

    /// Export one consistent control snapshot for offline review and migration.
    /// Live leases are included for diagnosis, but import always revokes them.
    pub fn export_snapshot(&self) -> Result<OperationalSnapshot> {
        let mut connection = self.connect()?;
        let transaction = connection.transaction()?;
        let jobs = {
            let mut statement = transaction.prepare(&format!(
                "SELECT {COLUMNS} FROM rust_jobs ORDER BY created_at,id"
            ))?;
            let rows = statement.query_map([], decode)?;
            rows.collect::<rusqlite::Result<Vec<_>>>()?
        };
        let schedules = Self::read_schedules(&transaction)?;
        let mut configurations = BTreeMap::new();
        {
            let mut statement = transaction
                .prepare("SELECT key,value_json FROM rust_configuration ORDER BY key")?;
            let rows = statement.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?;
            for row in rows {
                let (key, raw) = row?;
                configurations.insert(key, serde_json::from_str(&raw)?);
            }
        }
        let mut records: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        {
            let mut statement = transaction.prepare("SELECT source_table,record_json FROM rust_imported_records ORDER BY source_table,source_id")?;
            let rows = statement.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?;
            for row in rows {
                let (table, raw) = row?;
                records
                    .entry(table)
                    .or_default()
                    .push(serde_json::from_str(&raw)?);
            }
        }
        transaction.commit()?;
        Ok(OperationalSnapshot {
            schema_version: 1,
            jobs,
            schedules,
            configurations,
            records,
        })
    }

    /// Import only into an empty control store. IDs/history/artifacts are preserved;
    /// formerly running work receives a fresh attempt. Keep the owner scheduler
    /// disabled until offline import validation and deployment review are complete.
    /// Do this against a fresh path before cutover; never against the live owner.
    pub fn import_snapshot(&self, snapshot: &OperationalSnapshot) -> Result<()> {
        ensure!(
            snapshot.schema_version == 1,
            "unsupported operational snapshot schema"
        );
        ensure!(
            snapshot.jobs.len() <= 1_000_000,
            "snapshot job count exceeds import limit"
        );
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let occupied: i64 = transaction.query_row("SELECT (SELECT count(*) FROM rust_jobs)+(SELECT count(*) FROM rust_schedules)+(SELECT count(*) FROM rust_configuration)+(SELECT count(*) FROM rust_imported_records)",[],|row|row.get(0))?;
        ensure!(occupied == 0, "import requires an empty operational store");
        let time = now()?;
        let mut active = 0u32;
        for job in &snapshot.jobs {
            ensure!(
                !job.id.is_empty() && job.id.len() <= 128,
                "invalid imported job ID"
            );
            ensure!(
                matches!(job.kind.as_str(), "export" | "ingestion"),
                "unsupported imported job kind"
            );
            ensure!(
                matches!(
                    job.status.as_str(),
                    "queued" | "running" | "completed" | "cancelled" | "failed" | "expired"
                ),
                "unsupported imported job status"
            );
            ensure!(
                (1..=11).contains(&job.max_attempts),
                "invalid imported retry budget"
            );
            let mut status = job.status.as_str();
            if matches!(status, "queued" | "running") {
                status = if job.cancel_requested {
                    "cancelled"
                } else if job.deadline_at <= time || job.attempt >= job.max_attempts {
                    "failed"
                } else {
                    "queued"
                };
                if status == "queued" {
                    active = active
                        .checked_add(1)
                        .context("import queue count overflow")?;
                }
            }
            if status == "completed" && job.expires_at <= time {
                status = "expired";
            }
            let updated_at = if status == job.status {
                job.updated_at
            } else {
                time
            };
            transaction.execute("INSERT INTO rust_jobs(id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,attempt,max_attempts,cancel_requested,artifact_path,manifest_json,error,started_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                params![job.id,job.kind,status,serde_json::to_string(&job.request)?,job.created_at,updated_at,job.deadline_at,job.expires_at,job.attempt,job.max_attempts,job.cancel_requested,job.artifact_path,job.manifest.as_ref().map(serde_json::to_string).transpose()?,job.error,job.started_at,job.completed_at])?;
        }
        ensure!(
            active <= self.max_active,
            "imported active work exceeds configured queue capacity; drain or explicitly resolve it before cutover"
        );
        for schedule in &snapshot.schedules {
            ensure!(
                !schedule.id.is_empty() && schedule.id.len() <= 128 && schedule.kind == "ingestion",
                "invalid imported schedule"
            );
            ensure!(
                schedule.interval_seconds >= 60 && schedule.interval_seconds <= 31_536_000,
                "invalid imported schedule interval"
            );
            ensure!(
                (0..=253_402_300_799).contains(&schedule.next_run_at),
                "invalid imported schedule next_run_at"
            );
            ensure!(
                (1..=86400).contains(&schedule.timeout_seconds)
                    && (1..=10).contains(&schedule.max_attempts),
                "invalid imported schedule limits"
            );
            transaction.execute(
                "INSERT INTO rust_schedules VALUES (?,?,?,?,?,?,?,?)",
                params![
                    schedule.id,
                    schedule.kind,
                    serde_json::to_string(&schedule.request)?,
                    schedule.enabled,
                    schedule.interval_seconds,
                    schedule.next_run_at,
                    schedule.timeout_seconds,
                    schedule.max_attempts
                ],
            )?;
        }
        for (key, value) in &snapshot.configurations {
            transaction.execute(
                "INSERT INTO rust_configuration VALUES (?,?)",
                params![key, serde_json::to_string(value)?],
            )?;
        }
        for (table, records) in &snapshot.records {
            for record in records {
                import_legacy_record(&transaction, table, record, &snapshot.jobs, time)?;
            }
        }
        transaction.commit()?;
        Ok(())
    }

    /// Import a verified repeatable-read PostgreSQL acquisition into a fresh store.
    /// Data/checkpoints are imported by the analytical migration path, not this method.
    pub fn import_legacy_directory(&self, directory: &Path) -> Result<()> {
        let manifest: Value =
            serde_json::from_reader(std::fs::File::open(directory.join("manifest.json"))?)?;
        ensure!(
            manifest["format_version"] == 1
                && manifest["production_snapshot"] == true
                && manifest["source_transaction_read_only"] == true,
            "operations import requires a complete read-only production snapshot manifest"
        );
        let operations = manifest["operations"]
            .as_object()
            .context("migration manifest operations missing")?;
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let occupied: i64=transaction.query_row("SELECT (SELECT count(*) FROM rust_jobs)+(SELECT count(*) FROM rust_schedules)+(SELECT count(*) FROM rust_configuration)+(SELECT count(*) FROM rust_imported_records)",[],|row|row.get(0))?;
        ensure!(occupied == 0, "import requires an empty operational store");
        let time = now()?;
        for (table, metadata) in operations {
            if metadata["absent"] == true {
                continue;
            }
            ensure!(
                matches!(
                    table.as_str(),
                    "scheduled_jobs"
                        | "job_executions"
                        | "data_deletion_logs"
                        | "export_jobs"
                        | "ingestion_checkpoints"
                ),
                "unexpected legacy operations table"
            );
            let relative = metadata["file"]
                .as_str()
                .context("operation file missing")?;
            ensure!(
                relative == format!("operations/{table}.ndjson"),
                "unexpected operations file path"
            );
            let path = directory.join(relative);
            ensure!(
                !path.is_symlink() && path.is_file(),
                "operation file must be regular"
            );
            ensure!(
                metadata["bytes"].as_u64() == Some(path.metadata()?.len())
                    && metadata["sha256"] == crate::exports::file_sha256(&path)?,
                "operation file checksum/size mismatch"
            );
            let mut count = 0u64;
            let mut reader = BufReader::new(std::fs::File::open(path)?);
            while let Some(line) = operation_line(&mut reader)? {
                let record: Value = serde_json::from_str(&line)?;
                import_legacy_record(&transaction, table, &record, &[], time)?;
                count += 1;
                ensure!(
                    count <= 1_000_000,
                    "operational import exceeds one million records"
                );
            }
            ensure!(
                metadata["rows"].as_u64() == Some(count),
                "operation row count mismatch"
            );
        }
        transaction.commit()?;
        Ok(())
    }

    /// Install defaults only for a genuinely new schedule store. A migrated or
    /// deliberately emptied store must not gain duplicate/re-enabled jobs.
    pub fn initialize_scheduling(&self, enabled: bool) -> Result<()> {
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        if !enabled {
            transaction.execute("INSERT INTO rust_configuration VALUES('scheduler_enabled','false') ON CONFLICT(key) DO UPDATE SET value_json='false'", [])?;
        } else {
            transaction.execute(
                "INSERT OR IGNORE INTO rust_configuration VALUES('scheduler_enabled','true')",
                [],
            )?;
            let initialized: bool = transaction.query_row("SELECT EXISTS(SELECT 1 FROM rust_configuration WHERE key='default_schedules_initialized')", [], |r|r.get(0))?;
            let existing: i64 = transaction.query_row("SELECT (SELECT count(*) FROM rust_schedules)+(SELECT count(*) FROM rust_imported_records WHERE source_table='scheduled_jobs')", [], |r|r.get(0))?;
            if !initialized && existing == 0 {
                let time = now()?;
                for (id, request, interval, timeout) in [
                    (
                        "daily-source-refresh",
                        serde_json::json!({"endpoints":["crashes","people","vehicles"],"mode":"api","interval_seconds":86400,"timeout_seconds":7200}),
                        86400,
                        7200,
                    ),
                    (
                        "weekly-fatality-refresh",
                        serde_json::json!({"endpoints":["fatalities"],"mode":"incremental","interval_seconds":604800,"timeout_seconds":3600}),
                        604800,
                        3600,
                    ),
                ] {
                    transaction.execute(
                        "INSERT INTO rust_schedules VALUES(?,'ingestion',?,1,?,?,?,3)",
                        params![id, request.to_string(), interval, time + interval, timeout],
                    )?;
                }
            }
            transaction.execute("INSERT OR IGNORE INTO rust_configuration VALUES('default_schedules_initialized','true')", [])?;
        }
        transaction.commit()?;
        Ok(())
    }

    /// Transactionally enqueue due daily ingestion, preserving capacity and dedupe.
    pub fn enqueue_due(&self) -> Result<usize> {
        let time = now()?;
        let mut connection = self.connect()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        self.maintain(&transaction, time)?;
        let mut capacity = i64::from(self.max_active)
            - transaction.query_row(
                "SELECT count(*) FROM rust_jobs WHERE status IN ('queued','running')",
                [],
                |row| row.get::<_, i64>(0),
            )?;
        let due = {
            let mut statement = transaction.prepare("SELECT id,kind,request_json,next_run_at,interval_seconds,timeout_seconds,max_attempts FROM rust_schedules WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at,id")?;
            let rows = statement.query_map([time], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, i64>(3)?,
                    row.get::<_, i64>(4)?,
                    row.get::<_, i64>(5)?,
                    row.get::<_, u32>(6)?,
                ))
            })?;
            rows.collect::<rusqlite::Result<Vec<_>>>()?
        };
        let mut inserted = 0;
        for (id, kind, request, due_at, interval, timeout, attempts) in due {
            if capacity <= 0 {
                break;
            }
            let active: bool = transaction.query_row("SELECT EXISTS(SELECT 1 FROM rust_jobs WHERE kind=? AND status IN ('queued','running') AND instr(dedupe_key,?)=1)",params![kind,format!("schedule:{id}:")], |row|row.get(0))?;
            if active {
                continue;
            }
            let key = format!("schedule:{id}:{due_at}");
            let count = transaction.execute("INSERT OR IGNORE INTO rust_jobs(id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,max_attempts,dedupe_key) VALUES (?,?,'queued',?,?,?,?,?,?,?)",
                params![Uuid::new_v4().simple().to_string(),kind,request,time,time,time+timeout,time+86400,attempts,key])?;
            let next = due_at + ((time - due_at) / interval + 1) * interval;
            transaction.execute(
                "UPDATE rust_schedules SET next_run_at=? WHERE id=?",
                params![next, id],
            )?;
            capacity -= i64::try_from(count)?;
            inserted += count;
        }
        transaction.commit()?;
        Ok(inserted)
    }

    /// Online consistent SQLite backup; copying only the main WAL file is unsafe.
    pub fn backup(&self, destination: &Path) -> Result<()> {
        ensure!(!destination.exists(), "backup destination already exists");
        let source = self.connect()?;
        let mut target = Connection::open(destination)?;
        let backup = rusqlite::backup::Backup::new(&source, &mut target)?;
        backup.run_to_completion(64, Duration::from_millis(10), None)?;
        drop(backup);
        let check: String = target.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
        ensure!(check == "ok", "backup integrity check failed");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(destination, std::fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    }

    /// Restore into a fresh path while the owner is stopped. Never overwrite active state.
    pub fn restore(source: &Path, destination: &Path) -> Result<()> {
        ensure!(
            source.is_file() && !destination.exists(),
            "restore requires an existing backup and a fresh destination"
        );
        let input =
            Connection::open_with_flags(source, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let check: String = input.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
        ensure!(check == "ok", "source backup integrity check failed");
        let version: String = input.query_row(
            "SELECT value FROM rust_control_metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )?;
        if version != "1" {
            bail!("unsupported control schema version");
        }
        let mut output = Connection::open(destination)?;
        rusqlite::backup::Backup::new(&input, &mut output)?.run_to_completion(
            64,
            Duration::from_millis(10),
            None,
        )?;
        // Leases are process ownership, never durable authority after an offline restore.
        output.execute(
            "UPDATE rust_jobs SET lease_until=0 WHERE status='running'",
            [],
        )?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(destination, std::fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    }

    /// Expired private artifact pointers for bounded cleanup by their storage adapter.
    pub fn expired_artifacts(&self, limit: u32) -> Result<Vec<(String, String)>> {
        ensure!((1..=100).contains(&limit), "cleanup limit must be 1..100");
        let connection = self.connect()?;
        self.maintain(&connection, now()?)?;
        let mut statement = connection.prepare("SELECT id,artifact_path FROM rust_jobs WHERE status='expired' AND artifact_path IS NOT NULL LIMIT ?")?;
        let rows = statement.query_map([limit], |row| Ok((row.get(0)?, row.get(1)?)))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Clear a pointer only after the corresponding expired object has been removed.
    pub fn forget_expired_artifact(&self, id: &str) -> Result<()> {
        self.connect()?.execute(
            "UPDATE rust_jobs SET artifact_path=NULL WHERE id=? AND status='expired'",
            [id],
        )?;
        Ok(())
    }

    /// Protect live completed objects during age-based orphan cleanup.
    pub fn retains_artifact(&self, key: &str) -> Result<bool> {
        Ok(self.connect()?.query_row("SELECT EXISTS(SELECT 1 FROM rust_jobs WHERE artifact_path=? AND status='completed' AND expires_at>?)",params![key,now()?],|row|row.get(0))?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn store(directory: &tempfile::TempDir) -> Result<ControlStore> {
        ControlStore::open(directory.path().join("control.sqlite"), 4, 30)
    }

    #[test]
    fn operational_record_reader_rejects_unbounded_lines() -> Result<()> {
        let mut infinite = BufReader::new(std::io::repeat(b'x'));
        assert!(operation_line(&mut infinite).is_err());
        let mut valid = std::io::Cursor::new(b"{}\n{\"id\":1}\n");
        assert_eq!(operation_line(&mut valid)?.as_deref(), Some("{}\n"));
        assert_eq!(operation_line(&mut valid)?.as_deref(), Some("{\"id\":1}\n"));
        assert_eq!(operation_line(&mut valid)?, None);
        Ok(())
    }

    #[test]
    fn default_scheduling_is_atomic_once_and_preserves_operator_pause() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        store.initialize_scheduling(true)?;
        assert_eq!(store.schedules()?.len(), 2);
        store.set_configuration("scheduler_enabled", &serde_json::json!(false))?;
        store.connect()?.execute("DELETE FROM rust_schedules", [])?;
        store.initialize_scheduling(true)?;
        assert!(store.schedules()?.is_empty());
        assert_eq!(
            store.configuration("scheduler_enabled")?,
            Some(serde_json::json!(false))
        );
        Ok(())
    }

    #[test]
    fn imported_disabled_schedules_do_not_gain_native_defaults() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        store.connect()?.execute(
            "INSERT INTO rust_imported_records VALUES('scheduled_jobs','42',?)",
            [r#"{"id":42,"is_active":false}"#],
        )?;
        store.initialize_scheduling(true)?;
        assert!(store.schedules()?.is_empty());
        assert_eq!(
            store.configuration("scheduler_enabled")?,
            Some(serde_json::json!(true))
        );
        store.initialize_scheduling(false)?;
        assert_eq!(
            store.configuration("scheduler_enabled")?,
            Some(serde_json::json!(false))
        );
        Ok(())
    }

    #[test]
    fn cancelled_attempt_cannot_publish() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let job = store.enqueue(&json!({"resolved_area":{"geometry":"frozen"}}))?;
        let attempt = store.claim("export")?.context("claim")?;
        store.cancel(&job.id)?;
        assert!(
            store
                .finish(
                    &job.id,
                    attempt.attempt_token.as_deref().context("token")?,
                    Some("private"),
                    &json!({})
                )
                .is_err()
        );
        Ok(())
    }

    #[test]
    fn expired_lease_is_recovered_and_old_token_is_fenced() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let job = store.enqueue(&json!({}))?;
        let first = store.claim("export")?.context("claim")?;
        store
            .connect()?
            .execute("UPDATE rust_jobs SET lease_until=0 WHERE id=?", [&job.id])?;
        let second = store.claim("export")?.context("recovery")?;
        assert_eq!(second.attempt, 2);
        assert!(
            store
                .finish(
                    &job.id,
                    first.attempt_token.as_deref().context("token")?,
                    None,
                    &json!({})
                )
                .is_err()
        );
        store.finish(
            &job.id,
            second.attempt_token.as_deref().context("token")?,
            None,
            &json!({}),
        )?;
        Ok(())
    }

    #[test]
    fn exclusive_owner_restart_fences_live_attempt_without_waiting_for_lease() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let submitted = store.enqueue(&json!({"resolved_area":{"geometry":"frozen"}}))?;
        let first = store.claim("export")?.context("first claim")?;
        assert_eq!(store.recover_interrupted()?, 1);
        let second = store.claim("export")?.context("recovered claim")?;
        assert_eq!(second.attempt, 2);
        assert_eq!(second.deadline_at, submitted.deadline_at);
        assert!(
            store
                .finish(
                    &first.id,
                    first.attempt_token.as_deref().context("old token")?,
                    Some("private"),
                    &json!({})
                )
                .is_err()
        );
        store.finish(
            &second.id,
            second.attempt_token.as_deref().context("new token")?,
            Some("private"),
            &json!({}),
        )?;
        Ok(())
    }

    #[test]
    fn backup_restore_preserves_requests_but_revokes_live_leases() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let job = store.enqueue(&json!({"resolved_area":{"wkt":"POINT(1 2)"}}))?;
        let first = store.claim("export")?.context("claim")?;
        let backup = directory.path().join("backup.sqlite");
        store.backup(&backup)?;
        let restored_path = directory.path().join("restored.sqlite");
        ControlStore::restore(&backup, &restored_path)?;
        let restored = ControlStore::open(&restored_path, 4, 30)?;
        let attempt = restored.claim("export")?.context("claim restored")?;
        assert_eq!(attempt.request, job.request);
        assert!(
            restored
                .check_attempt(&job.id, first.attempt_token.as_deref().context("token")?)
                .is_err()
        );
        Ok(())
    }

    #[test]
    fn two_scheduler_ticks_enqueue_only_one_daily_job() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        store.put_schedule("core-daily", &json!({"days":30}), now()? - 172800, true)?;
        assert_eq!(store.enqueue_due()?, 1);
        assert_eq!(store.enqueue_due()?, 0);
        Ok(())
    }

    #[test]
    fn weekly_schedule_preserves_requested_cadence_timeout_and_attempt_budget() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let due = now()? - 1;
        store.put_schedule("fatalities-weekly",&json!({"endpoints":["fatalities"],"mode":"incremental","interval_seconds":604800,"timeout_seconds":3600,"max_attempts":4}),due,true)?;
        assert_eq!(store.enqueue_due()?, 1);
        let schedule = store.schedules()?.remove(0);
        assert_eq!(schedule.interval_seconds, 604800);
        assert_eq!(schedule.next_run_at, due + 604800);
        let execution = store.claim("ingestion")?.context("weekly execution")?;
        assert_eq!(execution.deadline_at - execution.created_at, 3600);
        assert_eq!(execution.max_attempts, 4);
        Ok(())
    }

    #[test]
    fn queue_capacity_is_durable_across_reopen() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = ControlStore::open(directory.path().join("queue.sqlite"), 1, 30)?;
        store.enqueue(&json!({}))?;
        let reopened = ControlStore::open(directory.path().join("queue.sqlite"), 1, 30)?;
        assert!(reopened.enqueue(&json!({})).is_err());
        Ok(())
    }

    #[test]
    fn migration_roundtrip_preserves_artifacts_and_history_and_schedule_enabled_state() -> Result<()>
    {
        let directory = tempfile::tempdir()?;
        let original = store(&directory)?;
        let job = original.enqueue(&json!({"resolved_area":{"geometry":"frozen"}}))?;
        let attempt = original.claim("export")?.context("claim")?;
        original.finish(
            &job.id,
            attempt.attempt_token.as_deref().context("token")?,
            Some("s3:exports/old/artifact.csv"),
            &json!({"sha256":"old"}),
        )?;
        original.put_schedule("daily", &json!({"days":30}), now()? + 86400, true)?;
        let mut snapshot = original.export_snapshot()?;
        snapshot.records.insert(
            "job_executions".into(),
            vec![json!({"id":42,"status":"completed","job_id":7})],
        );
        let raw = serde_json::to_vec(&snapshot)?;
        let snapshot: OperationalSnapshot = serde_json::from_slice(&raw)?;
        let imported = ControlStore::open(directory.path().join("imported.sqlite"), 4, 30)?;
        imported.import_snapshot(&snapshot)?;
        assert_eq!(
            imported
                .get(&job.id)?
                .context("imported job")?
                .artifact_path
                .as_deref(),
            Some("s3:exports/old/artifact.csv")
        );
        assert!(imported.schedules()?[0].enabled);
        assert_eq!(
            imported.export_snapshot()?.records["job_executions"][0]["id"],
            42
        );
        assert!(imported.import_snapshot(&snapshot).is_err());
        Ok(())
    }

    #[test]
    fn legacy_import_preserves_completed_private_exports_and_actual_checkpoint_keys() -> Result<()>
    {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let mut records = BTreeMap::new();
        records.insert("export_jobs".into(),vec![serde_json::json!({"id":"export-old","status":"completed","request":{"polygon":[[0,0],[1,0],[0,1]],"datasets":["crashes"]},"created_at":chrono::Utc::now().to_rfc3339(),"expires_at":(chrono::Utc::now()+chrono::Duration::days(1)).to_rfc3339(),"attempts":1,"object_key":"exports/export-old/attempt/crashes.csv","manifest":{"schema_version":1}})]);
        records.insert("ingestion_checkpoints".into(),vec![serde_json::json!({"endpoint":"fatalities","source_updated_before":"2026-10-20T00:00:00Z"})]);
        store.import_snapshot(&OperationalSnapshot {
            schema_version: 1,
            jobs: vec![],
            schedules: vec![],
            configurations: BTreeMap::new(),
            records,
        })?;
        let old = store
            .get("export-old")?
            .context("completed export missing")?;
        assert_eq!(
            old.artifact_path.as_deref(),
            Some("exports/export-old/attempt/crashes.csv")
        );
        assert_eq!(old.request["datasets"], serde_json::json!(["crashes"]));
        assert_eq!(
            store.export_snapshot()?.records["ingestion_checkpoints"][0]["endpoint"],
            "fatalities"
        );
        Ok(())
    }

    #[test]
    fn unknown_legacy_recurrence_aborts_entire_import() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = store(&directory)?;
        let records = BTreeMap::from([(
            "scheduled_jobs".into(),
            vec![
                serde_json::json!({"id":7,"name":"Unsupported","job_type":"incremental","recurrence_type":"unreviewed","config":{}}),
            ],
        )]);
        assert!(
            store
                .import_snapshot(&OperationalSnapshot {
                    schema_version: 1,
                    jobs: vec![],
                    schedules: vec![],
                    configurations: BTreeMap::new(),
                    records
                })
                .is_err()
        );
        assert!(store.export_snapshot()?.records.is_empty());
        Ok(())
    }

    #[test]
    fn verified_legacy_ndjson_import_rejects_corruption_and_rolls_back_atomically() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let snapshot = directory.path().join("snapshot");
        std::fs::create_dir_all(snapshot.join("operations"))?;
        let path = snapshot.join("operations/job_executions.ndjson");
        std::fs::write(
            &path,
            b"{\"id\":42,\"execution_id\":\"old-42\",\"job_id\":7,\"status\":\"completed\"}\n",
        )?;
        let manifest = serde_json::json!({"format_version":1,"production_snapshot":true,"source_transaction_read_only":true,"operations":{"job_executions":{"file":"operations/job_executions.ndjson","rows":1,"bytes":path.metadata()?.len(),"sha256":crate::exports::file_sha256(&path)?}}});
        std::fs::write(
            snapshot.join("manifest.json"),
            serde_json::to_vec(&manifest)?,
        )?;
        let restored = ControlStore::open(directory.path().join("restored.sqlite"), 4, 30)?;
        restored.import_legacy_directory(&snapshot)?;
        assert_eq!(
            restored.export_snapshot()?.records["job_executions"][0]["id"],
            42
        );
        std::fs::write(&path, b"mutated\n")?;
        let invalid = ControlStore::open(directory.path().join("invalid.sqlite"), 4, 30)?;
        assert!(invalid.import_legacy_directory(&snapshot).is_err());
        assert!(invalid.export_snapshot()?.records.is_empty());
        Ok(())
    }
}

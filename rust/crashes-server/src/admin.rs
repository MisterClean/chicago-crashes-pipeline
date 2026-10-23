//! Compatible scheduled-job administration backed by durable SQLite records.
//! HTTP authentication belongs to the outer router, before this dispatcher.

use crate::control::ControlStore;
use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Duration, NaiveDateTime, Utc};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::{collections::BTreeMap, str::FromStr};
use uuid::Uuid;

const JOB_TYPES: &[&str] = &[
    "full_refresh",
    "incremental",
    "last_30_days_core_data",
    "last_30_days_crashes",
    "last_30_days_people",
    "last_30_days_vehicles",
    "last_6_months_fatalities",
    "custom",
];
const RECURRENCES: &[&str] = &[
    "once",
    "daily",
    "weekly",
    "monthly",
    "custom_cron",
    "interval",
];

fn timestamp(value: &Value) -> Result<Option<DateTime<Utc>>> {
    let Some(value) = value.as_str() else {
        return Ok(None);
    };
    if let Ok(time) = DateTime::parse_from_rfc3339(value) {
        return Ok(Some(time.with_timezone(&Utc)));
    }
    Ok(Some(
        NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
            .or_else(|_| NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f"))?
            .and_utc(),
    ))
}

fn next_run(job: &Value, after: DateTime<Utc>) -> Result<Option<DateTime<Utc>>> {
    let recurrence = job["recurrence_type"]
        .as_str()
        .context("recurrence_type is required")?;
    Ok(match recurrence {
        "once" => None,
        "daily" => Some(after + Duration::days(1)),
        "weekly" => Some(after + Duration::weeks(1)),
        // Match the deployed system's fixed 30-day monthly recurrence.
        "monthly" => Some(after + Duration::days(30)),
        "interval" => Some(
            after
                + Duration::seconds(
                    job["interval_seconds"]
                        .as_i64()
                        .context("interval_seconds is required")?,
                ),
        ),
        "custom_cron" => {
            if job["legacy_cron_daily_fallback"] == true {
                Some(after + Duration::days(1))
            } else {
                let expression = job["cron_expression"]
                    .as_str()
                    .context("cron_expression is required")?;
                let expression = if expression.split_whitespace().count() == 5 {
                    format!("0 {expression}")
                } else {
                    expression.to_owned()
                };
                cron::Schedule::from_str(&expression)
                    .context("invalid UTC cron expression")?
                    .after(&after)
                    .next()
            }
        }
        _ => anyhow::bail!("unsupported recurrence type"),
    })
}

/// Validate a production schedule before import. Unsupported recurrence blocks import.
pub(crate) fn validate_job_record(job: &Value) -> Result<()> {
    let name = job["name"].as_str().context("job name is required")?;
    ensure!(
        !name.is_empty() && name.len() <= 255,
        "job name must be 1..255 characters"
    );
    ensure!(
        JOB_TYPES.contains(&job["job_type"].as_str().context("job_type is required")?),
        "unsupported job type"
    );
    ensure!(
        RECURRENCES.contains(
            &job["recurrence_type"]
                .as_str()
                .context("recurrence_type is required")?
        ),
        "unsupported recurrence type"
    );
    ensure!(
        (1..=480).contains(&job["timeout_minutes"].as_i64().unwrap_or(60)),
        "timeout_minutes must be 1..480"
    );
    ensure!(
        (0..=10).contains(&job["max_retries"].as_i64().unwrap_or(3)),
        "max_retries must be 0..10"
    );
    ensure!(
        (1..=60).contains(&job["retry_delay_minutes"].as_i64().unwrap_or(5)),
        "retry_delay_minutes must be 1..60"
    );
    ensure!(job["config"].is_object(), "job config must be an object");
    crate::ingestion::full_source_uses_api(&job["config"])?;
    if let Some(mode) = job["config"]["mode"].as_str() {
        ensure!(
            matches!(mode, "api" | "incremental" | "full"),
            "unsupported ingestion mode"
        );
    }
    if let Some(endpoints) = job["config"]["endpoints"].as_array() {
        ensure!(
            !endpoints.is_empty()
                && endpoints.len() <= 4
                && endpoints.iter().all(|v| matches!(
                    v.as_str(),
                    Some("crashes" | "people" | "vehicles" | "fatalities")
                )),
            "invalid ingestion endpoints"
        );
    }
    if job["recurrence_type"] == "interval" {
        ensure!(
            job["interval_seconds"]
                .as_i64()
                .is_some_and(|seconds| (60..=31_536_000).contains(&seconds)),
            "interval_seconds must be 60..31536000"
        );
    }
    next_run(job, Utc::now())?;
    timestamp(&job["next_run"])?;
    Ok(())
}

fn record(connection: &Connection, table: &str, id: &str) -> Result<Option<Value>> {
    let raw: Option<String> = connection
        .query_row(
            "SELECT record_json FROM rust_imported_records WHERE source_table=? AND source_id=?",
            params![table, id],
            |row| row.get(0),
        )
        .optional()?;
    raw.map(|raw| serde_json::from_str(&raw).map_err(Into::into))
        .transpose()
}

fn records(connection: &Connection, table: &str) -> Result<Vec<Value>> {
    let mut statement=connection.prepare("SELECT record_json FROM rust_imported_records WHERE source_table=? ORDER BY CAST(source_id AS INTEGER),source_id")?;
    let rows = statement.query_map([table], |row| row.get::<_, String>(0))?;
    rows.map(|row| Ok(serde_json::from_str(&row?)?)).collect()
}

fn persist(connection: &Connection, table: &str, value: &Value) -> Result<()> {
    let id = value["id"].as_i64().context("record ID missing")?;
    connection.execute("INSERT INTO rust_imported_records VALUES (?,?,?) ON CONFLICT(source_table,source_id) DO UPDATE SET record_json=excluded.record_json",params![table,id.to_string(),serde_json::to_string(value)?])?;
    Ok(())
}

fn next_id(connection: &Connection, table: &str) -> Result<i64> {
    let maximum: i64=connection.query_row("SELECT COALESCE(MAX(CAST(source_id AS INTEGER)),0) FROM rust_imported_records WHERE source_table=?",[table],|row|row.get(0))?;
    maximum.checked_add(1).context("operational ID overflow")
}

fn job(connection: &Connection, id: &str) -> Result<Value> {
    record(connection, "scheduled_jobs", id)?.context("Job not found")
}

fn create(store: &ControlStore, body: &Value) -> Result<Value> {
    let mut value = body.clone();
    let object = value
        .as_object_mut()
        .context("job request must be an object")?;
    for (key, default) in [
        ("enabled", json!(true)),
        ("config", json!({})),
        ("timeout_minutes", json!(60)),
        ("max_retries", json!(3)),
        ("retry_delay_minutes", json!(5)),
        ("description", Value::Null),
        ("cron_expression", Value::Null),
    ] {
        object.entry(key).or_insert(default);
    }
    object.insert("created_by".into(), json!("admin"));
    object.insert("created_at".into(), json!(Utc::now().to_rfc3339()));
    object.insert("updated_at".into(), json!(Utc::now().to_rfc3339()));
    object.insert("last_run".into(), Value::Null);
    validate_job_record(&value)?;
    value["next_run"] = if value["enabled"] == true {
        next_run(&value, Utc::now())?
            .map(|time| json!(time.to_rfc3339()))
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let mut connection = store.connect()?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    value["id"] = json!(next_id(&transaction, "scheduled_jobs")?);
    persist(&transaction, "scheduled_jobs", &value)?;
    transaction.commit()?;
    Ok(value)
}

fn update(store: &ControlStore, id: &str, body: &Value) -> Result<Value> {
    let mut connection = store.connect()?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let mut value = job(&transaction, id)?;
    let patch = body.as_object().context("job update must be an object")?;
    for (key, replacement) in patch {
        ensure!(
            [
                "name",
                "description",
                "enabled",
                "recurrence_type",
                "cron_expression",
                "config",
                "timeout_minutes",
                "max_retries",
                "retry_delay_minutes",
                "interval_seconds"
            ]
            .contains(&key.as_str()),
            "unsupported job update field"
        );
        value[key] = replacement.clone();
    }
    if (patch.contains_key("cron_expression") || patch.contains_key("recurrence_type"))
        && let Some(object) = value.as_object_mut()
    {
        object.remove("legacy_cron_daily_fallback");
    }
    validate_job_record(&value)?;
    if patch.keys().any(|key| {
        [
            "enabled",
            "recurrence_type",
            "cron_expression",
            "interval_seconds",
        ]
        .contains(&key.as_str())
    }) {
        value["next_run"] = if value["enabled"] == true {
            next_run(&value, Utc::now())?
                .map(|time| json!(time.to_rfc3339()))
                .unwrap_or(Value::Null)
        } else {
            Value::Null
        };
    }
    value["updated_at"] = json!(Utc::now().to_rfc3339());
    persist(&transaction, "scheduled_jobs", &value)?;
    transaction.commit()?;
    Ok(value)
}

/// Build the deployed job's ingestion parameters, preserving daily core API mode.
pub fn sync_request(job: &Value, override_config: Option<&Value>) -> Result<Value> {
    sync_request_at(job, override_config, Utc::now())
}

fn config_held(config: &Value) -> bool {
    ["held", "hold", "disabled"]
        .iter()
        .any(|key| config[key] == true)
}

fn sync_request_at(
    job: &Value,
    override_config: Option<&Value>,
    now: DateTime<Utc>,
) -> Result<Value> {
    ensure!(
        job["enabled"] != false,
        "scheduled job is disabled; enable it before execution"
    );
    ensure!(
        !config_held(&job["config"]),
        "ingestion request is held or disabled; update the persisted job configuration before execution"
    );
    let mut config = job["config"].clone();
    if let Some(override_config) = override_config {
        for (key, value) in override_config
            .as_object()
            .context("override_config must be an object")?
        {
            config[key] = value.clone();
        }
    }
    let kind = job["job_type"].as_str().context("job_type missing")?;
    let today = now.with_timezone(&chrono_tz::America::Chicago).date_naive();
    let defaults = || json!(["crashes", "people", "vehicles", "fatalities"]);
    let endpoints = || {
        config
            .get("endpoints")
            .filter(|v| !v.is_null())
            .cloned()
            .unwrap_or_else(defaults)
    };
    let mut request = if kind == "full_refresh" || config["mode"] == "full" {
        json!({"mode":"full","endpoints":endpoints(),"force":true})
    } else if kind == "incremental" || config["mode"] == "incremental" {
        json!({"mode":"incremental","endpoints":endpoints()})
    } else {
        let (endpoints, days) = match kind {
            "last_30_days_core_data" | "last_30_days_crashes" => (
                config
                    .get("endpoints")
                    .filter(|v| !v.is_null())
                    .cloned()
                    .unwrap_or_else(|| json!(["crashes", "people", "vehicles"])),
                30,
            ),
            "last_30_days_people" => (json!(["people"]), 30),
            "last_30_days_vehicles" => (json!(["vehicles"]), 30),
            "last_6_months_fatalities" => (json!(["fatalities"]), 180),
            "custom" => (
                config
                    .get("endpoints")
                    .filter(|v| !v.is_null())
                    .cloned()
                    .unwrap_or_else(|| json!(["crashes"])),
                config["date_range_days"].as_i64().unwrap_or(0),
            ),
            _ => anyhow::bail!("unsupported job type"),
        };
        ensure!((0..=36500).contains(&days), "invalid date_range_days");
        let mut request = json!({"mode":"api","endpoints":endpoints,"end_date":today.to_string(),"force":config["force"].as_bool().unwrap_or(true)});
        if days > 0 {
            request["start_date"] = json!((today - Duration::days(days)).to_string());
        }
        if kind == "custom" {
            for key in ["start_date", "end_date"] {
                if config[key].is_string() {
                    request[key] = config[key].clone();
                }
            }
        }
        request
    };
    // Freeze the reviewed policy alongside execution parameters. Ingestion
    // applies holds, repair restrictions and explicit full-refresh permission.
    request["config"] = config;
    request["scheduled_job_id"] = job["id"].clone();
    request["job_type"] = job["job_type"].clone();
    Ok(request)
}

fn enqueue(
    connection: &Connection,
    store: &ControlStore,
    job: &mut Value,
    body: &Value,
    dedupe: Option<&str>,
) -> Result<Value> {
    let time = Utc::now();
    store.maintain(connection, time.timestamp())?;
    let active: u32 = connection.query_row(
        "SELECT count(*) FROM rust_jobs WHERE status IN ('queued','running')",
        [],
        |row| row.get(0),
    )?;
    ensure!(active < store.max_active, "queue full; retry later");
    let existing: bool=connection.query_row("SELECT EXISTS(SELECT 1 FROM rust_jobs WHERE kind='ingestion' AND status IN ('queued','running') AND json_extract(request_json,'$.scheduled_job_id')=?)",[job["id"].as_i64().context("job id")?],|row|row.get(0))?;
    ensure!(!existing, "job already has a pending or running execution");
    let execution_id = Uuid::new_v4().simple().to_string();
    let mut request = sync_request(
        job,
        body.get("override_config").filter(|value| !value.is_null()),
    )?;
    request["execution_id"] = json!(execution_id);
    if body["force"] == true {
        request["force"] = json!(true);
    }
    let timeout = job["timeout_minutes"].as_i64().unwrap_or(60) * 60;
    let attempts = job["max_retries"].as_i64().unwrap_or(3) + 1;
    let retry_delay = job["retry_delay_minutes"].as_u64().unwrap_or(5) * 60;
    request["retry_delay_seconds"] = json!(retry_delay);
    connection.execute("INSERT INTO rust_jobs(id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,max_attempts,dedupe_key) VALUES (?,'ingestion','queued',?,?,?,?,?,?,?)",
        params![execution_id,serde_json::to_string(&request)?,time.timestamp(),time.timestamp(),time.timestamp()+timeout,time.timestamp()+86400,attempts,dedupe])?;
    let record = json!({"id":next_id(connection,"job_executions")?,"execution_id":execution_id,"job_id":job["id"],"job_name":job["name"],"status":"pending","started_at":Value::Null,"completed_at":Value::Null,"duration_seconds":Value::Null,"records_processed":0,"records_inserted":0,"records_updated":0,"records_skipped":0,"error_message":Value::Null,"retry_count":0,"created_at":time.to_rfc3339(),"execution_context":{"request":request},"logs":[]});
    persist(connection, "job_executions", &record)?;
    job["last_run"] = json!(time.to_rfc3339());
    job["next_run"] = next_run(job, time)?
        .map(|time| json!(time.to_rfc3339()))
        .unwrap_or(Value::Null);
    job["updated_at"] = json!(time.to_rfc3339());
    persist(connection, "scheduled_jobs", job)?;
    Ok(
        json!({"message":format!("Job {} execution queued",job["id"]),"execution_id":execution_id,"job_id":job["id"],"status":"pending","started_at":time.to_rfc3339()}),
    )
}

fn execute(store: &ControlStore, id: &str, body: &Value) -> Result<Value> {
    let mut connection = store.connect()?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let mut job = job(&transaction, id)?;
    let result = enqueue(&transaction, store, &mut job, body, None)?;
    transaction.commit()?;
    Ok(result)
}

/// Scheduler tick; due legacy schedules share the same bounded queue and claim fencing.
pub fn enqueue_due(store: &ControlStore) -> Result<usize> {
    let mut connection = store.connect()?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let time = Utc::now();
    let mut count = 0;
    for mut job in records(&transaction, "scheduled_jobs")? {
        validate_job_record(&job)?;
        if job["enabled"] != true
            || config_held(&job["config"])
            || !timestamp(&job["next_run"])?.is_some_and(|next| next <= time)
        {
            continue;
        }
        let active: u32 = transaction.query_row(
            "SELECT count(*) FROM rust_jobs WHERE status IN ('queued','running')",
            [],
            |row| row.get(0),
        )?;
        if active >= store.max_active {
            break;
        }
        let key = format!("legacy-schedule:{}:{}", job["id"], job["next_run"]);
        let existing: bool=transaction.query_row("SELECT EXISTS(SELECT 1 FROM rust_jobs WHERE kind='ingestion' AND status IN ('queued','running') AND json_extract(request_json,'$.scheduled_job_id')=?)",[job["id"].as_i64().context("job id")?],|row|row.get(0))?;
        if existing {
            continue;
        }
        enqueue(&transaction, store, &mut job, &json!({}), Some(&key))?;
        count += 1;
    }
    transaction.commit()?;
    Ok(count)
}

struct CurrentExecution {
    kind: String,
    status: String,
    started: i64,
    completed: i64,
    attempt: u32,
    error: Option<String>,
    manifest: Option<String>,
}

/// Derive legacy audit counters from the committed publication, including
/// unchanged and rejected source rows in the legacy skipped counter.
fn publication_totals(manifest: &Value, execution_id: &str) -> Result<Option<[u64; 4]>> {
    if manifest["operation_id"].as_str() != Some(execution_id)
        || !manifest["committed_at"].is_string()
    {
        return Ok(None);
    }
    let Some(datasets) = manifest["datasets"].as_object().filter(|v| !v.is_empty()) else {
        return Ok(None);
    };
    let mut totals = [0_u64; 4];
    for (name, dataset) in datasets {
        let count = |field: &str| {
            dataset[field].as_u64().with_context(|| {
                format!("publication {name}.{field} must be an unsigned row count")
            })
        };
        let source = count("source_rows")?;
        let accepted = count("accepted_rows")?;
        let inserted = count("inserted_rows")?;
        let updated = count("changed_rows")?;
        let unchanged = count("unchanged_rows")?;
        let writes = inserted
            .checked_add(updated)
            .context("publication row count overflow")?;
        ensure!(
            writes <= accepted && accepted <= source,
            "inconsistent publication row counts for {name}"
        );
        ensure!(
            unchanged == accepted - writes,
            "inconsistent unchanged publication rows for {name}"
        );
        for (total, value) in totals
            .iter_mut()
            .zip([source, inserted, updated, source - writes])
        {
            *total = total
                .checked_add(value)
                .context("publication total row count overflow")?;
        }
    }
    Ok(Some(totals))
}

fn project_manifest(
    execution: &mut Value,
    manifest: Value,
    execution_id: &str,
    kind: &str,
    status: &str,
) -> Result<()> {
    if status == "completed" && kind == "ingestion" {
        let fields = [
            "records_processed",
            "records_inserted",
            "records_updated",
            "records_skipped",
        ];
        if let Some(totals) = publication_totals(&manifest, execution_id)? {
            for (field, total) in fields.into_iter().zip(totals) {
                execution[field] = json!(total);
            }
        } else {
            // Older imported results may already expose the legacy flat totals.
            // An absent publication must not reset their retained audit counts.
            for field in fields {
                if !manifest[field].is_null() {
                    execution[field] = manifest[field].clone();
                }
            }
        }
    }
    execution["execution_context"]["result"] = manifest;
    Ok(())
}

fn executions(store: &ControlStore, id: Option<i64>, limit: usize) -> Result<Vec<Value>> {
    let connection = store.connect()?;
    let mut values = records(&connection, "job_executions")?;
    for value in &mut values {
        if let Some(execution_id) = value["execution_id"].as_str().map(str::to_owned) {
            let current=connection.query_row("SELECT kind,status,COALESCE(started_at,created_at),COALESCE(completed_at,updated_at),attempt,error,manifest_json FROM rust_jobs WHERE id=?",[&execution_id],|row|Ok(CurrentExecution{kind:row.get(0)?,status:row.get(1)?,started:row.get(2)?,completed:row.get(3)?,attempt:row.get(4)?,error:row.get(5)?,manifest:row.get(6)?})).optional()?;
            if let Some(CurrentExecution {
                kind,
                status,
                started: created,
                completed: updated,
                attempt,
                error,
                manifest,
            }) = current
            {
                value["status"] = json!(if status == "queued" {
                    "pending"
                } else {
                    &status
                });
                value["retry_count"] = json!(attempt.saturating_sub(1));
                value["error_message"] = error.map(Value::String).unwrap_or(Value::Null);
                if attempt > 0 {
                    value["started_at"] = json!(
                        DateTime::<Utc>::from_timestamp(created, 0)
                            .context("execution timestamp")?
                            .to_rfc3339()
                    );
                }
                if matches!(
                    status.as_str(),
                    "completed" | "failed" | "cancelled" | "expired"
                ) {
                    value["completed_at"] = json!(
                        DateTime::<Utc>::from_timestamp(updated, 0)
                            .context("execution timestamp")?
                            .to_rfc3339()
                    );
                    value["duration_seconds"] = json!((updated - created).max(0));
                }
                if let Some(manifest) = manifest {
                    let manifest: Value = serde_json::from_str(&manifest)?;
                    project_manifest(value, manifest, &execution_id, &kind, &status)?;
                }
            }
        }
    }
    values.retain(|value| id.is_none() || value["job_id"].as_i64() == id);
    values.sort_by(|a, b| b["created_at"].as_str().cmp(&a["created_at"].as_str()));
    values.truncate(limit);
    Ok(values)
}

/// Mirror a committed DuckDB deletion receipt without duplicating audit records
/// if the process died between analytical commit and SQLite acknowledgement.
pub fn record_deletion(store: &ControlStore, operation_id: &str, details: &Value) -> Result<Value> {
    ensure!(
        !operation_id.is_empty() && operation_id.len() <= 128,
        "invalid deletion operation ID"
    );
    let mut connection = store.connect()?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let old: Option<String>=transaction.query_row("SELECT record_json FROM rust_imported_records WHERE source_table='data_deletion_logs' AND json_extract(record_json,'$.operation_id')=?",[operation_id],|row|row.get(0)).optional()?;
    if let Some(old) = old {
        return Ok(serde_json::from_str(&old)?);
    }
    let mut record = details.clone();
    ensure!(
        record.is_object(),
        "deletion audit details must be an object"
    );
    record["id"] = json!(next_id(&transaction, "data_deletion_logs")?);
    record["operation_id"] = json!(operation_id);
    let object = record.as_object_mut().context("deletion record")?;
    for (key, default) in [
        ("created_at", json!(Utc::now().to_rfc3339())),
        ("updated_at", json!(Utc::now().to_rfc3339())),
        ("executed_by", json!("admin")),
        ("backup_location", Value::Null),
        ("can_restore", json!(false)),
    ] {
        object.entry(key).or_insert(default);
    }
    persist(&transaction, "data_deletion_logs", &record)?;
    transaction.commit()?;
    Ok(record)
}

/// Compatible /jobs JSON routes. The router maps errors to HTTP status and authenticates.
pub fn dispatch(
    store: &ControlStore,
    method: &str,
    path: &str,
    body: &Value,
    query: &BTreeMap<String, String>,
) -> Option<Result<Value>> {
    let path = path.trim_end_matches('/');
    if path != "/jobs" && !path.starts_with("/jobs/") {
        return None;
    }
    if matches!(
        path,
        "/jobs/data/delete" | "/jobs/backup" | "/jobs/schedules" | "/jobs/executions"
    ) || path.starts_with("/jobs/schedules/")
        || path.ends_with("/cancel")
    {
        return None;
    }
    if method == "GET"
        && let Some(id) = path.strip_prefix("/jobs/")
        && !id.contains('/')
        && !matches!(id, "types" | "summary")
        && id.parse::<i64>().is_err()
    {
        return None;
    }
    Some((|| {
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        let limit = query
            .get("limit")
            .map(|value| value.parse::<usize>())
            .transpose()?
            .unwrap_or(50);
        ensure!((1..=200).contains(&limit), "limit must be 1..200");
        match (method, parts.as_slice()) {
            ("GET", ["jobs"]) => {
                let mut jobs = records(&store.connect()?, "scheduled_jobs")?;
                if query
                    .get("enabled_only")
                    .is_some_and(|value| value == "true")
                {
                    jobs.retain(|job| job["enabled"] == true);
                }
                jobs.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
                Ok(json!(jobs))
            }
            ("POST", ["jobs"]) => create(store, body),
            ("GET", ["jobs", "types"]) => Ok(
                json!({"job_types":JOB_TYPES.iter().map(|kind|json!({"value":kind,"label":kind.replace('_'," ")})).collect::<Vec<_>>(),"recurrence_types":RECURRENCES.iter().map(|kind|json!({"value":kind,"label":kind.replace('_'," ")})).collect::<Vec<_>>(),"valid_endpoints":["crashes","people","vehicles","fatalities"],"valid_tables":["crashes","crash_people","crash_vehicles","vision_zero_fatalities"]}),
            ),
            ("GET", ["jobs", "summary"]) => {
                let jobs = records(&store.connect()?, "scheduled_jobs")?;
                let executions = executions(store, None, usize::MAX)?;
                let since = Utc::now() - Duration::days(1);
                let failed = executions
                    .iter()
                    .filter(|value| {
                        value["status"] == "failed"
                            && timestamp(&value["created_at"])
                                .ok()
                                .flatten()
                                .is_some_and(|time| time >= since)
                    })
                    .count();
                Ok(
                    json!({"total_jobs":jobs.len(),"active_jobs":jobs.iter().filter(|job|job["enabled"]==true).count(),"running_jobs":executions.iter().filter(|value|value["status"]=="running").count(),"failed_jobs_24h":failed,"last_execution":executions.first().map(|value|value["created_at"].clone())}),
                )
            }
            ("GET", ["jobs", "executions", "recent"]) => Ok(json!(executions(store, None, limit)?)),
            ("GET", ["jobs", "data", "deletions"]) => {
                Ok(json!(records(&store.connect()?, "data_deletion_logs")?))
            }
            ("GET", ["jobs", "executions", id]) => executions(store, None, usize::MAX)?
                .into_iter()
                .find(|value| {
                    value["execution_id"].as_str() == Some(id)
                        || id
                            .parse::<i64>()
                            .ok()
                            .is_some_and(|id| value["id"].as_i64() == Some(id))
                })
                .context("Execution not found"),
            ("GET", ["jobs", id]) => job(&store.connect()?, id),
            ("PUT", ["jobs", id]) => update(store, id, body),
            ("POST", ["jobs", id, "execute"]) => execute(store, id, body),
            ("GET", ["jobs", id, "executions"]) => {
                Ok(json!(executions(store, Some(id.parse()?), limit)?))
            }
            ("DELETE", ["jobs", id]) => {
                let mut connection = store.connect()?;
                let transaction =
                    connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
                job(&transaction, id)?;
                transaction.execute("UPDATE rust_jobs SET status='cancelled',cancel_requested=1,attempt_token=NULL,lease_until=NULL,updated_at=?,completed_at=? WHERE status IN ('queued','running') AND json_extract(request_json,'$.scheduled_job_id')=?",params![Utc::now().timestamp(),Utc::now().timestamp(),id.parse::<i64>()?])?;
                transaction.execute("DELETE FROM rust_imported_records WHERE source_table='scheduled_jobs' AND source_id=?",[id])?;
                transaction.commit()?;
                Ok(json!({"message":format!("Job {id} deleted successfully")}))
            }
            _ => anyhow::bail!("Job route not found"),
        }
    })())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn live_daily_receipt() -> Result<Value> {
        Ok(serde_json::from_str(include_str!(
            "../tests/fixtures/daily-core-publication-2026-10-21.json"
        ))?)
    }

    #[test]
    fn live_daily_publication_projects_counts_and_preserves_authoritative_failure() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = ControlStore::open(directory.path().join("control.sqlite"), 4, 30)?;
        let job = create(
            &store,
            &json!({"name":"Daily core","job_type":"last_30_days_core_data","recurrence_type":"daily","config":{}}),
        )?;
        execute(&store, &job["id"].to_string(), &json!({}))?;
        let attempt = store.claim("ingestion")?.context("queued execution")?;
        let mut receipt = live_daily_receipt()?;
        receipt["operation_id"] = json!(attempt.id);
        store.finish(
            &attempt.id,
            attempt.attempt_token.as_deref().context("token")?,
            None,
            &receipt,
        )?;
        let history = executions(&store, None, 50)?;
        assert_eq!(history[0]["records_processed"], 48639);
        assert_eq!(history[0]["records_inserted"], 332);
        assert_eq!(history[0]["records_updated"], 8855);
        assert_eq!(history[0]["records_skipped"], 39452);
        assert_eq!(history[0]["execution_context"]["result"], receipt);
        assert_eq!(history[0]["status"], "completed");

        // A retained receipt cannot make a failed/cancelled/retried attempt look
        // completed, erase its error, or claim committed success totals.
        for status in ["failed", "cancelled", "expired", "running", "queued"] {
            store.connect()?.execute(
                "UPDATE rust_jobs SET status=?,error='retained attempt error' WHERE id=?",
                params![status, attempt.id],
            )?;
            let history = executions(&store, None, 50)?;
            assert_eq!(
                history[0]["status"],
                if status == "queued" {
                    "pending"
                } else {
                    status
                }
            );
            assert_eq!(history[0]["error_message"], "retained attempt error");
            assert_eq!(history[0]["records_processed"], 0);
        }

        // Imported operational counters remain intact without a Rust receipt.
        let connection = store.connect()?;
        let mut imported = records(&connection, "job_executions")?.remove(0);
        for (field, count) in [
            ("records_processed", 42),
            ("records_inserted", 4),
            ("records_updated", 5),
            ("records_skipped", 33),
        ] {
            imported[field] = json!(count);
        }
        persist(&connection, "job_executions", &imported)?;
        connection.execute(
            "UPDATE rust_jobs SET status='completed',manifest_json=NULL,error=NULL WHERE id=?",
            [&attempt.id],
        )?;
        let history = executions(&store, None, 50)?;
        for field in [
            "records_processed",
            "records_inserted",
            "records_updated",
            "records_skipped",
        ] {
            assert_eq!(history[0][field], imported[field]);
        }
        Ok(())
    }

    #[test]
    fn publication_counters_include_rejected_rows_and_reject_corruption() -> Result<()> {
        let mut receipt = live_daily_receipt()?;
        let id = receipt["operation_id"]
            .as_str()
            .context("operation id")?
            .to_owned();
        receipt["datasets"]["crashes"]["source_rows"] = json!(9301);
        receipt["datasets"]["crashes"]["identity_rejections"]["rejected_rows"] = json!(3);
        assert_eq!(
            publication_totals(&receipt, &id)?,
            Some([48642, 332, 8855, 39455])
        );
        assert_eq!(publication_totals(&receipt, "another-execution")?, None);
        receipt["datasets"]["crashes"]["inserted_rows"] = json!(u64::MAX);
        assert!(publication_totals(&receipt, &id).is_err());
        Ok(())
    }

    #[test]
    fn admin_job_execution_is_durable_and_retains_legacy_core_api_semantics() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = ControlStore::open(directory.path().join("control.sqlite"), 4, 30)?;
        let job = create(
            &store,
            &json!({"name":"Daily core","job_type":"last_30_days_core_data","recurrence_type":"daily","config":{}}),
        )?;
        let execution = execute(&store, &job["id"].to_string(), &json!({}))?;
        let attempt = store.claim("ingestion")?.context("queued execution")?;
        assert_eq!(attempt.request["mode"], "api");
        assert_eq!(
            attempt.request["endpoints"],
            json!(["crashes", "people", "vehicles"])
        );
        assert_eq!(attempt.id, execution["execution_id"]);
        store.finish(
            &attempt.id,
            attempt.attempt_token.as_deref().context("token")?,
            None,
            &json!({"records_processed":17}),
        )?;
        let history = executions(&store, None, 50)?;
        assert_eq!(history[0]["records_processed"], 17);
        assert_eq!(history[0]["status"], "completed");
        Ok(())
    }
    #[test]
    fn schedule_tick_is_idempotent_and_cron_rejects_invalid_expression() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = ControlStore::open(directory.path().join("control.sqlite"), 4, 30)?;
        let mut job = create(
            &store,
            &json!({"name":"Daily","job_type":"incremental","recurrence_type":"daily","config":{}}),
        )?;
        job["next_run"] = json!((Utc::now() - Duration::days(5)).to_rfc3339());
        persist(&store.connect()?, "scheduled_jobs", &job)?;
        assert_eq!(enqueue_due(&store)?, 1);
        assert_eq!(enqueue_due(&store)?, 0);
        assert!(create(&store,&json!({"name":"Invalid cron","job_type":"incremental","recurrence_type":"custom_cron","cron_expression":"bad","config":{}})).is_err());
        Ok(())
    }

    #[test]
    fn execution_retains_reviewed_policy_and_uses_chicago_calendar_dates() -> Result<()> {
        let now = DateTime::parse_from_rfc3339("2026-10-23T02:00:00Z")?.with_timezone(&Utc);
        let mut job = json!({"id":1,"job_type":"last_30_days_core_data","config":{"repair_null_people_dates":true}});
        let request = sync_request_at(&job, None, now)?;
        assert_eq!(request["start_date"], "2026-09-22");
        assert_eq!(request["end_date"], "2026-10-22");
        assert_eq!(request["config"]["repair_null_people_dates"], true);

        job["config"] = json!({"mode":"full","endpoints":["fatalities"],"allow_full_refresh":true});
        let request = sync_request_at(&job, None, now)?;
        assert_eq!(request["mode"], "full");
        assert_eq!(request["endpoints"], json!(["fatalities"]));
        assert_eq!(request["config"]["allow_full_refresh"], true);
        Ok(())
    }

    #[test]
    fn held_jobs_cannot_be_forced_or_block_other_due_schedules() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let store = ControlStore::open(directory.path().join("control.sqlite"), 8, 30)?;
        for flag in ["held", "hold", "disabled"] {
            let mut config = json!({});
            config[flag] = json!(true);
            let mut job = create(
                &store,
                &json!({"name":flag,"job_type":"last_30_days_core_data","recurrence_type":"daily","config":config}),
            )?;
            job["next_run"] = json!((Utc::now() - Duration::days(1)).to_rfc3339());
            persist(&store.connect()?, "scheduled_jobs", &job)?;
            let mut overrides = json!({});
            overrides[flag] = json!(false);
            assert!(
                execute(
                    &store,
                    &job["id"].to_string(),
                    &json!({"force":true,"override_config":overrides})
                )
                .is_err()
            );
        }
        let disabled = create(
            &store,
            &json!({"name":"Disabled schedule","enabled":false,"job_type":"last_30_days_core_data","recurrence_type":"daily","config":{}}),
        )?;
        assert!(execute(&store, &disabled["id"].to_string(), &json!({"force":true})).is_err());
        let mut runnable = create(
            &store,
            &json!({"name":"Runnable","job_type":"last_30_days_core_data","recurrence_type":"daily","config":{}}),
        )?;
        runnable["next_run"] = json!((Utc::now() - Duration::days(1)).to_rfc3339());
        persist(&store.connect()?, "scheduled_jobs", &runnable)?;
        assert_eq!(enqueue_due(&store)?, 1);
        let queued = store.list(Some("ingestion"), 8)?;
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].request["scheduled_job_id"], runnable["id"]);
        Ok(())
    }
}

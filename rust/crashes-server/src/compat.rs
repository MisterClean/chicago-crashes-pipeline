//! Explicit compatibility for operational routes from the deployed Python API.
//! Live portal diagnostics and server-directory loading are retired explicitly;
//! they never masquerade as validation of a different local dataset.
use crate::{control::ControlStore, db::Database};
use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Duration, NaiveDate, Utc};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
    time::Instant,
};

static STARTED: OnceLock<Instant> = OnceLock::new();
pub fn start_clock() {
    STARTED.get_or_init(Instant::now);
}

#[derive(Debug)]
pub struct Error {
    pub status: u16,
    pub detail: String,
}
impl Error {
    fn bad(message: impl std::fmt::Display) -> Self {
        Self {
            status: 400,
            detail: message.to_string(),
        }
    }
    fn conflict(message: &str) -> Self {
        Self {
            status: 409,
            detail: message.into(),
        }
    }
    fn gone(message: &str) -> Self {
        Self {
            status: 410,
            detail: message.into(),
        }
    }
    fn missing(message: &str) -> Self {
        Self {
            status: 404,
            detail: message.into(),
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.detail.fmt(f)
    }
}
impl std::error::Error for Error {}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct SyncRequest {
    endpoint: Option<String>,
    endpoints: Option<Vec<String>>,
    datasets: Option<Vec<String>>,
    start_date: Option<String>,
    end_date: Option<String>,
    mode: Option<String>,
    source_mode: Option<String>,
    force: Option<bool>,
    config: Option<serde_json::Map<String, Value>>,
    held: Option<bool>,
    hold: Option<bool>,
    disabled: Option<bool>,
    repair_null_people_dates: Option<bool>,
    allow_full_refresh: Option<bool>,
    date_range_days: Option<i64>,
}

fn iso_date(value: &str) -> Result<NaiveDate> {
    let date = NaiveDate::parse_from_str(value, "%Y-%m-%d").map_err(Error::bad)?;
    ensure!(
        date.format("%Y-%m-%d").to_string() == value,
        Error::bad("Dates must use YYYY-MM-DD")
    );
    Ok(date)
}

/// Resolve only explicit selectors or the reviewed daily core default. Preserve
/// configuration and force in the durable request, including their audit origin.
pub fn sync_request(body: &Value, today: NaiveDate) -> Result<Value> {
    let request: SyncRequest = serde_json::from_value(if body.is_null() {
        json!({})
    } else {
        body.clone()
    })
    .map_err(Error::bad)?;
    let mut config = request.config.unwrap_or_default();
    if let Some(source_mode) = request.source_mode {
        config.insert("source_mode".into(), json!(source_mode));
    }
    crate::ingestion::full_source_uses_api(&Value::Object(config.clone())).map_err(Error::bad)?;
    for (key, value) in [
        ("held", request.held),
        ("hold", request.hold),
        ("disabled", request.disabled),
        ("repair_null_people_dates", request.repair_null_people_dates),
        ("allow_full_refresh", request.allow_full_refresh),
    ] {
        if matches!(
            key,
            "held" | "hold" | "disabled" | "repair_null_people_dates"
        ) && (value == Some(true) || config.get(key) == Some(&Value::Bool(true)))
        {
            return Err(Error::conflict("Ingestion is held/disabled or requests an unreviewed historical people-date repair").into());
        }
        if let Some(value) = value {
            config.insert(key.into(), json!(value));
        }
    }
    for key in [
        "held",
        "hold",
        "disabled",
        "repair_null_people_dates",
        "allow_full_refresh",
        "force",
        "recover_historical",
    ] {
        if let Some(value) = config.get(key) {
            ensure!(
                value.is_boolean(),
                Error::bad(format!("config.{key} must be boolean"))
            );
        }
    }
    let configured_endpoints = config
        .get("endpoints")
        .filter(|v| !v.is_null())
        .or_else(|| config.get("datasets").filter(|v| !v.is_null()))
        .cloned();
    let selectors = usize::from(request.endpoint.is_some())
        + usize::from(request.endpoints.is_some())
        + usize::from(request.datasets.is_some())
        + usize::from(configured_endpoints.is_some());
    ensure!(
        selectors <= 1,
        Error::bad(
            "Choose one endpoint selector; endpoint, endpoints, datasets and config selectors cannot be combined"
        )
    );
    ensure!(
        !(config.get("endpoints").is_some_and(|v| !v.is_null())
            && config.get("datasets").is_some_and(|v| !v.is_null())),
        Error::bad("Conflicting config endpoint selectors")
    );
    let endpoints = if let Some(endpoint) = &request.endpoint {
        vec![endpoint.clone()]
    } else if let Some(values) = request.endpoints.or(request.datasets) {
        values
    } else if let Some(values) = configured_endpoints {
        serde_json::from_value::<Vec<String>>(values).map_err(Error::bad)?
    } else {
        vec!["crashes".into(), "people".into(), "vehicles".into()]
    };
    ensure!(
        !endpoints.is_empty() && endpoints.len() <= 4,
        Error::bad("Choose 1..4 endpoints")
    );
    let mut unique = BTreeSet::new();
    for endpoint in &endpoints {
        ensure!(
            crate::sources::DATASETS.contains(&endpoint.as_str()),
            Error::bad("Unknown endpoint")
        );
        ensure!(unique.insert(endpoint), Error::bad("Duplicate endpoint"));
    }
    let mut dates = [None, None];
    for (index, (key, top)) in [
        ("start_date", request.start_date),
        ("end_date", request.end_date),
    ]
    .into_iter()
    .enumerate()
    {
        if let Some(value) = top {
            config.insert(key.into(), json!(value));
        }
        if let Some(value) = config.get(key).filter(|v| !v.is_null()) {
            dates[index] = Some(iso_date(value.as_str().ok_or_else(|| {
                Error::bad(format!("config.{key} must be a date string"))
            })?)?);
        }
    }
    if let Some(mode) = request.mode {
        config.insert("mode".into(), json!(mode));
    }
    let requested_mode = config
        .get("mode")
        .map(|v| {
            v.as_str()
                .ok_or_else(|| Error::bad("mode must be a string"))
        })
        .transpose()?
        .unwrap_or("api")
        .to_owned();
    ensure!(
        ["api", "full", "incremental"].contains(&requested_mode.as_str()),
        Error::bad("mode must be api, full or incremental")
    );
    ensure!(
        !(requested_mode == "full" && dates.iter().any(Option::is_some)),
        Error::bad("Full refresh cannot have date filters")
    );
    let mode = if dates.iter().any(Option::is_some) {
        "api"
    } else {
        requested_mode.as_str()
    };
    if mode == "full" {
        ensure!(
            config.get("allow_full_refresh") == Some(&Value::Bool(true)),
            Error::conflict("Full refresh requires an explicit reviewed allow_full_refresh guard")
        );
    }
    if mode == "incremental" {
        ensure!(
            endpoints.iter().all(|v| v == "fatalities"),
            Error::conflict(
                "Core source-modification incremental mode remains held; use an explicit API event-date window"
            )
        );
    }
    let days = request
        .date_range_days
        .or(config
            .get("date_range_days")
            .map(|v| {
                v.as_i64()
                    .ok_or_else(|| Error::bad("date_range_days must be an integer"))
            })
            .transpose()?)
        .unwrap_or(30);
    ensure!(
        (1..=36500).contains(&days),
        Error::bad("date_range_days must be 1..36500")
    );
    if mode == "api" {
        // Preserve whether the operator supplied dates before normalizing the
        // rolling window into concrete dates for a durable manual request.
        config
            .entry("recover_historical")
            .or_insert(json!(dates.iter().all(Option::is_none)));
        let end = dates[1].unwrap_or(today);
        let start = dates[0].unwrap_or(end - Duration::days(days));
        ensure!(
            start <= end,
            Error::bad("Start date must not be after end date")
        );
        config.insert("start_date".into(), json!(start.to_string()));
        config.insert("end_date".into(), json!(end.to_string()));
    }
    let force = request
        .force
        .or(config.get("force").and_then(Value::as_bool))
        .unwrap_or(false);
    config.insert("mode".into(), json!(mode));
    config.insert("endpoints".into(), json!(endpoints));
    config.remove("datasets");
    config.insert("force".into(), json!(force));
    config.insert("date_range_days".into(), json!(days));
    let mut normalized = Value::Object(config.clone());
    normalized["config"] = Value::Object(config);
    normalized["requested_mode"] = json!(requested_mode);
    normalized["endpoint"] = json!(request.endpoint);
    normalized["job_type"] = json!(match mode {
        "full" => "full_refresh",
        "incremental" => "incremental",
        _ => "custom",
    });
    Ok(normalized)
}

fn enqueue_manual(store: &ControlStore, request: &Value) -> Result<Value> {
    let now = Utc::now();
    let mut connection = store.connect()?;
    let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    store.maintain(&tx, now.timestamp())?;
    let active: u32 = tx.query_row(
        "SELECT count(*) FROM rust_jobs WHERE status IN ('queued','running')",
        [],
        |r| r.get(0),
    )?;
    ensure!(active < store.max_active, "queue full; retry later");
    let next_id = |table: &str| -> Result<i64> {
        Ok(tx.query_row("SELECT coalesce(max(cast(source_id AS INTEGER)),0)+1 FROM rust_imported_records WHERE source_table=?",[table],|r|r.get(0))?)
    };
    let job_id = next_id("scheduled_jobs")?;
    let execution_id = uuid::Uuid::new_v4().simple().to_string();
    let mut request = request.clone();
    request["scheduled_job_id"] = json!(job_id);
    request["execution_id"] = json!(execution_id);
    request["retry_delay_seconds"] = json!(300);
    let timeout = if request["mode"] == "full" {
        28800
    } else {
        3600
    };
    tx.execute("INSERT INTO rust_jobs(id,kind,status,request_json,created_at,updated_at,deadline_at,expires_at,max_attempts) VALUES(?,'ingestion','queued',?,?,?,?,?,?)",params![execution_id,request.to_string(),now.timestamp(),now.timestamp(),now.timestamp()+timeout,now.timestamp()+86400,4])?;
    let job = json!({"id":job_id,"name":"Manual sync","description":null,"job_type":request["job_type"],"enabled":false,"recurrence_type":"once","config":request["config"],"created_by":"manual-sync","timeout_minutes":timeout/60,"max_retries":3,"retry_delay_minutes":5,"created_at":now.to_rfc3339(),"updated_at":now.to_rfc3339(),"last_run":now.to_rfc3339(),"next_run":null});
    let execution = json!({"id":next_id("job_executions")?,"execution_id":execution_id,"job_id":job_id,"job_name":"Manual sync","status":"pending","started_at":null,"completed_at":null,"duration_seconds":null,"records_processed":0,"records_inserted":0,"records_updated":0,"records_skipped":0,"error_message":null,"retry_count":0,"created_at":now.to_rfc3339(),"execution_context":{"request":request,"trigger":{"type":"manual","force":request["force"]}},"logs":[]});
    for (table, id, value) in [
        ("scheduled_jobs", job_id, job),
        (
            "job_executions",
            execution["id"].as_i64().context("execution identity")?,
            execution,
        ),
    ] {
        tx.execute(
            "INSERT INTO rust_imported_records VALUES(?,?,?)",
            params![table, id.to_string(), value.to_string()],
        )?;
    }
    tx.commit()?;
    Ok(
        json!({"message":"Sync queued for worker","sync_id":execution_id,"queue_id":execution_id,"status":"pending","started_at":now.to_rfc3339(),"_accepted":true}),
    )
}

fn counts(db: &Database) -> Result<Value> {
    let row=db.query("SELECT (SELECT count(*) FROM crashes) AS crashes,(SELECT count(*) FROM crash_people) AS people,(SELECT count(*) FROM crash_vehicles) AS vehicles,(SELECT count(*) FROM vision_zero_fatalities) AS fatalities",&[])?.into_iter().next().context("counts row missing")?;
    let total = ["crashes", "people", "vehicles", "fatalities"]
        .iter()
        .map(|k| row[*k].as_u64().unwrap_or(0))
        .sum::<u64>();
    let mut counts = row;
    counts["crash_people"] = counts["people"].clone();
    counts["crash_vehicles"] = counts["vehicles"].clone();
    counts["vision_zero_fatalities"] = counts["fatalities"].clone();
    Ok(json!({"status":"success","counts":counts,"total_records":total,"timestamp":Utc::now()}))
}

const HISTORY:&str="WITH history AS (
    SELECT json_extract(r.record_json,'$.execution_id') AS id,
        coalesce(j.status,json_extract(r.record_json,'$.status')) AS status,
        CASE WHEN j.id IS NOT NULL THEN j.error ELSE json_extract(r.record_json,'$.error_message') END AS error,
        coalesce(j.created_at,unixepoch(json_extract(r.record_json,'$.created_at'))) AS created,
        CASE WHEN j.id IS NOT NULL THEN coalesce(j.completed_at,j.updated_at) ELSE unixepoch(json_extract(r.record_json,'$.completed_at')) END AS completed
    FROM rust_imported_records r LEFT JOIN rust_jobs j ON j.id=json_extract(r.record_json,'$.execution_id')
    WHERE r.source_table='job_executions'
    UNION ALL
    SELECT j.id,j.status,j.error,j.created_at,coalesce(j.completed_at,j.updated_at) FROM rust_jobs j
    WHERE j.kind='ingestion' AND NOT EXISTS(SELECT 1 FROM rust_imported_records r WHERE r.source_table='job_executions' AND json_extract(r.record_json,'$.execution_id')=j.id)
) ";
fn status(db: &Database, store: &ControlStore) -> Result<Value> {
    let counts = counts(db)?;
    let connection = store.connect()?;
    store.maintain(&connection, Utc::now().timestamp())?;
    let(total,successful,failed,last):(i64,i64,i64,Option<i64>)=connection.query_row(&format!("{HISTORY} SELECT count(*),count(*) FILTER(WHERE status='completed'),count(*) FILTER(WHERE status='failed'),max(completed) FILTER(WHERE status='completed') FROM history"),[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?;
    let active:Option<(String,String)>=connection.query_row(&format!("{HISTORY} SELECT id,status FROM history WHERE status IN ('queued','pending','running') ORDER BY created,id LIMIT 1"),[],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
    let latest: Option<(String, Option<String>)> = connection
        .query_row(
            &format!(
                "{HISTORY} SELECT id,error FROM history ORDER BY created DESC,id DESC LIMIT 1"
            ),
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let elapsed = STARTED.get_or_init(Instant::now).elapsed();
    Ok(
        json!({"status":active.as_ref().map(|r|if r.1=="running"{"running"}else{"pending"}).unwrap_or("idle"),"last_sync":last.and_then(|v|DateTime::<Utc>::from_timestamp(v,0)),"current_operation":active.as_ref().map(|r|&r.0),"stats":{"total_syncs":total,"successful_syncs":successful,"failed_syncs":failed,"last_error":latest.as_ref().and_then(|r|r.1.as_ref()).map(|_|"Last sync failed; inspect authenticated execution details"),"last_execution_id":latest.as_ref().map(|r|&r.0)},"uptime":format!("{}:{:02}:{:02}.{:06}",elapsed.as_secs()/3600,elapsed.as_secs()/60%60,elapsed.as_secs()%60,elapsed.subsec_micros()),"is_syncing":active.as_ref().is_some_and(|r|r.1=="running"),"crashes_count":counts["counts"]["crashes"],"people_count":counts["counts"]["people"],"vehicles_count":counts["counts"]["vehicles"]}),
    )
}

const SPATIAL_TABLES: [&str; 9] = [
    "crashes",
    "vision_zero_fatalities",
    "spatial_layer_features",
    "wards",
    "community_areas",
    "census_tracts",
    "police_beats",
    "house_districts",
    "senate_districts",
];
fn spatial_tables(db: &Database) -> Result<Value> {
    let mut tables = Vec::new();
    for table in SPATIAL_TABLES {
        let geometry=db.query("SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name=$1 AND upper(data_type) LIKE 'GEOMETRY%'",&[json!(table)])?;
        if geometry.is_empty() {
            continue;
        }
        let count = db.query(&format!("SELECT count(*) AS n FROM {table}"), &[])?[0]["n"].clone();
        tables.push(json!({"table_name":table,"geometry_column":"geometry","dimensions":2,"srid":4326,"geometry_type":"GEOMETRY","record_count":count}));
    }
    Ok(json!({"tables":tables,"total_tables":tables.len()}))
}
fn spatial_table(db: &Database, table: &str, query: &BTreeMap<String, String>) -> Result<Value> {
    ensure!(
        SPATIAL_TABLES.contains(&table),
        Error::missing("Spatial table not found")
    );
    let limit = query
        .get("limit")
        .map(|v| v.parse::<usize>())
        .transpose()
        .map_err(Error::bad)?
        .unwrap_or(10);
    ensure!(
        (1..=100).contains(&limit),
        Error::bad("limit must be 1..100")
    );
    let columns=db.query("SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name=$1 ORDER BY ordinal_position",&[json!(table)])?;
    ensure!(
        !columns.is_empty(),
        Error::missing("Spatial table not found")
    );
    let names = columns
        .iter()
        .map(|r| r["column_name"].as_str().context("column name missing"))
        .collect::<Result<Vec<_>>>()?;
    let projection=names.iter().map(|name|if *name=="geometry"{"CASE WHEN geometry IS NULL THEN NULL ELSE '<geometry: ' || left(ST_AsText(geometry),50) || '...>' END AS geometry".into()}else{crate::sources::identifier(name)}).collect::<Vec<_>>().join(",");
    let rows = db.query(
        &format!("SELECT {projection} FROM {table} LIMIT {limit}"),
        &[],
    )?;
    Ok(json!({"table_name":table,"columns":names,"record_count":rows.len(),"sample_data":rows}))
}

/// A durable gate for future scheduling. Running and manually queued work keep
/// their leases; stopping the scheduler does not cancel an in-flight publication.
fn scheduler_status(store: &ControlStore) -> Result<Value> {
    let enabled = store
        .configuration("scheduler_enabled")?
        .as_ref()
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let connection = store.connect()?;
    let active: i64 = connection.query_row(
        "SELECT count(*) FROM rust_jobs WHERE kind='ingestion' AND status='running'",
        [],
        |r| r.get(0),
    )?;
    let legacy: i64 = connection.query_row("SELECT count(*) FROM rust_imported_records WHERE source_table='scheduled_jobs' AND json_extract(record_json,'$.enabled')=1", [], |r| r.get(0))?;
    let native = store.schedules()?.iter().filter(|s| s.enabled).count();
    Ok(
        json!({"status":if enabled {"running"} else {"stopped"},"is_running":enabled,"scheduler_enabled":enabled,"enabled_jobs":legacy+native as i64,"running_jobs":active,"idle_poll_interval_milliseconds":250,"message":"Controls future schedule dispatch; existing queued and running work continues"}),
    )
}
fn scheduler_toggle(store: &ControlStore, enabled: bool) -> Result<Value> {
    store.set_configuration("scheduler_enabled", &json!(enabled))?;
    let mut status = scheduler_status(store)?;
    status["message"] = json!(if enabled {
        "Scheduler enabled; due jobs will be checked on the next worker tick"
    } else {
        "Scheduler stopped; existing queued and running work continues"
    });
    Ok(status)
}

pub fn dispatch(
    db: &Database,
    store: &ControlStore,
    method: &str,
    path: &str,
    body: &Value,
    query: &BTreeMap<String, String>,
) -> Option<Result<Value>> {
    let parts = path.trim_matches('/').split('/').collect::<Vec<_>>();
    match(method,parts.as_slice()){
        ("GET",["sync","counts"])=>Some(counts(db)),
        ("GET",["jobs","scheduler","status"])=>Some(scheduler_status(store)),
        ("POST",["jobs","scheduler","start"])=>Some(scheduler_toggle(store,true)),
        ("POST",["jobs","scheduler","stop"])=>Some(scheduler_toggle(store,false)),
        ("GET",["sync","status"])=>Some(status(db,store)),
        ("GET",["sync","endpoints"])=>Some((||{let mut endpoints=Vec::new();for name in crate::sources::DATASETS{let source=crate::sources::specification(name)?;endpoints.push(json!({"name":name,"url":format!("https://data.cityofchicago.org/resource/{}.json",source.dataset_id),"description":match name{"crashes"=>"Main crash records with location and injury data","people"=>"Person-level injury and demographic data","vehicles"=>"Vehicle/unit information involved in crashes",_=>"Curated fatality dataset from Vision Zero initiative"}}));}Ok(json!({"total_endpoints":endpoints.len(),"endpoints":endpoints}))})()),
        ("POST",["sync","trigger"])=>Some((||{let request=sync_request(body,Utc::now().with_timezone(&chrono_tz::America::Chicago).date_naive())?;if request["mode"]=="incremental"{let exists=db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='main' AND table_name='ingestion_checkpoints'",&[])?[0]["n"].as_u64().unwrap_or(0)>0;ensure!(exists,Error::conflict("Fatalities incremental checkpoint is missing; reviewed bootstrap required"));let count=db.query("SELECT count(*) AS n FROM ingestion_checkpoints WHERE dataset='fatalities'",&[])?[0]["n"].as_u64().unwrap_or(0);ensure!(count>0,Error::conflict("Fatalities incremental checkpoint is missing; reviewed bootstrap required"));}enqueue_manual(store,&request)})()),
        ("POST",["sync","test"])=>Some(Err(Error::gone("Live portal test-sync diagnostics are retired; use strictly verified source downloads and inspect worker execution receipts. This endpoint does not validate a local substitute dataset.").into())),
        ("GET",["validate"])=>Some(Ok(json!({"status":"retired","message":"Live portal validation is retired in this runtime; no local-data result is substituted","available_endpoints":crate::sources::DATASETS,"replacement":"Use strictly verified source downloads and ingestion publication receipts","limits":{"max_records_per_validation":1000,"default_records":100}}))),
        ("GET",["validate",_])=>Some(Err(Error::gone("Live portal validation is retired; use strictly verified source downloads and ingestion publication receipts. No local-data validation is substituted.").into())),
        ("POST",["spatial","load"])=>Some(Err(Error::gone("Server-filesystem shapefile loading is retired; upload a GeoJSON or complete shapefile ZIP to authenticated POST /spatial/layers.").into())),
        ("GET",["spatial"])=>Some(Ok(json!({"message":"Spatial data management endpoints","crs":"EPSG:4326","usage":{"upload":"POST /spatial/layers (multipart GeoJSON or shapefile ZIP)","preview":"POST /spatial/layers/preview-fields","list_layers":"GET /spatial/layers","list_tables":"GET /spatial/tables","query_table":"GET /spatial/tables/{table_name}?limit=10","places":"GET /places/types"},"instructions":["Uploaded layers retain their configured labels and identities","Native tables are not replaced by downloaded contemporary boundaries","Server-directory loading is retired; use authenticated uploads"]}))),
        ("GET",["spatial","tables"])=>Some(spatial_tables(db)),
        ("GET",["spatial","tables",table])=>Some(spatial_table(db,table,query)),
        _=>None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn today() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 10, 21).unwrap()
    }
    #[test]
    fn default_is_explicit_core_api_window_without_fatalities() {
        let value = sync_request(&json!({}), today()).unwrap();
        assert_eq!(value["endpoints"], json!(["crashes", "people", "vehicles"]));
        assert_eq!(value["mode"], "api");
        assert_eq!(value["start_date"], "2026-09-21");
        assert_eq!(value["end_date"], "2026-10-21");
        assert_eq!(value["recover_historical"], true);
    }
    #[test]
    fn singular_fatalities_and_dates_are_not_broadened() {
        let value=sync_request(&json!({"endpoint":"fatalities","mode":"incremental","start_date":"2024-01-01","end_date":"2024-01-31","force":true}),today()).unwrap();
        assert_eq!(value["endpoints"], json!(["fatalities"]));
        assert_eq!(value["mode"], "api");
        assert_eq!(value["requested_mode"], "incremental");
        assert_eq!(value["recover_historical"], false);
        assert_eq!(value["start_date"], "2024-01-01");
        assert_eq!(value["force"], true);
    }
    #[test]
    fn reviewed_full_replay_preserves_explicit_source_transport() {
        for source_mode in ["api", "bulk"] {
            let request = sync_request(&json!({"endpoint":"vehicles","mode":"full","allow_full_refresh":true,"source_mode":source_mode}), today()).unwrap();
            assert_eq!(request["source_mode"], source_mode);
            assert_eq!(request["config"]["source_mode"], source_mode);
            assert_eq!(request["endpoints"], json!(["vehicles"]));
            assert!(request.get("start_date").is_none() && request.get("end_date").is_none());
        }
    }
    #[test]
    fn invalid_or_held_requests_fail_before_queueing() {
        for body in [
            json!({"endpoint":"unknown"}),
            json!({"endpoint":"people","datasets":["vehicles"]}),
            json!({"mode":"full"}),
            json!({"mode":"full","allow_full_refresh":true,"source_mode":"typo"}),
            json!({"mode":"full","allow_full_refresh":true,"config":{"source_mode":42}}),
            json!({"mode":"incremental","endpoint":"people"}),
            json!({"endpoint":"crashes","config":{"held":true}}),
            json!({"config":{"repair_null_people_dates":true}}),
            json!({"start_date":"2024-02-30"}),
            json!({"start_date":"2025-01-01","end_date":"2024-01-01"}),
            json!({"unexpected":true}),
        ] {
            assert!(sync_request(&body, today()).is_err(), "{body}");
        }
    }
}

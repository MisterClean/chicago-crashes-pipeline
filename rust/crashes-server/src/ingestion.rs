//! Native CSV normalization and atomic, replayable current-data publication.
use crate::{
    db::{Database, Session},
    sources::{self, PublicationMode, VerifiedSource},
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};

const INTEGER_FIELDS: &[&str] = &[
    "posted_speed_limit",
    "lane_cnt",
    "injuries_total",
    "injuries_fatal",
    "injuries_incapacitating",
    "injuries_non_incapacitating",
    "injuries_reported_not_evident",
    "injuries_no_indication",
    "injuries_unknown",
    "age",
    "vehicle_year",
    "num_passengers",
    "occupant_cnt",
];
const STRING_NUMBERS: &[&str] = &[
    "street_no",
    "beat_of_occurrence",
    "crash_unit_id",
    "unit_no",
    "vehicle_id",
    "cmv_id",
];

fn configured_limit(name: &str, default: u64) -> Result<u64> {
    match std::env::var(name) {
        Ok(value) => value
            .parse::<u64>()
            .with_context(|| format!("{name} must be a nonnegative integer")),
        Err(std::env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("invalid {name} configuration")),
    }
}

pub fn table_name(dataset: &str) -> Result<&'static str> {
    match dataset {
        "crashes" => Ok("crashes"),
        "people" => Ok("crash_people"),
        "vehicles" => Ok("crash_vehicles"),
        "fatalities" => Ok("vision_zero_fatalities"),
        _ => anyhow::bail!("unknown dataset {dataset}"),
    }
}
fn primary_keys(dataset: &str) -> &[&str] {
    match dataset {
        "crashes" => &["crash_record_id"],
        "people" => &["crash_record_id", "person_id"],
        "vehicles" => &["crash_unit_id"],
        _ => &["person_id"],
    }
}
fn model_only(dataset: &str) -> BTreeMap<String, String> {
    let mut fields = BTreeMap::new();
    match dataset {
        "crashes" => {
            for key in [
                "street_direction_2",
                "street_name_2",
                "crash_record_id_original",
                "not_right_of_way_i",
            ] {
                fields.insert(key.to_owned(), "VARCHAR".to_owned());
            }
            fields.insert("crash_date_original".into(), "TIMESTAMP".into());
            fields.insert("geometry".into(), "GEOMETRY".into());
        }
        "people" => {
            fields.insert("ems_unit".into(), "VARCHAR".into());
            for i in 0..13 {
                fields.insert(format!("area_{i:02}_i"), "VARCHAR".into());
            }
        }
        "vehicles" => {
            fields.insert("hazmat_placard_i".into(), "VARCHAR".into());
        }
        "fatalities" => {
            fields.insert("rd_no".into(), "VARCHAR".into());
            fields.insert("geometry".into(), "GEOMETRY".into());
        }
        _ => {}
    }
    fields
}
pub fn schema_columns(dataset: &str) -> Result<BTreeMap<String, String>> {
    let mut fields = BTreeMap::new();
    for c in sources::specification(dataset)?.columns {
        let kind = if c.data_type == "calendar_date" {
            "TIMESTAMP"
        } else if INTEGER_FIELDS.contains(&c.api_field.as_str()) {
            "INTEGER"
        } else if c.data_type == "number" && !STRING_NUMBERS.contains(&c.api_field.as_str()) {
            "DOUBLE"
        } else {
            "VARCHAR"
        };
        fields.insert(c.api_field, kind.to_owned());
    }
    fields.extend(model_only(dataset));
    fields.insert("created_at".into(), "TIMESTAMP".into());
    fields.insert("updated_at".into(), "TIMESTAMP".into());
    Ok(fields)
}
fn convert(expression: &str, field: &str, kind: &str) -> String {
    if kind == "VARCHAR" {
        return format!(
            "CASE WHEN regexp_full_match(trim({expression}), '(?i:NULL|N/A|UNKNOWN|UNK|)') THEN NULL ELSE regexp_replace(trim({expression}), '\\s+', ' ', 'g') END"
        );
    }
    let cleaned = format!("trim({expression})");
    if kind == "TIMESTAMP" {
        return format!(
            "coalesce(try_strptime({cleaned}, '%m/%d/%Y %I:%M:%S %p'),try_strptime({cleaned}, '%m/%d/%Y %H:%M:%S'),try_strptime({cleaned}, '%m/%d/%Y'),try_cast({cleaned} AS TIMESTAMP))"
        );
    }
    let mut number = format!("try_cast({cleaned} AS DOUBLE)");
    if kind == "INTEGER" {
        number = format!("try_cast(trunc({number}) AS INTEGER)");
    }
    let condition = match field {
        "latitude" => format!("{number} BETWEEN 41.6 AND 42.1"),
        "longitude" => format!("{number} BETWEEN -87.95 AND -87.5"),
        "age" => format!("{number} BETWEEN 0 AND 120"),
        "vehicle_year" => format!("{number} BETWEEN 1900 AND 2025"),
        _ => format!("isfinite({number})"),
    };
    format!("CASE WHEN {condition} THEN {number} ELSE NULL END")
}
fn count(session: &Session, sql: &str) -> Result<u64> {
    session
        .query(sql, &[])?
        .first()
        .and_then(|v| v["n"].as_u64())
        .context("expected count result")
}
fn stage(session: &Session, source: &VerifiedSource, check: &sources::Check<'_>) -> Result<String> {
    let dataset = &source.dataset;
    let stage = format!("_ingest_stage_{dataset}");
    let raw = format!("_ingest_raw_{dataset}");
    let canonical = if dataset == "fatalities" {
        ensure!(
            source.rows()? <= 100000,
            "fatality source exceeds deployed 100000-row bound"
        );
        let scratch = session.query("SELECT current_setting('temp_directory') path", &[])?;
        let scratch = Path::new(
            scratch[0]["path"]
                .as_str()
                .context("owner scratch directory missing")?,
        );
        Some(sources::canonical_fatality_csv(
            &source.path,
            scratch,
            check,
        )?)
    } else {
        None
    };
    let input = canonical
        .as_ref()
        .map_or(source.path.as_path(), |file| file.path());
    let path = input.to_str().context("source path must be UTF-8")?;
    session.execute(&format!("CREATE TEMP VIEW {} AS SELECT * FROM read_csv({},header=true,all_varchar=true,normalize_names=false,ignore_errors=false,strict_mode=true,buffer_size=4194304,maximum_line_size=262144)",sources::identifier(&raw),sources::literal(path)),&[])?;
    let fields = schema_columns(dataset)?;
    let mut expressions = Vec::new();
    for c in sources::specification(dataset)?.columns {
        expressions.push(format!(
            "{} AS {}",
            convert(
                &sources::identifier(&c.csv_header),
                &c.api_field,
                &fields[&c.api_field]
            ),
            sources::identifier(&c.api_field)
        ));
    }
    for (field, kind) in model_only(dataset) {
        if field != "geometry" {
            expressions.push(format!("NULL::{kind} AS {}", sources::identifier(&field)));
        }
    }
    expressions.push("current_timestamp::TIMESTAMP AS created_at".into());
    expressions.push("current_timestamp::TIMESTAMP AS updated_at".into());
    let projection: Vec<_> = fields.keys().map(|field| {
        if field == "geometry" {"CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN ST_Point(longitude,latitude) ELSE NULL END AS geometry".to_owned()} else {sources::identifier(field)}
    }).collect();
    // No global sort: the 71-column vehicle sort exceeded the measured 256MB budget.
    let existing = count(
        session,
        &format!(
            "SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name={}",
            sources::literal(table_name(dataset)?)
        ),
    )? > 0;
    // A fresh core table can be atomically renamed into place. Avoid a second
    // historical CTAS copy; live merges retain disposable temporary staging.
    let scope = if existing || dataset == "fatalities" {
        "TEMP "
    } else {
        ""
    };
    session.execute(&format!("CREATE {scope}TABLE {} AS WITH normalized AS (SELECT {} FROM {}) SELECT {} FROM normalized",sources::identifier(&stage),expressions.join(","),sources::identifier(&raw),projection.join(",")),&[])?;
    ensure!(
        count(session, &format!("SELECT count(*) n FROM {stage}"))? == source.rows()?,
        "native CSV row count differs from source receipt"
    );
    session.execute(&format!("DROP VIEW {}", sources::identifier(&raw)), &[])?;
    Ok(stage)
}
fn validate_core(session: &Session, stage: &str, dataset: &str) -> Result<()> {
    let mut required = primary_keys(dataset).to_vec();
    if dataset == "vehicles" {
        required.push("crash_record_id");
    }
    if dataset == "crashes" {
        required.push("crash_date");
    }
    let missing = required
        .iter()
        .map(|f| format!("{} IS NULL", sources::identifier(f)))
        .collect::<Vec<_>>()
        .join(" OR ");
    ensure!(
        count(
            session,
            &format!("SELECT count(*) n FROM {stage} WHERE {missing}")
        )? == 0,
        "{dataset} has missing required identity/date"
    );
    let keys = primary_keys(dataset)
        .iter()
        .map(|f| sources::identifier(f))
        .collect::<Vec<_>>()
        .join(",");
    ensure!(
        count(
            session,
            &format!(
                "SELECT count(*) n FROM (SELECT {keys} FROM {stage} GROUP BY {keys} HAVING count(*)>1)"
            )
        )? == 0,
        "{dataset} has duplicate identities"
    );
    Ok(())
}
fn fatalities(session: &Session, stage: &str, operation: &str) -> Result<(String, Value)> {
    let comparable = sources::specification("fatalities")?
        .columns
        .iter()
        .map(|c| sources::identifier(&c.api_field))
        .collect::<Vec<_>>()
        .join(",");
    session.execute(&format!("CREATE TEMP TABLE _ingest_fatality_groups AS SELECT person_id,count(*) source_rows,count(DISTINCT row({comparable})) variants FROM {stage} WHERE person_id IS NOT NULL GROUP BY person_id"),&[])?;
    let missing = count(
        session,
        &format!("SELECT count(*) n FROM {stage} WHERE person_id IS NULL"),
    )?;
    let conflict = count(
        session,
        "SELECT coalesce(sum(source_rows),0)::BIGINT n FROM _ingest_fatality_groups WHERE variants>1",
    )?;
    let identical = count(
        session,
        "SELECT coalesce(sum(source_rows-1),0)::BIGINT n FROM _ingest_fatality_groups WHERE variants=1",
    )?;
    let rows = count(session, &format!("SELECT count(*) n FROM {stage}"))?;
    ensure!(
        rows <= 100000,
        "fatality source exceeds deployed 100000-row identity validation bound"
    );
    let rejected = missing + conflict + identical;
    ensure!(
        rejected <= 100 && rejected * 20 <= rows,
        "fatality identity exclusions exceed deployed 100-row/5% guard"
    );
    session.execute("INSERT INTO ingestion_rejections SELECT ?, 'fatalities', CASE WHEN variants>1 THEN 'conflicting_person_id' ELSE 'identical_duplicate_person_id' END,person_id,CASE WHEN variants>1 THEN source_rows ELSE source_rows-1 END FROM _ingest_fatality_groups WHERE source_rows>1",&[json!(operation)])?;
    if missing > 0 {
        session.execute(
            "INSERT INTO ingestion_rejections VALUES (?, 'fatalities','missing_person_id',NULL,?)",
            &[json!(operation), json!(missing)],
        )?;
    }
    let accepted = "_ingest_accepted_fatalities".to_owned();
    session.execute(&format!("CREATE TEMP TABLE {accepted} AS SELECT DISTINCT s.* FROM {stage} s JOIN _ingest_fatality_groups g USING(person_id) WHERE g.variants=1"),&[])?;
    ensure!(
        count(
            session,
            &format!("SELECT count(*) n FROM {accepted} WHERE crash_date IS NULL")
        )? == 0,
        "fatalities has missing/invalid dates"
    );
    session.execute("DROP TABLE _ingest_fatality_groups", &[])?;
    session.execute(&format!("DROP TABLE {stage}"), &[])?;
    Ok((
        accepted,
        json!({"missing_person_id":missing,"conflicting_person_id":conflict,"identical_duplicate_person_id":identical,"rejected_rows":rejected}),
    ))
}
fn publish(session: &Session, stage: &str, dataset: &str, mode: PublicationMode) -> Result<Value> {
    let table = table_name(dataset)?;
    let exists = count(
        session,
        &format!(
            "SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name={}",
            sources::literal(table)
        ),
    )? > 0;
    let accepted = count(session, &format!("SELECT count(*) n FROM {stage}"))?;
    if !exists {
        if dataset == "fatalities" {
            session.execute(
                &format!("CREATE TABLE {table} AS SELECT * FROM {stage}"),
                &[],
            )?;
            session.execute(&format!("DROP TABLE {stage}"), &[])?;
        } else {
            session.execute(&format!("ALTER TABLE {stage} RENAME TO {table}"), &[])?;
        }
        return Ok(
            json!({"inserted_rows":accepted,"changed_rows":0,"unchanged_rows":0,"accepted_rows":accepted}),
        );
    }
    ensure!(
        mode == PublicationMode::Production,
        "profiling publication refuses to change existing {table}"
    );
    if dataset == "people" {
        session.execute(&format!("UPDATE {stage} s SET crash_date=NULL FROM {table} t WHERE t.crash_record_id=s.crash_record_id AND t.person_id=s.person_id AND t.crash_date IS NULL"),&[])?;
    }
    let schema = schema_columns(dataset)?;
    let columns: Vec<_> = schema.keys().map(|c| sources::identifier(c)).collect();
    let compared: Vec<_> = schema
        .keys()
        .filter(|c| !["created_at", "updated_at", "geometry"].contains(&c.as_str()))
        .map(|c| sources::identifier(c))
        .collect();
    let equality = primary_keys(dataset)
        .iter()
        .map(|c| format!("t.{0}=s.{0}", sources::identifier(c)))
        .collect::<Vec<_>>()
        .join(" AND ");
    // Existing ambiguous destination identities must remain unchanged for fatalities.
    if dataset == "fatalities" {
        session.execute(&format!("DELETE FROM {stage} WHERE person_id IN (SELECT person_id FROM {table} GROUP BY person_id HAVING count(*)>1)"),&[])?;
    }
    let changed_predicate = format!(
        "row({}) IS DISTINCT FROM row({})",
        compared
            .iter()
            .map(|c| format!("t.{c}"))
            .collect::<Vec<_>>()
            .join(","),
        compared
            .iter()
            .map(|c| format!("s.{c}"))
            .collect::<Vec<_>>()
            .join(",")
    );
    let inserted = count(
        session,
        &format!(
            "SELECT count(*) n FROM {stage} s WHERE NOT EXISTS(SELECT 1 FROM {table} t WHERE {equality})"
        ),
    )?;
    let changed = count(
        session,
        &format!(
            "SELECT count(*) n FROM {stage} s JOIN {table} t ON {equality} WHERE {changed_predicate}"
        ),
    )?;
    let assignments = schema
        .keys()
        .filter(|c| c.as_str() != "created_at")
        .map(|c| format!("{0}=s.{0}", sources::identifier(c)))
        .collect::<Vec<_>>()
        .join(",");
    session.execute(&format!("UPDATE {table} t SET {assignments} FROM {stage} s WHERE {equality} AND {changed_predicate}"),&[])?;
    session.execute(&format!("INSERT INTO {table} ({}) SELECT {} FROM {stage} s WHERE NOT EXISTS(SELECT 1 FROM {table} t WHERE {equality})",columns.join(","),columns.iter().map(|c|format!("s.{c}")).collect::<Vec<_>>().join(",")),&[])?;
    session.execute(&format!("DROP TABLE {stage}"), &[])?;
    Ok(
        json!({"inserted_rows":inserted,"changed_rows":changed,"unchanged_rows":accepted.saturating_sub(inserted+changed),"accepted_rows":accepted}),
    )
}

/// Publishes all supplied sources and revision checkpoints in one owner transaction.
/// Production replays full stable snapshots daily so historical corrections are
/// included; source absence never silently deletes existing accepted records.
pub fn publish_sources(
    db: &Database,
    directory: &Path,
    datasets: &[String],
    mode: PublicationMode,
    operation_id: &str,
) -> Result<Value> {
    publish_sources_guarded(db, directory, datasets, mode, operation_id, &|| Ok(()))
}
fn acquisition_watermark(manifest: &Value) -> Result<Value> {
    let Some(value) = manifest
        .get("source_updated_before")
        .filter(|value| !value.is_null())
    else {
        // Older complete source receipts do not establish when acquisition began.
        // They can bootstrap facts, but cannot invent a modification watermark.
        return Ok(Value::Null);
    };
    let timestamp = |value: &Value| -> Result<chrono::DateTime<chrono::FixedOffset>> {
        Ok(chrono::DateTime::parse_from_rfc3339(
            value
                .as_str()
                .context("source acquisition timestamps must be RFC3339 strings")?,
        )?)
    };
    let before = timestamp(value)?;
    let started = timestamp(&manifest["acquisition_started_at"])?;
    let downloaded = timestamp(&manifest["downloaded_at"])?;
    ensure!(
        before <= started && started <= downloaded && downloaded <= chrono::Utc::now(),
        "source modification watermark must not advance past acquisition"
    );
    Ok(json!(before.to_rfc3339()))
}

pub fn publish_sources_guarded(
    db: &Database,
    directory: &Path,
    datasets: &[String],
    mode: PublicationMode,
    operation_id: &str,
    check: &sources::Check<'_>,
) -> Result<Value> {
    ensure!(
        !operation_id.is_empty() && operation_id.len() <= 200,
        "invalid operation identifier"
    );
    ensure!(!datasets.is_empty(), "choose at least one dataset");
    let unique: std::collections::BTreeSet<_> = datasets.iter().collect();
    ensure!(
        unique.len() == datasets.len(),
        "duplicate dataset selection"
    );
    let sources = datasets
        .iter()
        .map(|dataset| sources::load_source_guarded(directory, dataset, mode, check))
        .collect::<Result<Vec<_>>>()?;
    let fingerprint = json!({"mode":format!("{mode:?}"),"sources":sources.iter().map(|s|json!({"dataset":s.dataset,"sha256":s.manifest["sha256"],"revision":s.manifest["source_revision_after"],"source_filter":s.manifest["source_filter"]})).collect::<Vec<_>>()});
    db.transaction(|session| { session.guarded(check, || {
        session.execute("CREATE TABLE IF NOT EXISTS ingestion_publications(operation_id VARCHAR PRIMARY KEY,committed_at TIMESTAMPTZ,fingerprint JSON,receipt JSON)",&[])?;
        session.execute("CREATE TABLE IF NOT EXISTS ingestion_rejections(operation_id VARCHAR,dataset VARCHAR,reason VARCHAR,identity VARCHAR,source_rows BIGINT)",&[])?;
        session.execute("CREATE TABLE IF NOT EXISTS ingestion_checkpoints(dataset VARCHAR PRIMARY KEY,source_revision BIGINT,operation_id VARCHAR,updated_at TIMESTAMPTZ,source_updated_before TIMESTAMPTZ)",&[])?;
        session.execute("ALTER TABLE ingestion_checkpoints ADD COLUMN IF NOT EXISTS source_updated_before TIMESTAMPTZ",&[])?;
        let prior = session.query("SELECT fingerprint,receipt FROM ingestion_publications WHERE operation_id=?",&[json!(operation_id)])?;
        if let Some(prior) = prior.first() {
            let previous = if let Some(s)=prior["fingerprint"].as_str() {serde_json::from_str::<Value>(s)?} else {prior["fingerprint"].clone()};
            ensure!(previous==fingerprint,"idempotency key reused for different source content");
            return if let Some(s)=prior["receipt"].as_str(){Ok(serde_json::from_str(s)?)}else{Ok(prior["receipt"].clone())};
        }
        let mut stats = serde_json::Map::new();
        let existing_targets=count(session,"SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name IN ('crashes','crash_people','crash_vehicles','vision_zero_fatalities')")?>0;
        let max_changed=configured_limit("INGESTION_MAX_CHANGED_ROWS",25000)?;
        let mut changed_rows=0_u64;
        for source in &sources {
            let stage = stage(session,source,check)?;
            let (stage,rejections) = if source.dataset=="fatalities" {fatalities(session,&stage,operation_id)?} else {validate_core(session,&stage,&source.dataset)?;(stage,json!({"rejected_rows":0}))};
            let mut result = publish(session,&stage,&source.dataset,mode)?;
            changed_rows+=result["inserted_rows"].as_u64().unwrap_or(0)+result["changed_rows"].as_u64().unwrap_or(0);
            ensure!(!existing_targets||changed_rows<=max_changed,"publication changes exceed INGESTION_MAX_CHANGED_ROWS={max_changed}; transaction rolled back");
            result["identity_rejections"]=rejections;
            result["source_rows"]=json!(source.rows()?);
            result["source_manifest"]=source.manifest.clone();
            stats.insert(source.dataset.clone(),result);
            if mode == PublicationMode::Production && source.manifest["source_scope"]!="event_date_window" {
                let watermark = acquisition_watermark(&source.manifest)?;
                session.execute("INSERT INTO ingestion_checkpoints(dataset,source_revision,operation_id,updated_at,source_updated_before) VALUES(?,?,?,current_timestamp,?::TIMESTAMPTZ) ON CONFLICT(dataset) DO UPDATE SET source_revision=excluded.source_revision,operation_id=excluded.operation_id,updated_at=excluded.updated_at,source_updated_before=excluded.source_updated_before",&[json!(source.dataset),source.manifest["source_revision_after"].clone(),json!(operation_id),watermark])?;
            }
        }
        let receipt = json!({"operation_id":operation_id,"committed_at":chrono::Utc::now().to_rfc3339(),"production_complete":mode==PublicationMode::Production,"profiling_only":mode==PublicationMode::Profiling,"cross_dataset_consistent_snapshot":false,"datasets":stats});
        check()?;
        session.execute("INSERT INTO ingestion_publications VALUES(?,current_timestamp,?,?)",&[json!(operation_id),json!(fingerprint.to_string()),json!(receipt.to_string())])?;
        crate::mutations::record(session,"facts.publish",&receipt)?;
        Ok(receipt)
    }) })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn keeps_parentless_child_date_nullable_and_identifier_as_text() {
        let fields = schema_columns("people").unwrap();
        assert_eq!(
            schema_columns("vehicles").unwrap()["crash_unit_id"],
            "VARCHAR"
        );
        assert_eq!(fields["crash_date"], "TIMESTAMP");
    }
    #[test]
    fn sanitation_preserves_audited_year_age_and_coordinate_policy() {
        assert!(convert("v", "vehicle_year", "INTEGER").contains("1900 AND 2025"));
        assert!(convert("v", "age", "INTEGER").contains("0 AND 120"));
        assert!(convert("v", "longitude", "DOUBLE").contains("-87.95 AND -87.5"));
    }
    #[test]
    fn missing_acquisition_proof_cannot_fabricate_a_watermark() {
        assert!(
            acquisition_watermark(&json!({"downloaded_at":"2000-01-01T00:00:00Z"}))
                .unwrap()
                .is_null()
        );
    }
}

#[cfg(test)]
mod native_tests {
    use super::*;
    use std::fs::File;

    fn database(directory: &Path) -> Option<Database> {
        let library = crate::test_support::library();
        let db = Database::open(
            &directory.join("test.duckdb"),
            &library,
            "256MB",
            1,
            &directory.join("spill"),
        )
        .unwrap();
        crate::test_support::load_spatial(&db);
        Some(db)
    }
    fn fixture(directory: &Path, dataset: &str, records: &[Value]) {
        let spec = sources::specification(dataset).unwrap();
        std::fs::create_dir_all(directory.join("sources")).unwrap();
        let path = directory.join("sources").join(format!("{dataset}.csv"));
        let mut writer = csv::Writer::from_path(&path).unwrap();
        let headers: Vec<_> = spec.columns.iter().map(|c| c.csv_header.clone()).collect();
        writer.write_record(&headers).unwrap();
        for row in records {
            writer
                .write_record(
                    spec.columns
                        .iter()
                        .map(|c| row[&c.api_field].as_str().unwrap_or("")),
                )
                .unwrap();
        }
        writer.flush().unwrap();
        drop(writer);
        let manifest = json!({"dataset":dataset,"mapping_sha256":sources::mapping_sha256(),"sha256":sources::file_sha256(&path).unwrap(),"rows":records.len(),"bytes":path.metadata().unwrap().len(),"headers":headers,"stable_source_revision":true,"profiling_only":false,"source_revision_before":1,"source_revision_after":1,"expected_rows_before":records.len(),"expected_rows_after":records.len()});
        serde_json::to_writer(
            File::create(path.with_extension("manifest.json")).unwrap(),
            &manifest,
        )
        .unwrap();
    }
    #[test]
    fn publication_rolls_back_first_dataset_when_later_identity_invalid() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        fixture(
            temp.path(),
            "crashes",
            &[json!({"crash_record_id":"C1","crash_date":"2026-01-01"})],
        );
        fixture(temp.path(), "vehicles", &[json!({"crash_unit_id":"1"})]);
        assert!(
            publish_sources(
                &db,
                temp.path(),
                &["crashes".into(), "vehicles".into()],
                PublicationMode::Production,
                "rollback"
            )
            .is_err()
        );
        assert_eq!(
            db.query(
                "SELECT count(*) n FROM information_schema.tables WHERE table_name='crashes'",
                &[]
            )
            .unwrap()[0]["n"],
            0
        );
    }
    #[test]
    fn delayed_publication_never_advances_past_the_source_acquisition_boundary() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        fixture(
            temp.path(),
            "fatalities",
            &[json!({"person_id":"P1","crash_date":"2000-01-01"})],
        );
        publish_sources(
            &db,
            temp.path(),
            &["fatalities".into()],
            PublicationMode::Production,
            "old-receipt",
        )
        .unwrap();
        assert!(
            db.query(
                "SELECT source_updated_before FROM ingestion_checkpoints",
                &[]
            )
            .unwrap()[0]["source_updated_before"]
                .is_null()
        );
        let receipt_path = temp.path().join("sources/fatalities.manifest.json");
        let mut receipt: Value =
            serde_json::from_reader(File::open(&receipt_path).unwrap()).unwrap();
        receipt["acquisition_started_at"] = json!("2000-01-01T00:00:10Z");
        receipt["source_updated_before"] = json!("2000-01-01T00:00:00Z");
        receipt["downloaded_at"] = json!("2000-01-01T00:01:00Z");
        std::fs::write(&receipt_path, receipt.to_string()).unwrap();
        publish_sources(
            &db,
            temp.path(),
            &["fatalities".into()],
            PublicationMode::Production,
            "delayed-commit",
        )
        .unwrap();
        // An update after download proof must remain beyond the stored watermark,
        // even when publication happens years after the acquisition fixture.
        assert_eq!(db.query("SELECT count(*) n FROM ingestion_checkpoints WHERE source_updated_before=TIMESTAMPTZ '2000-01-01T00:00:00Z' AND source_updated_before<TIMESTAMPTZ '2000-01-01T00:02:00Z'",&[]).unwrap()[0]["n"],1);
        receipt["source_updated_before"] = json!("2000-01-01T00:03:00Z");
        std::fs::write(&receipt_path, receipt.to_string()).unwrap();
        assert!(
            publish_sources(
                &db,
                temp.path(),
                &["fatalities".into()],
                PublicationMode::Production,
                "invalid-watermark"
            )
            .is_err()
        );
        assert_eq!(db.query("SELECT count(*) n FROM ingestion_publications WHERE operation_id='invalid-watermark'",&[]).unwrap()[0]["n"],0);
        assert_eq!(db.query("SELECT count(*) n FROM ingestion_checkpoints WHERE source_updated_before=TIMESTAMPTZ '2000-01-01T00:00:00Z'",&[]).unwrap()[0]["n"],1);
    }
    #[test]
    fn production_replay_is_idempotent_and_updates_changed_rows_preserving_created_at() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        fixture(
            temp.path(),
            "crashes",
            &[json!({"crash_record_id":"C1","crash_date":"2026-01-01","posted_speed_limit":"30"})],
        );
        let first = publish_sources(
            &db,
            temp.path(),
            &["crashes".into()],
            PublicationMode::Production,
            "first",
        )
        .unwrap();
        assert_eq!(
            first,
            publish_sources(
                &db,
                temp.path(),
                &["crashes".into()],
                PublicationMode::Production,
                "first"
            )
            .unwrap()
        );
        let created =
            db.query("SELECT created_at FROM crashes", &[]).unwrap()[0]["created_at"].clone();
        fixture(
            temp.path(),
            "crashes",
            &[json!({"crash_record_id":"C1","crash_date":"2026-01-01","posted_speed_limit":"35"})],
        );
        let changed = publish_sources(
            &db,
            temp.path(),
            &["crashes".into()],
            PublicationMode::Production,
            "second",
        )
        .unwrap();
        assert_eq!(changed["datasets"]["crashes"]["changed_rows"], 1);
        assert_eq!(
            db.query("SELECT created_at FROM crashes", &[]).unwrap()[0]["created_at"],
            created
        );
        assert!(
            publish_sources(
                &db,
                temp.path(),
                &["crashes".into()],
                PublicationMode::Production,
                "first"
            )
            .is_err()
        );
    }
    #[test]
    fn people_keep_null_child_dates_and_chicago_coordinate_policy() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        fixture(
            temp.path(),
            "people",
            &[json!({"crash_record_id":"C1","person_id":"P1","age":"121"})],
        );
        publish_sources(
            &db,
            temp.path(),
            &["people".into()],
            PublicationMode::Production,
            "people",
        )
        .unwrap();
        let row = &db
            .query("SELECT crash_date,age FROM crash_people", &[])
            .unwrap()[0];
        assert!(row["crash_date"].is_null() && row["age"].is_null());
        fixture(
            temp.path(),
            "people",
            &[
                json!({"crash_record_id":"C1","person_id":"P1","age":"119","crash_date":"2026-01-01"}),
            ],
        );
        publish_sources(
            &db,
            temp.path(),
            &["people".into()],
            PublicationMode::Production,
            "people-updated",
        )
        .unwrap();
        let updated = &db
            .query("SELECT crash_date,age FROM crash_people", &[])
            .unwrap()[0];
        assert!(updated["crash_date"].is_null());
        assert_eq!(updated["age"], 119);
    }
    #[test]
    fn fatalities_coalesce_wkt_json_points_and_roll_back_bad_source_points() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        let mut rows: Vec<_> = (0..40)
            .map(|id| json!({"person_id":format!("P{id}"),"crash_date":"2026-01-01"}))
            .collect();
        rows.push(json!({"person_id":"same","crash_date":"2026-01-01","geocoded_column":"POINT (-87.6000 41.8000)"}));
        rows.push(json!({"person_id":"same","crash_date":"2026-01-01","geocoded_column":r#"{"type":"Point","coordinates":[-87.6,41.8]}"#}));
        fixture(temp.path(), "fatalities", &rows);
        let receipt = publish_sources(
            &db,
            temp.path(),
            &["fatalities".into()],
            PublicationMode::Production,
            "points",
        )
        .unwrap();
        assert_eq!(
            receipt["datasets"]["fatalities"]["identity_rejections"]["identical_duplicate_person_id"],
            1
        );
        assert_eq!(
            db.query(
                "SELECT geocoded_column FROM vision_zero_fatalities WHERE person_id='same'",
                &[]
            )
            .unwrap()[0]["geocoded_column"],
            "POINT (-87.6 41.8)"
        );
        rows.push(
            json!({"person_id":"bad","crash_date":"2026-01-01","geocoded_column":"POINT (NaN 41)"}),
        );
        fixture(temp.path(), "fatalities", &rows);
        assert!(
            publish_sources(
                &db,
                temp.path(),
                &["fatalities".into()],
                PublicationMode::Production,
                "points-invalid"
            )
            .is_err()
        );
        assert_eq!(
            db.query("SELECT count(*) n FROM vision_zero_fatalities", &[])
                .unwrap()[0]["n"],
            41
        );
        assert_eq!(
            db.query(
                "SELECT count(*) n FROM ingestion_publications WHERE operation_id='points-invalid'",
                &[]
            )
            .unwrap()[0]["n"],
            0
        );
    }
    #[test]
    fn fatalities_exclude_every_conflicting_identity_inside_rejection_guard() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        let mut rows: Vec<_> = (0..40)
            .map(|id| json!({"person_id":format!("P{id}"),"crash_date":"2026-01-01"}))
            .collect();
        rows.push(json!({"person_id":"conflict","crash_date":"2026-01-01"}));
        rows.push(json!({"person_id":"conflict","crash_date":"2026-02-01"}));
        fixture(temp.path(), "fatalities", &rows);
        let result = publish_sources(
            &db,
            temp.path(),
            &["fatalities".into()],
            PublicationMode::Production,
            "fatalities",
        )
        .unwrap();
        assert_eq!(
            result["datasets"]["fatalities"]["identity_rejections"]["conflicting_person_id"],
            2
        );
        assert_eq!(
            db.query("SELECT count(*) n FROM vision_zero_fatalities", &[])
                .unwrap()[0]["n"],
            40
        );
    }
}

/// Run one bounded acquisition attempt under the owner lease/deadline fence.
fn refresh_attempt(
    db: &Database,
    directory: &Path,
    datasets: &[String],
    operation_id: &str,
    check: &sources::Check<'_>,
    window: Option<(&str, &str)>,
    api_only: bool,
) -> Result<Value> {
    ensure!(!datasets.is_empty(), "choose at least one dataset");
    for dataset in datasets {
        sources::specification(dataset)?;
    }
    let attempts = directory.join("attempts");
    std::fs::create_dir_all(&attempts)?;
    let attempts = attempts.canonicalize()?;
    let max_bytes = configured_limit("CRASHES_INGESTION_MAX_BYTES", 8 * 1024 * 1024 * 1024)?;
    ensure!(
        max_bytes > 0,
        "CRASHES_INGESTION_MAX_BYTES must be positive"
    );
    prune_attempts(&attempts, 1, max_bytes / 4)?;
    let attempt = attempts.join(uuid::Uuid::new_v4().to_string());
    std::fs::create_dir(&attempt)?;
    std::fs::write(
        attempt.join(".ingestion-attempt"),
        json!({"format_version":1,"operation_id":operation_id}).to_string(),
    )?;
    let last_budget_check =
        std::sync::Mutex::new(std::time::Instant::now() - std::time::Duration::from_secs(2));
    let checked = || {
        check()?;
        let mut previous = last_budget_check
            .lock()
            .map_err(|_| anyhow::anyhow!("ingestion budget mutex poisoned"))?;
        if previous.elapsed() >= std::time::Duration::from_secs(1) {
            ensure!(
                fs2::available_space(&attempt)? > 256 * 1024 * 1024,
                "ingestion requires 256MiB free disk reserve"
            );
            ensure!(
                directory_bytes(&attempts)? <= max_bytes,
                "ingestion staging disk budget exceeded"
            );
            *previous = std::time::Instant::now();
        }
        Ok(())
    };
    let result = (|| {
        for dataset in datasets {
            if let Some((start, end)) = window {
                sources::download_api_window_source(&attempt, dataset, start, end, &checked)?;
                continue;
            }
            if api_only {
                sources::download_api_source_guarded(&attempt, dataset, &checked)?;
                continue;
            }
            if let Err(csv_error) = sources::download_source_guarded(&attempt, dataset, &checked) {
                checked()?;
                tracing::warn!(dataset,error=%csv_error,"strict bulk source rejected; trying complete ordered API bootstrap");
                let fallback = attempt.join(format!("api-{dataset}"));
                let source = sources::download_api_source_guarded(&fallback, dataset, &checked)?;
                let destination = attempt.join("sources").join(format!("{dataset}.csv"));
                ensure!(
                    !destination.exists() && !destination.with_extension("manifest.json").exists(),
                    "failed bulk attempt already published artifacts; inspect before retry"
                );
                std::fs::hard_link(&source.path, &destination)?;
                std::fs::hard_link(
                    source.path.with_extension("manifest.json"),
                    destination.with_extension("manifest.json"),
                )?;
            }
        }
        checked()?;
        publish_sources_guarded(
            db,
            &attempt,
            datasets,
            PublicationMode::Production,
            operation_id,
            &checked,
        )
    })();
    if result.is_ok() {
        remove_owned_attempt(&attempts, &attempt)?;
    }
    prune_attempts(&attempts, 2, max_bytes)?;
    result
}
fn directory_bytes(directory: &Path) -> Result<u64> {
    let mut bytes = 0_u64;
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        ensure!(!kind.is_symlink(), "symlink in ingestion staging directory");
        bytes = bytes
            .checked_add(if kind.is_dir() {
                directory_bytes(&entry.path())?
            } else {
                entry.metadata()?.len()
            })
            .context("ingestion size overflow")?;
    }
    Ok(bytes)
}
fn remove_owned_attempt(root: &Path, path: &Path) -> Result<()> {
    ensure!(
        path.parent() == Some(root) && path.join(".ingestion-attempt").is_file(),
        "refusing cleanup outside owned attempt"
    );
    let name = path
        .file_name()
        .and_then(|v| v.to_str())
        .context("attempt filename missing")?;
    uuid::Uuid::parse_str(name).context("attempt directory is not UUID")?;
    ensure!(
        !path.symlink_metadata()?.file_type().is_symlink(),
        "refusing symlink cleanup"
    );
    std::fs::remove_dir_all(path)?;
    Ok(())
}
fn prune_attempts(root: &Path, keep: usize, max_bytes: u64) -> Result<()> {
    let mut attempts = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() || !entry.path().join(".ingestion-attempt").is_file() {
            continue;
        }
        if entry
            .file_name()
            .to_str()
            .and_then(|name| uuid::Uuid::parse_str(name).ok())
            .is_none()
        {
            continue;
        }
        attempts.push((
            entry.metadata()?.modified()?,
            entry.path(),
            directory_bytes(&entry.path())?,
        ));
    }
    attempts.sort_by_key(|entry| std::cmp::Reverse(entry.0));
    let mut retained = 0_u64;
    for (index, (_, path, bytes)) in attempts.into_iter().enumerate() {
        if index >= keep || retained.saturating_add(bytes) > max_bytes {
            remove_owned_attempt(root, &path)?;
        } else {
            retained += bytes;
        }
    }
    Ok(())
}

/// Restore a consistent read-only PostgreSQL export without re-sanitizing stored
/// values. External Parquet artifacts require checksums, physical schema receipts,
/// explicit null-only columns, source snapshot identity and exact row counts.
pub fn import_fact_snapshot(db: &Database, directory: &Path) -> Result<Value> {
    let root = directory.canonicalize()?;
    let manifest: Value =
        serde_json::from_reader(std::fs::File::open(root.join("manifest.json"))?)?;
    ensure!(
        manifest["format_version"] == 1
            && manifest["source_kind"] == "postgresql_repeatable_read"
            && manifest["production_snapshot"] == true
            && manifest["source_transaction_read_only"] == true,
        "expected consistent PostgreSQL snapshot manifest"
    );
    ensure!(
        manifest["snapshot_id"]
            .as_str()
            .is_some_and(|v| !v.is_empty()),
        "PostgreSQL snapshot identity missing"
    );
    let table_receipts = manifest["tables"]
        .as_object()
        .context("snapshot table receipts missing")?;
    let mut inputs = Vec::new();
    for dataset in sources::DATASETS {
        let table = table_name(dataset)?;
        let receipt = table_receipts
            .get(table)
            .context("all four fact tables must be supplied")?;
        let input = root
            .join(
                receipt["file"]
                    .as_str()
                    .context("snapshot parquet filename missing")?,
            )
            .canonicalize()?;
        ensure!(
            input.starts_with(&root) && input.is_file(),
            "snapshot file escapes root"
        );
        ensure!(
            receipt["sha256"] == sources::file_sha256(&input)?,
            "snapshot checksum mismatch for {table}"
        );
        ensure!(
            receipt["bytes"].as_u64() == Some(input.metadata()?.len()),
            "snapshot size mismatch for {table}"
        );
        inputs.push((dataset, table, input, receipt));
    }
    let mut checkpoints = Vec::new();
    if let Some(receipt) = manifest
        .get("operations")
        .and_then(|ops| ops.get("ingestion_checkpoints"))
        && receipt["absent"] != true
    {
        let path = root
            .join(
                receipt["file"]
                    .as_str()
                    .context("checkpoint file missing")?,
            )
            .canonicalize()?;
        ensure!(
            path.starts_with(&root) && path.metadata()?.len() <= 1048576,
            "invalid checkpoint snapshot path/size"
        );
        ensure!(
            receipt["sha256"] == sources::file_sha256(&path)?
                && receipt["bytes"].as_u64() == Some(path.metadata()?.len()),
            "checkpoint checksum/size mismatch"
        );
        use std::io::BufRead;
        for line in std::io::BufReader::new(std::fs::File::open(path)?).lines() {
            let row: Value = serde_json::from_str(&line?)?;
            ensure!(
                row["endpoint"]
                    .as_str()
                    .is_some_and(|endpoint| sources::DATASETS.contains(&endpoint))
                    && row["source_updated_before"].as_str().is_some(),
                "invalid actual checkpoint row"
            );
            checkpoints.push(row);
        }
        ensure!(
            receipt["rows"].as_u64() == Some(checkpoints.len() as u64),
            "checkpoint row count mismatch"
        );
    }
    db.transaction(|session|{
        let mut imported=serde_json::Map::new();
        for (dataset,table,input,receipt) in &inputs{
            ensure!(count(session,&format!("SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name={}",sources::literal(table)))?==0,"snapshot target {table} already exists");
            let relation=format!("read_parquet({})",sources::literal(input.to_str().context("snapshot path must be UTF-8")?));
            let physical=session.query(&format!("DESCRIBE SELECT * FROM {relation}"),&[])?;
            let observed:BTreeMap<_,_>=physical.iter().map(|v|Ok((v["column_name"].as_str().context("physical column missing")?.to_owned(),v["column_type"].as_str().context("physical type missing")?.to_owned()))).collect::<Result<_>>()?;
            let declared:BTreeMap<String,String>=serde_json::from_value(receipt["columns"].clone()).context("snapshot physical schema receipt missing")?;
            ensure!(observed==declared,"snapshot schema drift for {table}");
            let nulls:Vec<String>=serde_json::from_value(receipt["null_columns"].clone()).context("explicit null-only target columns missing")?;
            let schema=schema_columns(dataset)?;
            let mut projection=Vec::new();
            for (field,kind) in &schema{
                let identifier=sources::identifier(field);
                let expression=if field=="geometry"{
                    ensure!(observed.contains_key("geometry_wkb_hex")&&observed.contains_key("geometry_srid"),"snapshot requires exact WKB and SRID for {table}");
                    ensure!(count(session,&format!("SELECT count(*) n FROM {relation} WHERE geometry_wkb_hex IS NOT NULL AND(geometry_srid IS NULL OR geometry_srid<>4326)"))?==0,"snapshot non-WGS84 geometry");
                    "CASE WHEN geometry_wkb_hex IS NULL THEN NULL ELSE ST_GeomFromHEXWKB(geometry_wkb_hex) END".to_owned()
                }else if observed.contains_key(field){format!("CAST({identifier} AS {kind})")}
                else{ensure!(nulls.contains(field),"missing snapshot column {table}.{field} requires explicit null declaration");format!("NULL::{kind}")};
                projection.push(format!("{expression} AS {identifier}"));
            }
            ensure!(nulls.iter().all(|field|schema.contains_key(field)&&!observed.contains_key(field)),"invalid explicit null-only snapshot columns");
            session.execute(&format!("CREATE TABLE {table} AS SELECT {} FROM {relation}",projection.join(",")),&[])?;
            let rows=count(session,&format!("SELECT count(*) n FROM {table}"))?;
            ensure!(receipt["rows"].as_u64()==Some(rows),"snapshot row count mismatch");
            if *dataset!="fatalities"{validate_core(session,table,dataset)?;}
            if schema.contains_key("geometry"){
                ensure!(count(session,&format!("SELECT count(*) n FROM {table} WHERE geometry IS NOT NULL AND(NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry))"))?==0,"snapshot invalid geometry");
            }
            imported.insert((*table).to_owned(),json!({"rows":rows,"sha256":receipt["sha256"]}));
        }
        session.execute("CREATE TABLE IF NOT EXISTS ingestion_checkpoints(dataset VARCHAR PRIMARY KEY,source_revision BIGINT,operation_id VARCHAR,updated_at TIMESTAMPTZ,source_updated_before TIMESTAMPTZ)",&[])?;
        session.execute("ALTER TABLE ingestion_checkpoints ADD COLUMN IF NOT EXISTS source_updated_before TIMESTAMPTZ",&[])?;
        for checkpoint in &checkpoints{session.execute("INSERT INTO ingestion_checkpoints(dataset,source_revision,operation_id,updated_at,source_updated_before) VALUES(?,NULL,?,current_timestamp,?::TIMESTAMPTZ)",&[checkpoint["endpoint"].clone(),manifest["snapshot_id"].clone(),checkpoint["source_updated_before"].clone()])?;}
        session.execute("CREATE TABLE IF NOT EXISTS fact_snapshot_imports(import_id VARCHAR PRIMARY KEY,imported_at TIMESTAMPTZ,receipt JSON)",&[])?;
        let receipt=json!({"import_id":uuid::Uuid::new_v4().to_string(),"snapshot_id":manifest["snapshot_id"],"production_snapshot":true,"source_kind":"postgresql_repeatable_read","tables":imported,"historical_values_resanitized":false});
        session.execute("INSERT INTO fact_snapshot_imports VALUES(?,current_timestamp,?)",&[receipt["import_id"].clone(),json!(receipt.to_string())])?;
        crate::mutations::record(session,"facts.snapshot_import",&receipt)?;
        Ok(receipt)
    })
}

#[cfg(test)]
mod migration_tests {
    use super::*;
    fn database(directory: &Path, name: &str) -> Option<Database> {
        let library = crate::test_support::library();
        let db = Database::open(
            &directory.join(format!("{name}.duckdb")),
            &library,
            "256MB",
            1,
            &directory.join(format!("{name}-spill")),
        )
        .unwrap();
        crate::test_support::load_spatial(&db);
        Some(db)
    }
    #[test]
    fn typed_snapshot_preserves_null_people_dates_and_historical_values_without_sanitizing() {
        let temp = tempfile::tempdir().unwrap();
        let Some(source) = database(temp.path(), "source") else {
            return;
        };
        let mut tables = serde_json::Map::new();
        for dataset in sources::DATASETS {
            let table = table_name(dataset).unwrap();
            let schema = schema_columns(dataset).unwrap();
            let ddl = schema
                .iter()
                .map(|(name, kind)| format!("{} {kind}", sources::identifier(name)))
                .collect::<Vec<_>>()
                .join(",");
            source
                .execute(&format!("CREATE TABLE {table}({ddl})"), &[])
                .unwrap();
            let statement = match dataset {
                "crashes" => {
                    "INSERT INTO crashes(crash_record_id,crash_date,posted_speed_limit,created_at,updated_at,geometry) VALUES('C1','2020-01-01',-12,'2019-01-01','2020-01-02',ST_Point(-87.6,41.8))"
                }
                "people" => {
                    "INSERT INTO crash_people(crash_record_id,person_id,crash_date,age,created_at) VALUES('C1','P1',NULL,130,'2019-01-01')"
                }
                "vehicles" => {
                    "INSERT INTO crash_vehicles(crash_record_id,crash_unit_id,vehicle_year) VALUES('C1','V1',1800)"
                }
                _ => {
                    "INSERT INTO vision_zero_fatalities(person_id,crash_date) VALUES('F1','2020-01-01')"
                }
            };
            source.execute(statement, &[]).unwrap();
            let path = temp.path().join(format!("{table}.parquet"));
            let projection = if schema.contains_key("geometry") {
                "* EXCLUDE(geometry),ST_AsHEXWKB(geometry) geometry_wkb_hex,4326 geometry_srid"
            } else {
                "*"
            };
            source
                .execute(
                    &format!(
                        "COPY(SELECT {projection} FROM {table}) TO {}(FORMAT PARQUET)",
                        sources::literal(path.to_str().unwrap())
                    ),
                    &[],
                )
                .unwrap();
            let physical = source
                .query(
                    &format!(
                        "DESCRIBE SELECT * FROM read_parquet({})",
                        sources::literal(path.to_str().unwrap())
                    ),
                    &[],
                )
                .unwrap();
            let columns: BTreeMap<_, _> = physical
                .iter()
                .map(|v| {
                    (
                        v["column_name"].as_str().unwrap(),
                        v["column_type"].as_str().unwrap(),
                    )
                })
                .collect();
            tables.insert(table.to_owned(),json!({"file":path.file_name().unwrap().to_str().unwrap(),"rows":1,"bytes":path.metadata().unwrap().len(),"sha256":sources::file_sha256(&path).unwrap(),"columns":columns,"null_columns":[]}));
        }
        let manifest = json!({"format_version":1,"source_kind":"postgresql_repeatable_read","production_snapshot":true,"snapshot_id":"test-readonly-snapshot","source_transaction_read_only":true,"tables":tables});
        std::fs::write(temp.path().join("manifest.json"), manifest.to_string()).unwrap();
        let target = database(temp.path(), "target").unwrap();
        import_fact_snapshot(&target, temp.path()).unwrap();
        let people = &target
            .query("SELECT crash_date,age,created_at FROM crash_people", &[])
            .unwrap()[0];
        assert!(people["crash_date"].is_null());
        assert_eq!(people["age"], 130);
        assert_eq!(people["created_at"], "2019-01-01 00:00:00");
        assert_eq!(
            target
                .query("SELECT vehicle_year FROM crash_vehicles", &[])
                .unwrap()[0]["vehicle_year"],
            1800
        );
    }
    #[test]
    fn retention_removes_only_marked_uuid_attempts_and_respects_byte_cap() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let untouched = root.join("sources");
        std::fs::create_dir(&untouched).unwrap();
        std::fs::write(untouched.join("keep.csv"), "preserved").unwrap();
        for _ in 0..3 {
            let path = root.join(uuid::Uuid::new_v4().to_string());
            std::fs::create_dir(&path).unwrap();
            std::fs::write(path.join(".ingestion-attempt"), "{}").unwrap();
            std::fs::write(path.join("large.csv"), vec![0_u8; 20]).unwrap();
        }
        prune_attempts(&root, 2, 50).unwrap();
        let owned = std::fs::read_dir(&root)
            .unwrap()
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.path().join(".ingestion-attempt").is_file())
            .count();
        assert_eq!(owned, 2);
        assert!(untouched.join("keep.csv").is_file());
    }
}

/// Execute the operator's requested endpoint/mode/window without broadening it
/// into an all-table historical refresh. Unsupported watermark modes fail closed.
pub fn refresh_request_guarded(
    db: &Database,
    directory: &Path,
    request: &Value,
    operation_id: &str,
    check: &sources::Check<'_>,
) -> Result<Value> {
    check()?;
    if let Some(receipt) = committed_publication(db, operation_id)? {
        return Ok(receipt);
    }

    let mut configuration = request
        .get("config")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    if let Some(top) = request.as_object() {
        for (key, value) in top {
            if key != "config" {
                configuration.insert(key.clone(), value.clone());
            }
        }
    }
    let config = Value::Object(configuration);
    ensure!(
        config["held"] != true && config["hold"] != true && config["disabled"] != true,
        "ingestion request is held or disabled"
    );
    ensure!(
        config["repair_null_people_dates"] != true,
        "null people date repair requires separate reviewed migration; daily ingestion preserves historical nulls"
    );
    let kind = config["job_type"].as_str().unwrap_or("");
    let requested = config.get("endpoints").or_else(|| config.get("datasets"));
    let datasets: Vec<String> = if let Some(requested) = requested {
        serde_json::from_value(requested.clone()).context("ingestion endpoints must be an array")?
    } else {
        match kind {
            "last_30_days_core_data" | "last_30_days_crashes" => {
                vec!["crashes".into(), "people".into(), "vehicles".into()]
            }
            "last_30_days_people" => vec!["people".into()],
            "last_30_days_vehicles" => vec!["vehicles".into()],
            "last_6_months_fatalities" => vec!["fatalities".into()],
            _ => anyhow::bail!(
                "explicit ingestion endpoints required; no implicit all-table refresh"
            ),
        }
    };
    ensure!(!datasets.is_empty(), "choose ingestion endpoints");
    for dataset in &datasets {
        sources::specification(dataset)?;
    }
    let mode = config["mode"]
        .as_str()
        .unwrap_or(if kind == "full_refresh" {
            "full"
        } else if kind == "incremental" {
            "incremental"
        } else {
            "api"
        });
    match mode {
        "full" => {
            ensure!(
                config["allow_full_refresh"] == true,
                "full source replay requires explicit allow_full_refresh after review of operational change guard"
            );
            ensure!(
                config.get("start_date").is_none_or(Value::is_null)
                    && config.get("end_date").is_none_or(Value::is_null),
                "full refresh cannot use event-date filters"
            );
            refresh_attempt(db, directory, &datasets, operation_id, check, None, false)
        }
        "incremental" => {
            ensure!(
                datasets.iter().all(|dataset| dataset == "fatalities"),
                "core source-modification incremental ingestion is not implemented; preserve the job as held pending reviewed watermark migration"
            );
            ensure!(
                config.get("start_date").is_none_or(Value::is_null)
                    && config.get("end_date").is_none_or(Value::is_null),
                "incremental mode cannot use event-date filters"
            );
            let has_checkpoint=db.query("SELECT count(*) n FROM information_schema.tables WHERE table_name='ingestion_checkpoints'",&[])?;
            ensure!(
                has_checkpoint[0]["n"].as_u64().unwrap_or(0) > 0,
                "incremental fatalities require imported checkpoint or explicit full bootstrap"
            );
            let checkpoint = db.query(
                "SELECT count(*) n FROM ingestion_checkpoints WHERE dataset='fatalities' AND source_updated_before IS NOT NULL",
                &[],
            )?;
            ensure!(
                checkpoint[0]["n"].as_u64().unwrap_or(0) > 0,
                "incremental fatalities checkpoint missing; explicit full bootstrap required"
            );
            // As deployed, a fatality delta cannot validate identity conflicts.
            refresh_attempt(db, directory, &datasets, operation_id, check, None, true)
        }
        "api" => {
            let today = chrono::Utc::now()
                .with_timezone(&chrono_tz::America::Chicago)
                .date_naive();
            let days = config["date_range_days"].as_i64().unwrap_or(
                if kind == "last_6_months_fatalities" {
                    180
                } else {
                    30
                },
            );
            ensure!(
                (1..=36500).contains(&days),
                "invalid ingestion date_range_days"
            );
            let default_start = (today - chrono::Duration::days(days)).to_string();
            let default_end = today.to_string();
            let start = config["start_date"].as_str().unwrap_or(&default_start);
            let end = config["end_date"].as_str().unwrap_or(&default_end);
            refresh_attempt(
                db,
                directory,
                &datasets,
                operation_id,
                check,
                Some((start, end)),
                true,
            )
        }
        _ => anyhow::bail!("unsupported ingestion mode {mode}"),
    }
}

/// Reconcile a durable queue attempt whose DuckDB commit preceded SQLite finish.
/// Queue operation IDs must remain bound to their original immutable request.
pub fn committed_publication(db: &Database, operation_id: &str) -> Result<Option<Value>> {
    let exists=db.query("SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name='ingestion_publications'",&[])?;
    if exists[0]["n"].as_u64().unwrap_or(0) == 0 {
        return Ok(None);
    }
    let rows = db.query(
        "SELECT receipt FROM ingestion_publications WHERE operation_id=?",
        &[json!(operation_id)],
    )?;
    rows.first()
        .map(|row| {
            if let Some(text) = row["receipt"].as_str() {
                Ok(serde_json::from_str(text)?)
            } else {
                Ok(row["receipt"].clone())
            }
        })
        .transpose()
}

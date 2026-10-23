//! Atomic analytical mutation receipts also drive recovery snapshot scheduling.
use crate::db::{Database, Session};

/// Reconcile the cross-store crash gap without replaying a data deletion.
pub fn reconcile_deletions(db: &Database, control: &crate::control::ControlStore) -> Result<()> {
    if db
        .query(
            "SELECT 1 FROM information_schema.tables WHERE table_name='rust_mutations'",
            &[],
        )?
        .is_empty()
    {
        return Ok(());
    }
    let mut cursor = String::new();
    loop {
        let rows=db.query("SELECT id,payload FROM rust_mutations WHERE id>$1 AND json_extract_string(payload,'$.action')='data_delete' ORDER BY id LIMIT 500",&[json!(cursor)])?;
        if rows.is_empty() {
            break;
        }
        for row in rows {
            cursor = row["id"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("mutation ID missing"))?
                .to_owned();
            let payload: Value = serde_json::from_str(
                row["payload"]
                    .as_str()
                    .ok_or_else(|| anyhow::anyhow!("mutation payload missing"))?,
            )?;
            let details = &payload["details"];
            let id = details["request"]["operation_id"]
                .as_str()
                .unwrap_or(&cursor);
            crate::admin::record_deletion(control, id, details)?;
        }
    }
    Ok(())
}
use anyhow::{Result, ensure};
use serde_json::{Value, json};

/// Record a mutation in the same transaction as the affected analytical tables.
pub fn record(session: &Session, action: &str, payload: &Value) -> Result<()> {
    session.execute("CREATE TABLE IF NOT EXISTS rust_mutations(id VARCHAR PRIMARY KEY,committed_at TIMESTAMPTZ,payload JSON)",&[])?;
    session.execute(
        "INSERT INTO rust_mutations VALUES($1,current_timestamp,$2)",
        &[
            json!(uuid::Uuid::new_v4().to_string()),
            json!({"action":action,"details":payload})
                .to_string()
                .into(),
        ],
    )
}

/// Most recent committed mutation, used to detect a missing post-commit snapshot.
pub fn revision(db: &Database) -> Result<Option<String>> {
    if db
        .query(
            "SELECT 1 FROM information_schema.tables WHERE table_name='rust_mutations'",
            &[],
        )?
        .is_empty()
    {
        return Ok(None);
    }
    Ok(db
        .query(
            "SELECT id FROM rust_mutations ORDER BY committed_at DESC,id DESC LIMIT 1",
            &[],
        )?
        .first()
        .and_then(|r| r["id"].as_str())
        .map(str::to_owned))
}

/// Date-bounded legacy deletion and its audit record commit together.
pub fn delete_data(db: &Database, request: &Value) -> Result<Value> {
    let started = std::time::Instant::now();
    let table = request["table_name"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("table_name required"))?;
    ensure!(
        [
            "crashes",
            "crash_people",
            "crash_vehicles",
            "vision_zero_fatalities"
        ]
        .contains(&table),
        "invalid table_name"
    );
    let dates = crate::queries::DateRange {
        start_date: request["date_range"]["start"].as_str().map(str::to_owned),
        end_date: request["date_range"]["end"].as_str().map(str::to_owned),
    };
    let (predicate, params) = crate::queries::date_predicate(&dates)?;
    ensure!(
        request["confirm"] == true || request["confirm_deletion"] == true,
        "explicit deletion confirmation is required"
    );
    db.transaction(|session|{
        let count=session.query(&format!("SELECT count(*) AS n FROM {table} WHERE {predicate}"),&params)?;
        session.execute(&format!("DELETE FROM {table} WHERE {predicate}"),&params)?;
        let receipt=json!({"message":format!("Deleted records from {table}"),"table_name":table,"records_deleted":count[0]["n"],"execution_time_seconds":started.elapsed().as_secs_f64(),"backup_location":request["backup_id"],"can_restore":request["backup_id"].is_string(),"request":request,"deleted_at":chrono::Utc::now()});
        record(session,"data_delete",&receipt)?;
        Ok(receipt)
    })
}

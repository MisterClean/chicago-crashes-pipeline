//! Bounded, read-only acquisition of one consistent PostgreSQL migration snapshot.
use crate::{
    db::Database,
    ingestion,
    sources::{self, Check},
};
use anyhow::{Context, Result, ensure};
use postgres::{IsolationLevel, Transaction};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    io::{Read, Write},
    path::Path,
};

fn private_directory(path: &Path) -> Result<()> {
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path)?;
    Ok(())
}
fn private_file(path: &Path) -> Result<File> {
    let mut options = File::options();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    Ok(options.open(path)?)
}
fn secure_native_file(path: &Path) -> Result<()> {
    // Native COPY creates this file inside the already-private snapshot root.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    File::open(path)?.sync_all()?;
    Ok(())
}

fn stream_copy(
    transaction: &mut Transaction<'_>,
    sql: &str,
    path: &Path,
    check: &Check<'_>,
) -> Result<u64> {
    let mut reader = transaction.copy_out(sql)?;
    let mut output = private_file(path)?;
    let mut bytes = 0_u64;
    let mut buffer = [0_u8; 65536];
    loop {
        check()?;
        let size = reader.read(&mut buffer)?;
        if size == 0 {
            break;
        }
        bytes += size as u64;
        ensure!(
            bytes <= 8 * 1024 * 1024 * 1024,
            "migration table exceeds 8GiB transfer cap"
        );
        ensure!(
            fs2::available_space(path)? > 256 * 1024 * 1024,
            "migration disk reserve exhausted"
        );
        output.write_all(&buffer[..size])?;
    }
    output.sync_all()?;
    Ok(bytes)
}
fn columns(transaction: &mut Transaction<'_>, table: &str) -> Result<Vec<String>> {
    Ok(transaction.query("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position",&[&table])?.into_iter().map(|row|row.get(0)).collect())
}
fn operations(
    transaction: &mut Transaction<'_>,
    table: &str,
    directory: &Path,
    check: &Check<'_>,
) -> Result<Value> {
    let fields = columns(transaction, table)?;
    if fields.is_empty() {
        return Ok(json!({"absent":true}));
    }
    let path = directory.join("operations").join(format!("{table}.ndjson"));
    let sql = format!(
        "COPY(SELECT row_to_json(t)::text FROM {} t) TO STDOUT WITH(FORMAT CSV)",
        sources::identifier(table)
    );
    let reader = transaction.copy_out(&sql)?;
    let mut records = csv::ReaderBuilder::new()
        .has_headers(false)
        .from_reader(reader);
    let mut row = csv::StringRecord::new();
    let mut count = 0_u64;
    let mut output = private_file(&path)?;
    while records.read_record(&mut row)? {
        check()?;
        ensure!(row.len() == 1, "invalid operational row export");
        let text = row.get(0).context("operational record missing")?;
        ensure!(
            text.len() <= 16 * 1024 * 1024,
            "operational row exceeds 16MiB"
        );
        let parsed: Value = serde_json::from_str(text)?;
        ensure!(parsed.is_object(), "operational export row must be object");
        output.write_all(text.as_bytes())?;
        output.write_all(b"\n")?;
        count += 1;
        ensure!(
            output.metadata()?.len() <= 512 * 1024 * 1024,
            "operational table exceeds 512MiB export cap"
        );
    }
    output.sync_all()?;
    Ok(
        json!({"file":format!("operations/{table}.ndjson"),"rows":count,"bytes":path.metadata()?.len(),"sha256":sources::file_sha256_guarded(&path,check)?,"columns":fields}),
    )
}
fn boundaries(
    transaction: &mut Transaction<'_>,
    directory: &Path,
    check: &Check<'_>,
) -> Result<Value> {
    let root = directory.join("boundaries");
    private_directory(&root)?;
    let rows = transaction.query(
        "SELECT row_to_json(t)::text FROM spatial_layers t ORDER BY id",
        &[],
    )?;
    ensure!(
        rows.len() <= 10000,
        "too many boundary layers for migration metadata"
    );
    let layers = rows
        .iter()
        .map(|row| serde_json::from_str::<Value>(row.get::<_, &str>(0)))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let path = root.join("features.ndjson");
    let sql = "COPY(SELECT row_to_json(f)::text FROM(SELECT id,layer_id,properties::text properties_json,encode(ST_AsBinary(geometry),'hex') geometry_wkb_hex,ST_SRID(geometry) srid,created_at,updated_at FROM spatial_layer_features ORDER BY id) f) TO STDOUT WITH(FORMAT CSV)";
    let reader = transaction.copy_out(sql)?;
    let mut csv = csv::ReaderBuilder::new()
        .has_headers(false)
        .from_reader(reader);
    let mut row = csv::StringRecord::new();
    let mut count = 0_u64;
    let mut output = private_file(&path)?;
    while csv.read_record(&mut row)? {
        check()?;
        let text = row.get(0).context("boundary record missing")?;
        let _: Value = serde_json::from_str(text)?;
        output.write_all(text.as_bytes())?;
        output.write_all(b"\n")?;
        count += 1;
        ensure!(
            output.metadata()?.len() <= 512 * 1024 * 1024,
            "boundary snapshot exceeds 512MiB"
        );
    }
    output.sync_all()?;
    let manifest = json!({"format_version":1,"source":"existing uploaded boundaries; consistent read-only PostgreSQL snapshot","captured_at":chrono::Utc::now().to_rfc3339(),"layers":layers,"features_file":"features.ndjson","feature_count":count,"features_sha256":sources::file_sha256_guarded(&path,check)?,"features_bytes":path.metadata()?.len(),"contains_crash_records":false,"feature_timestamps_preserved":true});
    write_manifest(&root.join("manifest.json"), &manifest)?;
    Ok(json!({"directory":"boundaries","layers":layers.len(),"features":count}))
}
fn write_manifest(path: &Path, value: &Value) -> Result<()> {
    let mut file = private_file(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.sync_all()?;
    Ok(())
}

/// Credentials are read only from PG_MIGRATION_URL, never printed or serialized.
/// The explicit flag authorizes read load; no source mutation is possible inside
/// the repeatable-read/read-only transaction. Destination must be new and local.
pub fn export_postgres_snapshot(
    db: &Database,
    directory: &Path,
    allow_production_read: bool,
    check: &Check<'_>,
) -> Result<Value> {
    ensure!(
        allow_production_read,
        "explicit --allow-production-read required for consistent PostgreSQL snapshot acquisition"
    );
    ensure!(
        !directory.exists(),
        "migration destination exists; choose a new directory"
    );
    let url = std::env::var("PG_MIGRATION_URL").context("PG_MIGRATION_URL is required")?;
    let mut configuration: postgres::Config = url
        .parse()
        .map_err(|_| anyhow::anyhow!("invalid PostgreSQL migration connection configuration"))?;
    configuration.connect_timeout(std::time::Duration::from_secs(30));
    configuration.ssl_mode(postgres::config::SslMode::Require);
    let mut tls_builder = native_tls::TlsConnector::builder();
    if let Some(path) = std::env::var_os("PG_MIGRATION_CA_CERT") {
        let path = std::path::PathBuf::from(path);
        ensure!(
            path.metadata()?.len() <= 1048576,
            "migration CA certificate exceeds 1MiB"
        );
        let certificate = native_tls::Certificate::from_pem(&fs::read(path)?)
            .context("invalid trusted PostgreSQL CA PEM certificate")?;
        tls_builder.add_root_certificate(certificate);
    }
    let tls = tls_builder.build()?;
    let mut client=configuration.connect(postgres_native_tls::MakeTlsConnector::new(tls)).map_err(|error|{
        // PostgreSQL's outer error is a fixed category; omit its potentially
        // sensitive server detail and never format the connection configuration.
        let tls_error=std::error::Error::source(&error).and_then(|cause|cause.downcast_ref::<native_tls::Error>()).map(ToString::to_string).unwrap_or_else(||"no TLS certificate diagnostic".to_owned());
        anyhow::anyhow!("PostgreSQL migration connection failed ({error}, SQLSTATE {}, {tls_error}); verify secret environment and TLS connectivity",error.code().map(|code|code.code()).unwrap_or("unavailable"))
    })?;
    let mut transaction = client
        .build_transaction()
        .isolation_level(IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()?;
    transaction.batch_execute("SET LOCAL statement_timeout='600000'; SET LOCAL idle_in_transaction_session_timeout='600000'; SET LOCAL TIME ZONE 'UTC'; SET LOCAL search_path=pg_catalog,public")?;
    let actual_read_only: String = transaction
        .query_one("SHOW transaction_read_only", &[])?
        .get(0);
    let actual_isolation: String = transaction
        .query_one("SHOW transaction_isolation", &[])?
        .get(0);
    ensure!(
        actual_read_only == "on" && actual_isolation == "repeatable read",
        "source transaction must actually be read-only and repeatable-read"
    );
    let snapshot_id: String = transaction
        .query_one("SELECT txid_current_snapshot()::text", &[])?
        .get(0);
    if let Some(parent) = directory.parent() {
        fs::create_dir_all(parent)?;
    }
    // Atomic create rejects a directory or symlink installed during acquisition.
    private_directory(directory)?;
    private_directory(&directory.join("operations"))?;
    let mut tables = serde_json::Map::new();
    for dataset in sources::DATASETS {
        check()?;
        let table = ingestion::table_name(dataset)?;
        let fields = columns(&mut transaction, table)?;
        ensure!(!fields.is_empty(), "source fact table {table} missing");
        let desired = ingestion::schema_columns(dataset)?;
        let expected: BTreeSet<_> = desired.keys().map(String::as_str).collect();
        let unmapped: Vec<_> = fields
            .iter()
            .filter(|field| !expected.contains(field.as_str()))
            .collect();
        ensure!(
            unmapped.is_empty(),
            "unmapped production columns in {table}: {unmapped:?}; review migration schema before copying"
        );
        let mut projection = Vec::new();
        let mut typed = Vec::new();
        let mut nulls = Vec::new();
        for (field, kind) in &desired {
            if !fields.contains(field) {
                nulls.push(field.clone());
                continue;
            }
            if field == "geometry" {
                projection
                    .push("encode(ST_AsBinary(geometry),'hex') AS geometry_wkb_hex".to_owned());
                projection.push("ST_SRID(geometry) AS geometry_srid".to_owned());
                typed.push("CAST(geometry_wkb_hex AS VARCHAR) geometry_wkb_hex".to_owned());
                typed.push("CAST(geometry_srid AS INTEGER) geometry_srid".to_owned());
            } else {
                let field = sources::identifier(field);
                projection.push(field.clone());
                typed.push(format!("CAST({field} AS {kind}) AS {field}"));
            }
        }
        ensure!(
            !nulls.iter().any(|field| field == "geometry"),
            "production point geometry column missing for {table}"
        );
        let expected_rows: i64 = transaction
            .query_one(
                &format!("SELECT count(*) FROM {}", sources::identifier(table)),
                &[],
            )?
            .get(0);
        let csv = directory.join(format!("{table}.csv.part"));
        let copy = format!(
            "COPY(SELECT {} FROM {}) TO STDOUT WITH(FORMAT CSV,HEADER,FORCE_QUOTE *)",
            projection.join(","),
            sources::identifier(table)
        );
        stream_copy(&mut transaction, &copy, &csv, check)?;
        let parquet = directory.join(format!("{table}.parquet"));
        let relation = format!(
            "read_csv({},header=true,all_varchar=true,normalize_names=false,ignore_errors=false,strict_mode=true,allow_quoted_nulls=false,nullstr='',buffer_size=4194304,maximum_line_size=262144)",
            sources::literal(csv.to_str().context("CSV path must be UTF-8")?)
        );
        let native = format!(
            "COPY(SELECT {} FROM {relation}) TO {}(FORMAT PARQUET,COMPRESSION ZSTD)",
            typed.join(","),
            sources::literal(parquet.to_str().context("Parquet path must be UTF-8")?)
        );
        db.with_session(|session| session.guarded(check, || session.execute(&native, &[])))?;
        secure_native_file(&parquet)?;
        let observed = db.query(
            &format!(
                "DESCRIBE SELECT * FROM read_parquet({})",
                sources::literal(parquet.to_str().context("Parquet path must be UTF-8")?)
            ),
            &[],
        )?;
        let physical: BTreeMap<_, _> = observed
            .iter()
            .map(|v| {
                (
                    v["column_name"].as_str().unwrap_or(""),
                    v["column_type"].as_str().unwrap_or(""),
                )
            })
            .collect();
        let count = db.query(
            &format!(
                "SELECT count(*) n FROM read_parquet({})",
                sources::literal(parquet.to_str().context("Parquet path must be UTF-8")?)
            ),
            &[],
        )?[0]["n"]
            .clone();
        ensure!(
            count.as_i64() == Some(expected_rows),
            "PostgreSQL/native row count mismatch for {table}"
        );
        tables.insert(table.to_owned(),json!({"file":format!("{table}.parquet"),"rows":count,"bytes":parquet.metadata()?.len(),"sha256":sources::file_sha256_guarded(&parquet,check)?,"columns":physical,"null_columns":nulls}));
        fs::remove_file(csv)?;
    }
    let mut ops = serde_json::Map::new();
    for table in [
        "scheduled_jobs",
        "job_executions",
        "data_deletion_logs",
        "export_jobs",
        "ingestion_checkpoints",
    ] {
        check()?;
        ops.insert(
            table.to_owned(),
            operations(&mut transaction, table, directory, check)?,
        );
    }
    let boundaries = boundaries(&mut transaction, directory, check)?;
    check()?;
    transaction.rollback()?;
    let manifest = json!({"format_version":1,"source_kind":"postgresql_repeatable_read","production_snapshot":true,"snapshot_id":snapshot_id,"captured_at":chrono::Utc::now().to_rfc3339(),"source_transaction_read_only":actual_read_only=="on","source_isolation":actual_isolation,"source_credentials_recorded":false,"tables":tables,"operations":ops,"boundaries":boundaries});
    write_manifest(&directory.join("manifest.json"), &manifest)?;
    Ok(manifest)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    #[test]
    fn snapshot_artifacts_are_private_without_inheriting_the_callers_umask() {
        use std::os::unix::fs::PermissionsExt;
        let scratch = tempfile::tempdir().unwrap();
        let root = scratch.path().join("snapshot");
        private_directory(&root).unwrap();
        let operations = root.join("operations");
        private_directory(&operations).unwrap();
        let file = operations.join("jobs.ndjson");
        private_file(&file).unwrap();
        let parquet = root.join("native.parquet");
        fs::write(&parquet, "native fixture").unwrap();
        fs::set_permissions(&parquet, fs::Permissions::from_mode(0o644)).unwrap();
        secure_native_file(&parquet).unwrap();
        for directory in [&root, &operations] {
            assert_eq!(
                directory.metadata().unwrap().permissions().mode() & 0o777,
                0o700
            );
        }
        for file in [&file, &parquet] {
            assert_eq!(file.metadata().unwrap().permissions().mode() & 0o777, 0o600);
        }
        assert!(private_directory(&root).is_err());
        assert!(private_file(&file).is_err());
    }
    #[test]
    fn postgres_copy_csv_distinguishes_quoted_empty_text_and_null() {
        let library = crate::test_support::library();
        if !library.is_file() {
            return;
        }
        let temp = tempfile::tempdir().unwrap();
        let db = Database::open(
            &temp.path().join("copy.duckdb"),
            &library,
            "256MB",
            1,
            &temp.path().join("spill"),
        )
        .unwrap();
        let csv = temp.path().join("copy.csv");
        fs::write(
            &csv,
            b"text_field,nullable\n\"\",\n\"UNKNOWN\",\"literal\"\n",
        )
        .unwrap();
        let rows=db.query(&format!("SELECT * FROM read_csv({},header=true,all_varchar=true,allow_quoted_nulls=false,nullstr='')",sources::literal(csv.to_str().unwrap())),&[]).unwrap();
        assert_eq!(rows[0]["text_field"], "");
        assert!(rows[0]["nullable"].is_null());
        assert_eq!(rows[1]["text_field"], "UNKNOWN");
    }
}

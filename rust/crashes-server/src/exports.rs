//! Schema-v1 exports with frozen geometry, one read transaction and private artifacts.

use crate::{
    db::{Database, sql_literal},
    queries::{LocationRequest, Selection, selected_crashes},
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs::{File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

/// Exact public columns/order from the deployed ff1503e schema-v1 export contract.
pub fn export_columns(dataset: &str) -> Result<&'static [&'static str]> {
    Ok(match dataset {
        "crashes" => &[
            "crash_record_id",
            "crash_date",
            "crash_date_est_i",
            "posted_speed_limit",
            "traffic_control_device",
            "device_condition",
            "weather_condition",
            "lighting_condition",
            "street_no",
            "street_direction",
            "street_name",
            "sec_contributory_cause",
            "street_direction_2",
            "street_name_2",
            "crash_type",
            "crash_record_id_original",
            "crash_date_original",
            "latitude",
            "longitude",
            "geometry",
            "beat_of_occurrence",
            "photos_taken_i",
            "statements_taken_i",
            "damage",
            "date_police_notified",
            "prim_contributory_cause",
            "work_zone_i",
            "work_zone_type",
            "workers_present_i",
            "injuries_total",
            "injuries_fatal",
            "injuries_incapacitating",
            "injuries_non_incapacitating",
            "injuries_reported_not_evident",
            "injuries_no_indication",
            "injuries_unknown",
            "hit_and_run_i",
            "dooring_i",
            "intersection_related_i",
            "not_right_of_way_i",
            "lane_cnt",
            "alignment",
            "roadway_surface_cond",
            "road_defect",
            "report_type",
            "most_severe_injury",
        ],
        "people" => &[
            "crash_record_id",
            "person_id",
            "crash_date",
            "vehicle_id",
            "person_type",
            "age",
            "sex",
            "safety_equipment",
            "airbag_deployed",
            "ejection",
            "injury_classification",
            "hospital",
            "ems_agency",
            "ems_unit",
            "area_00_i",
            "area_01_i",
            "area_02_i",
            "area_03_i",
            "area_04_i",
            "area_05_i",
            "area_06_i",
            "area_07_i",
            "area_08_i",
            "area_09_i",
            "area_10_i",
            "area_11_i",
            "area_12_i",
            "drivers_license_state",
            "drivers_license_class",
            "driver_action",
            "driver_vision",
            "physical_condition",
            "pedpedal_action",
            "pedpedal_visibility",
            "pedpedal_location",
            "bac_result",
            "bac_result_value",
            "cell_phone_use",
        ],
        "vehicles" => &[
            "crash_unit_id",
            "crash_record_id",
            "unit_no",
            "crash_date",
            "unit_type",
            "num_passengers",
            "vehicle_id",
            "cmv_id",
            "make",
            "model",
            "lic_plate_state",
            "vehicle_year",
            "vehicle_defect",
            "vehicle_type",
            "vehicle_use",
            "travel_direction",
            "maneuver",
            "towed_i",
            "fire_i",
            "hazmat_placard_i",
            "hazmat_name",
            "hazmat_present_i",
            "occupant_cnt",
            "first_contact_point",
        ],
        "vision_zero" => &[
            "person_id",
            "rd_no",
            "crash_date",
            "crash_location",
            "victim",
            "crash_circumstances",
            "longitude",
            "latitude",
            "geometry",
            "geocoded_column",
        ],
        _ => anyhow::bail!("unsupported export dataset"),
    })
}

/// Finite rows per dataset, cumulative uncompressed bytes and wall clock budget.
#[derive(Debug, Clone)]
pub struct ExportLimits {
    pub max_rows: u64,
    pub max_bytes: u64,
    pub timeout_seconds: u64,
}

impl Default for ExportLimits {
    fn default() -> Self {
        Self {
            max_rows: 10_000_000,
            max_bytes: 1_073_741_824,
            timeout_seconds: 300,
        }
    }
}

/// A verified artifact ready for upload. The queue pointer is published separately.
#[derive(Debug)]
pub struct ExportArtifact {
    pub path: PathBuf,
    pub manifest: Value,
    pub sha256: String,
    pub bytes: u64,
}

fn dataset_query(dataset: &str, selection: &Selection, limit: u64) -> Result<String> {
    let columns = export_columns(dataset)?
        .iter()
        .map(|column| {
            if *column == "geometry" {
                "ST_AsText(t.geometry) AS geometry".to_string()
            } else {
                format!("t.\"{column}\"")
            }
        })
        .collect::<Vec<_>>()
        .join(", ");
    let query = match dataset {
        "crashes" => format!(
            "SELECT {columns} FROM ({}) t ORDER BY t.crash_record_id",
            selection.sql
        ),
        "vision_zero" => format!(
            "SELECT {columns} FROM vision_zero_fatalities t WHERE t.geometry IS NOT NULL AND {} AND {} ORDER BY t.person_id",
            selection.spatial_sql, selection.date_sql
        ),
        "people" | "vehicles" => {
            let (table, identity) = if dataset == "people" {
                ("crash_people", "t.person_id,t.crash_record_id")
            } else {
                ("crash_vehicles", "t.crash_unit_id")
            };
            format!(
                "WITH selected AS MATERIALIZED ({}) SELECT {columns} FROM {table} t JOIN selected s ON s.crash_record_id=t.crash_record_id ORDER BY {identity}",
                selection.sql
            )
        }
        _ => anyhow::bail!("unsupported export dataset"),
    };
    Ok(format!("SELECT * FROM ({query}) export_rows LIMIT {limit}"))
}

/// Hash files with fixed memory instead of buffering artifacts in the application.
pub fn file_sha256(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn directory_bytes(directory: &Path) -> Result<u64> {
    let mut total = 0u64;
    for entry in std::fs::read_dir(directory)? {
        let metadata = entry?.metadata()?;
        ensure!(
            metadata.is_file(),
            "unexpected non-file in private export directory"
        );
        total = total
            .checked_add(metadata.len())
            .context("export disk bytes overflow")?;
    }
    Ok(total)
}

fn inspect_csv(
    path: &Path,
    dataset: &str,
    limits: &ExportLimits,
    check: &dyn Fn() -> Result<()>,
) -> Result<Value> {
    let bytes = path.metadata()?.len();
    ensure!(bytes <= limits.max_bytes, "export exceeds byte limit");
    let mut reader = csv::ReaderBuilder::new().from_path(path)?;
    ensure!(
        reader
            .headers()?
            .iter()
            .eq(export_columns(dataset)?.iter().copied()),
        "export CSV schema differs from version 1"
    );
    let mut count = 0u64;
    for row in reader.byte_records() {
        row?;
        count += 1;
        ensure!(count <= limits.max_rows, "export exceeds row limit");
        if count.is_multiple_of(2000) {
            check()?;
        }
    }
    check()?;
    Ok(json!({"rows":count,"bytes":bytes,"sha256":file_sha256(path)?}))
}

/// Generate into a new attempt directory, then upload and fence publication in SQLite.
///
/// `check` must use only control state: analytical connection admission remains held
/// during native COPY. The watchdog checks it every 100 ms and interrupts native SQL.
/// A volume quota remains necessary for an absolute disk ceiling between samples.
pub fn generate_export(
    database: &Database,
    request: &LocationRequest,
    datasets: &[String],
    directory: &Path,
    limits: &ExportLimits,
    check: &(dyn Fn() -> Result<()> + Sync),
    data_version: Option<&str>,
) -> Result<ExportArtifact> {
    ensure!(
        limits.max_rows > 0
            && limits.max_rows < u64::MAX
            && limits.max_bytes > 0
            && limits.timeout_seconds > 0,
        "export limits must be positive"
    );
    ensure!(
        !datasets.is_empty() && datasets.len() <= 4,
        "choose 1..4 export datasets"
    );
    let mut unique = HashSet::new();
    for dataset in datasets {
        export_columns(dataset)?;
        ensure!(unique.insert(dataset), "duplicate export dataset");
    }
    // Resolution happens before transaction admission. Named boundaries must have
    // been frozen in the durable submission, otherwise a layer replacement could
    // silently change a queued request's meaning.
    ensure!(
        request.place_type.is_none() || request.resolved_area.is_some(),
        "named export area must be frozen at submission"
    );
    let selection = selected_crashes(database, request)?;
    ensure!(!directory.exists(), "attempt directory already exists");
    std::fs::create_dir_all(directory)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700))?;
    }
    let started = Instant::now();
    let operation = || -> Result<ExportArtifact> {
        let native_check = || -> Result<()> {
            ensure!(
                started.elapsed() < Duration::from_secs(limits.timeout_seconds),
                "export time limit exceeded"
            );
            ensure!(
                directory_bytes(directory)? <= limits.max_bytes,
                "export exceeds total byte limit"
            );
            check()
        };
        let mut manifest = json!({
            "schema_version":1,"filters":request,"resolved_area":selection.query_area,
            "generated_at":chrono::Utc::now().to_rfc3339(),"datasets":{},
            "data_version":data_version,"consistency":"DuckDB single caller-owned read transaction",
            "geometry":{"encoding":"WKT","crs":"EPSG:4326","axis_order":"longitude,latitude"},
            "null_serialization":"empty CSV field"
        });
        database.transaction(|session| {
            session.guarded(native_check, || {
                native_check()?;
                manifest["engine_version"] = session
                    .query("SELECT version() AS version", &[])?
                    .first()
                    .and_then(|row| row.get("version"))
                    .cloned()
                    .unwrap_or(Value::Null);
                let has_revision=!session.query("SELECT 1 FROM information_schema.tables WHERE table_name='rust_mutations' AND table_schema='main'",&[])?.is_empty();
                if has_revision {
                    let revision=session.query("SELECT id,CAST(committed_at AS VARCHAR) AS committed_at FROM rust_mutations ORDER BY rust_mutations.committed_at DESC,id DESC LIMIT 1",&[])?;
                    if let Some(revision)=revision.first() {
                        manifest["data_version"]=revision["id"].clone();
                        manifest["publication_provenance"]=revision.clone();
                    }
                }
                for dataset in datasets {
                    native_check()?;
                    let path = directory.join(format!("{dataset}.csv.partial"));
                    let query = dataset_query(dataset, &selection, limits.max_rows + 1)?;
                    let copy = format!(
                        "COPY ({query}) TO {} (FORMAT CSV, HEADER TRUE, NULL '')",
                        sql_literal(path.to_str().context("export path must be UTF-8")?)
                    );
                    session.execute(&copy, &selection.params)?;
                    let metadata = inspect_csv(&path, dataset, limits, &native_check)?;
                    manifest["datasets"][dataset] = metadata;
                }
                native_check()
            })
        })?;
        native_check()?;
        let manifest_path = directory.join("manifest.json");
        let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&manifest_path)?;
        output.write_all(&manifest_bytes)?;
        output.sync_all()?;
        drop(output);
        let artifact_path = if datasets.len() == 1 {
            directory.join(format!("{}.csv", datasets[0]))
        } else {
            let archive_partial = directory.join("location-report.zip.partial");
            let mut archive = ZipWriter::new(
                OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&archive_partial)?,
            );
            let options = SimpleFileOptions::default()
                .compression_method(CompressionMethod::Deflated)
                .compression_level(Some(6));
            let mut copied = 0u64;
            let mut buffer = [0u8; 65536];
            for dataset in datasets {
                check()?;
                archive.start_file(format!("{dataset}.csv"), options)?;
                let mut input = File::open(directory.join(format!("{dataset}.csv.partial")))?;
                loop {
                    let read = input.read(&mut buffer)?;
                    if read == 0 {
                        break;
                    }
                    archive.write_all(&buffer[..read])?;
                    copied += read as u64;
                    ensure!(copied <= limits.max_bytes, "export exceeds byte limit");
                    ensure!(
                        started.elapsed() < Duration::from_secs(limits.timeout_seconds),
                        "export time limit exceeded"
                    );
                    check()?;
                }
            }
            archive.start_file("manifest.json", options)?;
            archive.write_all(&manifest_bytes)?;
            archive.finish()?.sync_all()?;
            ensure!(
                archive_partial.metadata()?.len() <= limits.max_bytes,
                "export archive exceeds byte limit"
            );
            let archive_path = directory.join("location-report.zip");
            std::fs::rename(&archive_partial, &archive_path)?;
            archive_path
        };
        for dataset in datasets {
            let source = directory.join(format!("{dataset}.csv.partial"));
            File::open(&source)?.sync_all()?;
            std::fs::rename(&source, directory.join(format!("{dataset}.csv")))?;
        }
        check()?;
        let bytes = artifact_path.metadata()?.len();
        let sha256 = file_sha256(&artifact_path)?;
        // Directory fsync makes the artifact rename durable before SQLite publishes.
        #[cfg(unix)]
        File::open(directory)?.sync_all()?;
        Ok(ExportArtifact {
            path: artifact_path,
            manifest,
            sha256,
            bytes,
        })
    };
    match operation() {
        Ok(artifact) => Ok(artifact),
        Err(error) => {
            // Only this function's newly created private directory is removed.
            let _ = std::fs::remove_dir_all(directory);
            Err(error)
        }
    }
}

/// Verify the final artifact immediately before publishing or signing a download.
pub fn verify_artifact(path: &Path, expected_bytes: u64, expected_sha256: &str) -> Result<()> {
    ensure!(
        path.is_file() && path.metadata()?.len() == expected_bytes,
        "artifact bytes do not match manifest"
    );
    ensure!(
        file_sha256(path)? == expected_sha256,
        "artifact checksum does not match manifest"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn export_identity_and_geometry_columns_match_deployed_contract() -> Result<()> {
        assert_eq!(export_columns("crashes")?.len(), 46);
        assert_eq!(export_columns("people")?.len(), 38);
        assert_eq!(export_columns("vehicles")?.len(), 24);
        assert_eq!(export_columns("vision_zero")?.len(), 10);
        assert_eq!(export_columns("crashes")?[19], "geometry");
        Ok(())
    }
    #[test]
    fn artifact_verification_rejects_corrupt_bytes() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("export.csv");
        std::fs::write(&path, b"header\nrecord\n")?;
        let digest = file_sha256(&path)?;
        std::fs::write(&path, b"header\nmutate\n")?;
        assert!(verify_artifact(&path, 14, &digest).is_err());
        Ok(())
    }

    fn native_fixture(directory: &Path) -> Result<Option<Database>> {
        let library = crate::test_support::library();
        let database = Database::open(
            &directory.join("export.duckdb"),
            &library,
            "256MB",
            1,
            &directory.join("spill"),
        )?;
        crate::test_support::load_spatial(&database);
        for (dataset, table) in [
            ("crashes", "crashes"),
            ("people", "crash_people"),
            ("vehicles", "crash_vehicles"),
            ("fatalities", "vision_zero_fatalities"),
        ] {
            let columns = crate::ingestion::schema_columns(dataset)?;
            let definitions = columns
                .iter()
                .map(|(column, kind)| format!("\"{column}\" {kind}"))
                .collect::<Vec<_>>()
                .join(",");
            database.execute(&format!("CREATE TABLE {table} ({definitions})"), &[])?;
        }
        database.execute("INSERT INTO crashes(crash_record_id,crash_date,latitude,longitude,geometry) VALUES ('a','2024-01-15',41.75,-87.65,ST_Point(-87.65,41.75))",&[])?;
        database.execute("INSERT INTO crash_people(crash_record_id,person_id,crash_date) VALUES ('a','p2',NULL),('a','p1','2023-01-01')",&[])?;
        database.execute(
            "INSERT INTO crash_vehicles(crash_record_id,crash_unit_id) VALUES ('a','v1')",
            &[],
        )?;
        database.execute("INSERT INTO vision_zero_fatalities(person_id,crash_date,latitude,longitude,geometry) VALUES ('f1','2024-01-10',41.75,-87.65,ST_Point(-87.65,41.75)),('f2','2023-01-10',41.75,-87.65,ST_Point(-87.65,41.75))",&[])?;
        Ok(Some(database))
    }

    fn request() -> LocationRequest {
        LocationRequest {
            start_date: Some("2024-01-01".into()),
            end_date: Some("2024-01-31".into()),
            polygon: Some(vec![
                [-87.7, 41.7],
                [-87.6, 41.7],
                [-87.6, 41.8],
                [-87.7, 41.8],
            ]),
            ..LocationRequest::default()
        }
    }

    #[test]
    fn native_zip_exports_preserve_schema_parent_dates_nulls_and_wkt() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let Some(database) = native_fixture(directory.path())? else {
            return Ok(());
        };
        let output = directory.path().join("attempt");
        database.transaction(|session| {
            crate::mutations::record(
                session,
                "export.fixture",
                &json!({"source":"native fixture"}),
            )
        })?;
        let revision =
            crate::mutations::revision(&database)?.context("fixture publication revision")?;
        let artifact = generate_export(
            &database,
            &request(),
            &[
                "crashes".into(),
                "people".into(),
                "vehicles".into(),
                "vision_zero".into(),
            ],
            &output,
            &ExportLimits::default(),
            &|| Ok(()),
            Some("fixture-v1"),
        )?;
        assert_eq!(artifact.manifest["datasets"]["people"]["rows"], 2);
        assert_eq!(artifact.manifest["datasets"]["vision_zero"]["rows"], 1);
        assert_eq!(artifact.manifest["data_version"], revision);
        assert!(artifact.manifest["publication_provenance"]["committed_at"].is_string());
        let mut reader = csv::Reader::from_path(output.join("crashes.csv"))?;
        let row = reader.records().next().context("missing crash")??;
        assert_eq!(&row[19], "POINT (-87.65 41.75)");
        assert_eq!(&row[10], "");
        let mut archive = zip::ZipArchive::new(File::open(artifact.path)?)?;
        let archived: Value = serde_json::from_reader(archive.by_name("manifest.json")?)?;
        assert_eq!(archived, artifact.manifest);
        Ok(())
    }

    #[test]
    fn native_export_row_bound_and_cancellation_remove_partial_directory() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let Some(database) = native_fixture(directory.path())? else {
            return Ok(());
        };
        let output = directory.path().join("attempt");
        let limits = ExportLimits {
            max_rows: 1,
            ..ExportLimits::default()
        };
        assert!(
            generate_export(
                &database,
                &request(),
                &["people".into()],
                &output,
                &limits,
                &|| Ok(()),
                None
            )
            .is_err()
        );
        assert!(!output.exists());
        let limits = ExportLimits {
            max_bytes: 100,
            ..ExportLimits::default()
        };
        assert!(
            generate_export(
                &database,
                &request(),
                &["crashes".into()],
                &output,
                &limits,
                &|| Ok(()),
                None
            )
            .is_err()
        );
        assert!(!output.exists());
        let cancelled = generate_export(
            &database,
            &request(),
            &["crashes".into()],
            &output,
            &ExportLimits::default(),
            &|| anyhow::bail!("cancelled"),
            None,
        );
        assert!(cancelled.is_err());
        assert!(!output.exists());
        Ok(())
    }
}

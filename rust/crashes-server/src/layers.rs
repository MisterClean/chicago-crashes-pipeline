//! Exact boundary restoration and bounded, safe spatial upload preparation.
use crate::{
    db::{Database, Session},
    sources::{file_sha256, literal},
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, File},
    io::Read,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

fn count(session: &Session, sql: &str) -> Result<u64> {
    session
        .query(sql, &[])?
        .first()
        .and_then(|v| v["n"].as_u64())
        .context("expected boundary count")
}
const LAYER_FIELDS: [&str; 13] = [
    "id",
    "name",
    "slug",
    "description",
    "geometry_type",
    "srid",
    "feature_count",
    "original_filename",
    "is_active",
    "label_field",
    "sort_type",
    "created_at",
    "updated_at",
];
fn create_tables(session: &Session) -> Result<()> {
    session.execute("CREATE TABLE IF NOT EXISTS spatial_layers(id BIGINT PRIMARY KEY,name VARCHAR,slug VARCHAR,description VARCHAR,geometry_type VARCHAR,srid INTEGER,feature_count BIGINT,original_filename VARCHAR,is_active BOOLEAN,label_field VARCHAR,sort_type VARCHAR,created_at TIMESTAMP,updated_at TIMESTAMP)",&[])?;
    session.execute("CREATE TABLE IF NOT EXISTS spatial_layer_features(id BIGINT PRIMARY KEY,layer_id BIGINT,properties JSON,geometry GEOMETRY,created_at TIMESTAMP,updated_at TIMESTAMP)",&[])
}
/// Create the empty upload catalog for a new portal bootstrap, preserving existing layers.
pub fn initialize_catalog(db: &Database) -> Result<()> {
    db.transaction(create_tables)
}
/// Restore IDs, labels, ordering, properties, timestamps and complete WKB geometry.
pub fn import_layer_snapshot(db: &Database, directory: &Path) -> Result<Value> {
    let manifest: Value = serde_json::from_reader(File::open(directory.join("manifest.json"))?)?;
    ensure!(
        manifest["format_version"] == 1,
        "unsupported boundary snapshot format"
    );
    let root = directory.canonicalize()?;
    let feature_file = root
        .join(
            manifest["features_file"]
                .as_str()
                .context("features filename missing")?,
        )
        .canonicalize()?;
    ensure!(
        feature_file.starts_with(&root),
        "features path escapes snapshot directory"
    );
    ensure!(
        manifest["features_sha256"] == file_sha256(&feature_file)?,
        "boundary checksum mismatch"
    );
    if let Some(bytes) = manifest["features_bytes"].as_u64() {
        ensure!(
            feature_file.metadata()?.len() == bytes,
            "boundary size mismatch"
        );
    }
    let layers = manifest["layers"]
        .as_array()
        .context("layer metadata missing")?;
    let path = literal(
        feature_file
            .to_str()
            .context("boundary path must be UTF-8")?,
    );
    let relation = format!(
        "read_json({path},columns={{id:'BIGINT',layer_id:'BIGINT',properties_json:'VARCHAR',geometry_wkb_hex:'VARCHAR',srid:'INTEGER',created_at:'TIMESTAMP',updated_at:'TIMESTAMP'}},format='newline_delimited')"
    );
    db.transaction(|session|{
        ensure!(count(session,"SELECT count(*) n FROM information_schema.tables WHERE table_schema='main' AND table_name IN ('spatial_layers','spatial_layer_features')")?==0,"boundary tables exist; restore requires fresh target");
        create_tables(session)?;
        for layer in layers{
            ensure!(layer["srid"]==4326,"boundary metadata must declare EPSG:4326");
            let values:Vec<_>=LAYER_FIELDS.iter().map(|field|layer[*field].clone()).collect();
            session.execute("INSERT INTO spatial_layers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",&values)?;
        }
        ensure!(count(session,&format!("SELECT count(*) n FROM {relation} WHERE srid IS NULL OR srid<>4326"))?==0,"snapshot geometry must be normalized to EPSG:4326");
        session.execute(&format!("INSERT INTO spatial_layer_features SELECT id,layer_id,CAST(properties_json AS JSON),ST_GeomFromHEXWKB(geometry_wkb_hex),created_at,updated_at FROM {relation}"),&[])?;
        let features=count(session,"SELECT count(*) n FROM spatial_layer_features")?;
        ensure!(manifest["feature_count"].as_u64()==Some(features),"boundary feature count mismatch");
        ensure!(count(session,"SELECT count(*) n FROM spatial_layer_features f LEFT JOIN spatial_layers l ON l.id=f.layer_id WHERE f.geometry IS NULL OR ST_IsEmpty(f.geometry) OR NOT ST_IsValid(f.geometry) OR l.id IS NULL")?==0,"boundary geometry validity or parent mismatch");
        // SRID tags alone do not validate degree coordinates. Reject invalid WGS84 extents.
        ensure!(count(session,"SELECT count(*) n FROM spatial_layer_features WHERE ST_XMin(geometry)<-180 OR ST_XMax(geometry)>180 OR ST_YMin(geometry)<-90 OR ST_YMax(geometry)>90")?==0,"boundary coordinates outside WGS84 extent");
        ensure!(count(session,"SELECT count(*) n FROM spatial_layers l LEFT JOIN(SELECT layer_id,count(*) n FROM spatial_layer_features GROUP BY layer_id)f ON l.id=f.layer_id WHERE l.feature_count IS NULL OR l.feature_count<>coalesce(f.n,0)")?==0,"boundary metadata counts do not reconcile");
        let receipt=json!({"layers":layers.len(),"features":features,"features_sha256":manifest["features_sha256"],"feature_timestamps_preserved":manifest["feature_timestamps_preserved"],"snapshot":root});
        crate::mutations::record(session,"layers.snapshot_import",&receipt)?;
        Ok(receipt)
    })
}

const MAX_UPLOAD_BYTES: u64 = 64 * 1024 * 1024;
const MAX_EXPANDED_BYTES: u64 = 256 * 1024 * 1024;
static CONVERSION_PERMIT: Mutex<()> = Mutex::new(());
struct ConversionLimits {
    timeout: Duration,
    output_bytes: u64,
    stderr_bytes: u64,
}

/// The converter never inherits a terminal or unbounded diagnostic buffer. A
/// separate process group lets timeout/error cleanup also reap pipe-owning children.
fn bounded_conversion(
    executable: &Path,
    input: &Path,
    output: &Path,
    limits: &ConversionLimits,
    permit: &Mutex<()>,
) -> Result<()> {
    let _permit = permit
        .try_lock()
        .map_err(|_| anyhow::anyhow!("another spatial conversion is active; retry later"))?;
    let mut command = Command::new(executable);
    command
        .args(["-f", "GeoJSON"])
        .arg(output)
        .arg(input)
        .args(["-t_srs", "EPSG:4326", "-lco", "RFC7946=YES"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .env("GDAL_CACHEMAX", "16")
        .env("GDAL_NUM_THREADS", "1")
        .env("OMP_NUM_THREADS", "1");
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let output_bytes = limits.output_bytes;
        // SAFETY: the post-fork callback calls only async-signal-safe POSIX
        // functions, without locks, allocation, or access to mutable parent state.
        unsafe {
            command.pre_exec(move || {
                if libc::setpgid(0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                let file = libc::rlimit {
                    rlim_cur: output_bytes as libc::rlim_t,
                    rlim_max: output_bytes as libc::rlim_t,
                };
                let cpu = libc::rlimit {
                    rlim_cur: 30,
                    rlim_max: 30,
                };
                if libc::setrlimit(libc::RLIMIT_FSIZE, &file) != 0
                    || libc::setrlimit(libc::RLIMIT_CPU, &cpu) != 0
                {
                    return Err(std::io::Error::last_os_error());
                }
                #[cfg(target_os = "linux")]
                {
                    let memory = libc::rlimit {
                        rlim_cur: 512 * 1024 * 1024,
                        rlim_max: 512 * 1024 * 1024,
                    };
                    if libc::setrlimit(libc::RLIMIT_AS, &memory) != 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
    }
    let mut child = command
        .spawn()
        .context("ogr2ogr is required for spatial uploads")?;
    let stderr = child
        .stderr
        .take()
        .context("converter stderr pipe missing")?;
    let exceeded = AtomicBool::new(false);
    let result = std::thread::scope(|scope| -> Result<()> {
        let diagnostics = scope.spawn(|| -> std::io::Result<Vec<u8>> {
            let mut bytes = Vec::new();
            stderr
                .take(limits.stderr_bytes + 1)
                .read_to_end(&mut bytes)?;
            exceeded.store(bytes.len() as u64 > limits.stderr_bytes, Ordering::Release);
            bytes.truncate(limits.stderr_bytes as usize);
            Ok(bytes)
        });
        let started = Instant::now();
        let outcome = (|| {
            loop {
                ensure!(
                    !exceeded.load(Ordering::Acquire),
                    "spatial converter diagnostics exceed limit"
                );
                ensure!(
                    started.elapsed() < limits.timeout,
                    "spatial conversion deadline exceeded"
                );
                match output.metadata() {
                    Ok(metadata) => ensure!(
                        metadata.len() <= limits.output_bytes,
                        "converted geometry exceeds size limit"
                    ),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
                if let Some(status) = child.try_wait()? {
                    return Ok(status);
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        })();
        // Always terminate the process group, including descendants left behind
        // after the converter exits, before joining its diagnostic reader.
        #[cfg(unix)]
        // SAFETY: child.id is the process-group ID established before exec. A
        // negative PID targets only that group; no shell command is constructed.
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
        let _ = child.kill();
        let _ = child.wait();
        let diagnostics = diagnostics
            .join()
            .map_err(|_| anyhow::anyhow!("converter diagnostic reader panicked"))??;
        let status = outcome?;
        ensure!(
            !exceeded.load(Ordering::Acquire),
            "spatial converter diagnostics exceed limit"
        );
        ensure!(
            status.success(),
            "spatial conversion failed: {}",
            String::from_utf8_lossy(&diagnostics)
        );
        ensure!(
            output.metadata()?.len() <= limits.output_bytes,
            "converted geometry exceeds size limit"
        );
        Ok(())
    });
    if result.is_err() {
        let _ = fs::remove_file(output);
    }
    result
}
/// Owns extraction/conversion scratch until the owner completes ingestion.
pub struct PreparedUpload {
    pub _directory: tempfile::TempDir,
    pub geojson: PathBuf,
}

fn safe_member(name: &str) -> Result<PathBuf> {
    ensure!(
        !name.contains('\\') && !name.contains(':') && !name.contains('\0'),
        "unsafe archive member name"
    );
    let path = Path::new(name);
    ensure!(
        !path.is_absolute() && path.components().all(|c| matches!(c, Component::Normal(_))),
        "archive path traversal rejected"
    );
    Ok(path.to_owned())
}
/// Extract only one complete shapefile set, refusing links, traversal, duplicate
/// names, zip bombs and missing CRS. Conversion actually transforms CRS to WGS84.
pub fn prepare_upload(path: &Path, filename: &str) -> Result<PreparedUpload> {
    ensure!(
        path.metadata()?.len() <= MAX_UPLOAD_BYTES,
        "spatial upload exceeds 64MiB"
    );
    let directory = tempfile::tempdir()?;
    let extension = Path::new(filename)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let input = if extension == "zip" {
        let mut archive = zip::ZipArchive::new(File::open(path)?)?;
        ensure!(archive.len() <= 128, "archive has too many entries");
        let mut expanded = 0_u64;
        let mut members = BTreeMap::new();
        for index in 0..archive.len() {
            let mut entry = archive.by_index(index)?;
            if entry.is_dir() {
                continue;
            }
            let name = entry
                .name()
                .context("archive member name cannot be decoded")?;
            let member = safe_member(&name)?;
            if let Some(mode) = entry.unix_mode() {
                ensure!(mode & 0o170000 != 0o120000, "archive symlinks rejected");
            }
            expanded = expanded
                .checked_add(entry.size())
                .context("archive size overflow")?;
            ensure!(
                expanded <= MAX_EXPANDED_BYTES,
                "expanded archive exceeds 256MiB"
            );
            ensure!(
                entry.size() <= MAX_UPLOAD_BYTES
                    && entry.size()
                        <= entry
                            .compressed_size()
                            .saturating_mul(500)
                            .saturating_add(1048576),
                "archive compression ratio exceeds limit"
            );
            let key = member.to_string_lossy().to_ascii_lowercase();
            ensure!(!members.contains_key(&key), "duplicate archive member");
            let destination = directory.path().join(&member);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent)?;
            }
            let mut target = File::options()
                .write(true)
                .create_new(true)
                .open(&destination)?;
            let copied =
                std::io::copy(&mut entry.by_ref().take(MAX_UPLOAD_BYTES + 1), &mut target)?;
            ensure!(copied <= MAX_UPLOAD_BYTES, "archive member exceeds limit");
            members.insert(key, destination);
        }
        let shp: Vec<_> = members
            .keys()
            .filter(|name| name.ends_with(".shp"))
            .collect();
        ensure!(shp.len() == 1, "archive requires exactly one shapefile");
        let stem = shp[0]
            .strip_suffix(".shp")
            .context("shapefile name missing")?;
        for extension in ["shp", "shx", "dbf", "prj"] {
            ensure!(
                members.contains_key(&format!("{stem}.{extension}")),
                "archive missing required .{extension} component"
            );
        }
        members[shp[0]].clone()
    } else {
        ensure!(
            ["geojson", "json"].contains(&extension.as_str()),
            "spatial upload must be GeoJSON or shapefile ZIP"
        );
        let target = directory.path().join("input.geojson");
        fs::copy(path, &target)?;
        target
    };
    let output = directory.path().join("normalized.geojson");
    if extension != "zip" {
        let document: Value = serde_json::from_reader(File::open(&input)?)?;
        ensure!(
            document["type"] == "FeatureCollection",
            "GeoJSON must be a FeatureCollection"
        );
        let features = document["features"]
            .as_array()
            .context("GeoJSON FeatureCollection features array required")?;
        ensure!(
            !features.is_empty() && features.len() <= 100000,
            "upload requires 1..100000 features"
        );
        let declared = if let Some(crs) = document.get("crs").filter(|crs| !crs.is_null()) {
            Some(
                crs["properties"]["name"]
                    .as_str()
                    .context("invalid GeoJSON CRS declaration")?,
            )
        } else {
            None
        };
        let wgs84 = declared.is_none_or(|name| {
            matches!(
                name,
                "EPSG:4326"
                    | "urn:ogc:def:crs:OGC:1.3:CRS84"
                    | "urn:ogc:def:crs:EPSG::4326"
                    | "OGC:CRS84"
            )
        });
        if wgs84 {
            // RFC7946 already uses longitude/latitude WGS84. Native validation
            // preserves rings and multipart coordinates without a GDAL process.
            fs::rename(&input, &output)?;
            return Ok(PreparedUpload {
                _directory: directory,
                geojson: output,
            });
        }
    }
    bounded_conversion(
        Path::new("ogr2ogr"),
        &input,
        &output,
        &ConversionLimits {
            timeout: Duration::from_secs(30),
            output_bytes: MAX_EXPANDED_BYTES,
            stderr_bytes: 4096,
        },
        &CONVERSION_PERMIT,
    )?;
    Ok(PreparedUpload {
        _directory: directory,
        geojson: output,
    })
}

/// Build a native staging table from a normalized FeatureCollection. Multipart
/// coordinates and interior rings pass intact to the spatial extension.
fn stage_geojson(session: &Session, path: &Path) -> Result<u64> {
    let maximum_object_size = path.metadata()?.len().max(1048576);
    ensure!(
        maximum_object_size <= MAX_EXPANDED_BYTES,
        "upload object exceeds bound"
    );
    let path = literal(path.to_str().context("geometry path must be UTF-8")?);
    session.execute(&format!("CREATE TEMP TABLE _uploaded_features AS SELECT json_extract(feature,'$.properties') properties,ST_GeomFromGeoJSON(CAST(json_extract(feature,'$.geometry') AS VARCHAR)) geometry FROM(SELECT unnest(features) feature FROM read_json({path},columns={{features:'JSON[]'}},format='unstructured',maximum_object_size={maximum_object_size}))"),&[])?;
    let features = count(session, "SELECT count(*) n FROM _uploaded_features")?;
    ensure!(
        features > 0 && features <= 100000,
        "upload requires 1..100000 features"
    );
    ensure!(
        count(
            session,
            "SELECT count(*) n FROM _uploaded_features WHERE geometry IS NULL OR ST_IsEmpty(geometry) OR NOT ST_IsValid(geometry) OR ST_XMin(geometry)<-180 OR ST_XMax(geometry)>180 OR ST_YMin(geometry)<-90 OR ST_YMax(geometry)>90"
        )? == 0,
        "invalid upload geometry"
    );
    Ok(features)
}
/// Preview names and a bounded sample without publishing any metadata or shapes.
pub fn preview_upload(db: &Database, path: &Path) -> Result<Value> {
    db.transaction(|session|{
        let features=stage_geojson(session,path)?;
        let samples=session.query("SELECT properties FROM _uploaded_features LIMIT 100",&[])?;
        let mut fields:BTreeMap<String,Vec<Value>>=BTreeMap::new();
        for row in samples{let properties=if let Some(text)=row["properties"].as_str(){serde_json::from_str::<Value>(text)?}else{row["properties"].clone()};
            if let Some(properties)=properties.as_object(){for(name,value)in properties{let samples=fields.entry(name.clone()).or_default();if !value.is_null()&&samples.len()<3&&!samples.contains(value){samples.push(value.clone());}}}
        }
        let recommended=["name","NAME","Name","title","TITLE","label","LABEL"].iter().find(|name|fields.contains_key(**name)).map(|name|(*name).to_owned())
            .or_else(||fields.keys().find(|name|{let lower=name.to_lowercase();lower.contains("name")||lower.contains("_nm")||lower.ends_with("nm")}).cloned())
            .or_else(||fields.keys().find(|name|{let lower=name.to_lowercase();lower.contains("desc")||lower.contains("district")||lower.contains("community")||lower.contains("ward")}).cloned());
        session.execute("DROP TABLE _uploaded_features",&[])?;
        let fields:Vec<_>=fields.into_iter().map(|(name,samples)|json!({"suggested":recommended.as_deref()==Some(name.as_str()),"name":name,"sample_values":samples})).collect();
        Ok(json!({"feature_count":features,"fields":fields,"recommended_field":recommended,"srid":4326}))
    })
}
/// Atomically create or replace a layer; replacement retains its existing layer
/// identity and metadata, while new feature IDs advance beyond all stored IDs.
pub fn publish_upload_metadata(
    db: &Database,
    path: &Path,
    name: &str,
    label_field: Option<&str>,
    replace_layer: Option<i64>,
    metadata: &Value,
) -> Result<Value> {
    ensure!(
        !name.trim().is_empty() && name.len() <= 200,
        "layer name required, maximum 200 bytes"
    );
    db.transaction(|session|{
        create_tables(session)?;
        let features=stage_geojson(session,path)?;
        if let Some(field)=label_field{ensure!(count(session,&format!("SELECT count(*) n FROM _uploaded_features WHERE list_contains(json_keys(properties),{})",literal(field)))? > 0,"label field absent from upload");}
        let layer_id=if let Some(id)=replace_layer{
            ensure!(count(session,&format!("SELECT count(*) n FROM spatial_layers WHERE id={id}"))?==1,"replacement layer missing");
            id
        }else{
            let id=count(session,"SELECT coalesce(max(id),0)::BIGINT+1 n FROM spatial_layers")? as i64;
            let slug=format!("uploaded-{id}");
            session.execute("INSERT INTO spatial_layers VALUES(?,?,?,NULL,'GEOMETRY',4326,?,NULL,true,?,'alphabetic',current_timestamp,current_timestamp)",&[json!(id),json!(name),json!(slug),json!(features),json!(label_field)])?;
            id
        };
        let first_id=count(session,"SELECT coalesce(max(id),0)::BIGINT n FROM spatial_layer_features")?;
        if replace_layer.is_some(){session.execute("DELETE FROM spatial_layer_features WHERE layer_id=?",&[json!(layer_id)])?;session.execute("UPDATE spatial_layers SET feature_count=?,updated_at=current_timestamp WHERE id=?",&[json!(features),json!(layer_id)])?;}
        session.execute(&format!("INSERT INTO spatial_layer_features SELECT {first_id}+row_number() OVER(),{layer_id},properties,geometry,current_timestamp,current_timestamp FROM _uploaded_features"),&[])?;
        session.execute("DROP TABLE _uploaded_features",&[])?;
        for field in ["description","sort_type","original_filename"]{
            if let Some(value)=metadata.get(field){
                if field=="sort_type"{ensure!(matches!(value.as_str(),Some("alphabetic"|"numeric"|"natural")),"invalid layer sort_type");}
                session.execute(&format!("UPDATE spatial_layers SET {field}=?,updated_at=current_timestamp WHERE id=?"),&[value.clone(),json!(layer_id)])?;
            }
        }
        if replace_layer.is_some()&&let Some(label)=label_field{session.execute("UPDATE spatial_layers SET label_field=?,updated_at=current_timestamp WHERE id=?",&[json!(label),json!(layer_id)])?;}
        let receipt=json!({"id":layer_id,"feature_count":features,"srid":4326});
        crate::mutations::record(session,"layers.upload",&receipt)?;
        Ok(receipt)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_traversal_absolute_windows_and_symlink_style_paths() {
        for name in [
            "../bad.shp",
            "/bad.shp",
            "C:/bad.shp",
            "a\\bad.shp",
            "a/../../bad.shp",
        ] {
            assert!(safe_member(name).is_err(), "accepted {name}");
        }
    }
    #[test]
    fn accepts_nested_normal_shapefile_components() {
        assert_eq!(
            safe_member("wards/wards.shp").unwrap(),
            Path::new("wards/wards.shp")
        );
    }
}

#[cfg(test)]
mod native_tests {
    use super::*;
    use std::io::Write;
    fn database(directory: &Path) -> Option<Database> {
        let library = crate::test_support::library();
        let db = Database::open(
            &directory.join("layers.duckdb"),
            &library,
            "256MB",
            1,
            &directory.join("spill"),
        )
        .unwrap();
        crate::test_support::load_spatial(&db);
        Some(db)
    }
    fn snapshot(directory: &Path, wkb: &Value, srid: i64) {
        fs::create_dir_all(directory).unwrap();
        let feature = json!({"id":259,"layer_id":4,"properties_json":"{\"community\":\"LOOP\"}","geometry_wkb_hex":wkb,"srid":srid,"created_at":"2020-01-02 03:04:05","updated_at":"2021-02-03 04:05:06"});
        let file = directory.join("features.ndjson");
        fs::write(&file, format!("{feature}\n")).unwrap();
        let manifest = json!({"format_version":1,"features_file":"features.ndjson","features_sha256":file_sha256(&file).unwrap(),"feature_count":1,"feature_timestamps_preserved":true,"layers":[{"id":4,"name":"Communities","slug":"communities","geometry_type":"POLYGON","srid":4326,"feature_count":1,"is_active":true,"label_field":"community","sort_type":"alphabetic"}]});
        fs::write(directory.join("manifest.json"), manifest.to_string()).unwrap();
    }
    #[test]
    fn restores_exact_feature_ids_properties_timestamps_and_holes() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        let wkb=db.query("SELECT ST_AsHEXWKB(ST_GeomFromText('POLYGON((-88 41,-87 41,-87 42,-88 42,-88 41),(-87.8 41.2,-87.2 41.2,-87.2 41.8,-87.8 41.8,-87.8 41.2))')) wkb",&[]).unwrap()[0]["wkb"].clone();
        let source = temp.path().join("snapshot");
        snapshot(&source, &wkb, 4326);
        import_layer_snapshot(&db, &source).unwrap();
        let row=&db.query("SELECT id,layer_id,properties->>'community' community,created_at,ST_AsHEXWKB(geometry) wkb,ST_Contains(geometry,ST_Point(-87.5,41.5)) hole,ST_Contains(geometry,ST_Point(-88,41.5)) edge FROM spatial_layer_features",&[]).unwrap()[0];
        assert_eq!(row["id"], 259);
        assert_eq!(row["layer_id"], 4);
        assert_eq!(row["community"], "LOOP");
        assert_eq!(row["wkb"], wkb);
        assert_eq!(row["created_at"], "2020-01-02 03:04:05");
        assert_eq!(row["hole"], false);
        assert_eq!(row["edge"], false);
    }
    #[test]
    fn invalid_srid_rolls_back_boundary_metadata() {
        let temp = tempfile::tempdir().unwrap();
        let Some(db) = database(temp.path()) else {
            return;
        };
        let wkb = db
            .query("SELECT ST_AsHEXWKB(ST_Point(-87.6,41.8)) wkb", &[])
            .unwrap()[0]["wkb"]
            .clone();
        let source = temp.path().join("snapshot");
        snapshot(&source, &wkb, 3857);
        assert!(import_layer_snapshot(&db, &source).is_err());
        assert_eq!(db.query("SELECT count(*) n FROM information_schema.tables WHERE table_name='spatial_layers'",&[]).unwrap()[0]["n"],0);
    }
    #[test]
    fn missing_prj_archive_rejected_before_converter_runs() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("missing.zip");
        let mut zip = zip::ZipWriter::new(File::create(&path).unwrap());
        for ext in ["shp", "shx", "dbf"] {
            zip.start_file(
                format!("test.{ext}"),
                zip::write::SimpleFileOptions::default(),
            )
            .unwrap();
            zip.write_all(b"fixture").unwrap();
        }
        zip.finish().unwrap();
        assert!(
            prepare_upload(&path, "missing.zip")
                .err()
                .unwrap()
                .to_string()
                .contains(".prj")
        );
    }
}

#[cfg(test)]
mod upload_tests {
    use super::*;
    #[test]
    fn configured_label_preview_and_metadata_publish_atomically() {
        let library = crate::test_support::library();
        if !library.is_file() {
            return;
        }
        let temp = tempfile::tempdir().unwrap();
        let db = Database::open(
            &temp.path().join("upload.duckdb"),
            &library,
            "256MB",
            1,
            &temp.path().join("spill"),
        )
        .unwrap();
        crate::test_support::load_spatial(&db);
        let path = temp.path().join("upload.geojson");
        fs::write(&path,json!({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"SCHOOL_NM":"Lincoln","rank":1},"geometry":{"type":"Polygon","coordinates":[[[-87.8,41.8],[-87.7,41.8],[-87.7,41.9],[-87.8,41.9],[-87.8,41.8]]]}}]}).to_string()).unwrap();
        let preview = preview_upload(&db, &path).unwrap();
        assert_eq!(preview["recommended_field"], "SCHOOL_NM");
        assert_eq!(preview["fields"][0]["sample_values"][0], "Lincoln");
        publish_upload_metadata(&db,&path,"Schools",Some("SCHOOL_NM"),None,&json!({"description":"School boundaries","sort_type":"numeric","original_filename":"schools.geojson"})).unwrap();
        let row = &db
            .query(
                "SELECT label_field,description,sort_type,original_filename FROM spatial_layers",
                &[],
            )
            .unwrap()[0];
        assert_eq!(row["label_field"], "SCHOOL_NM");
        assert_eq!(row["description"], "School boundaries");
        assert_eq!(row["sort_type"], "numeric");
        assert!(
            publish_upload_metadata(
                &db,
                &path,
                "Bad",
                Some("SCHOOL_NM"),
                None,
                &json!({"sort_type":"invalid"})
            )
            .is_err()
        );
        assert_eq!(
            db.query("SELECT count(*) n FROM spatial_layers", &[])
                .unwrap()[0]["n"],
            1
        );
    }
}

#[cfg(all(test, unix))]
mod conversion_tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn mock(directory: &Path, body: &str) -> PathBuf {
        let executable = directory.join("mock-ogr2ogr");
        fs::write(&executable, format!("#!/bin/sh\n{body}\n")).unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
        executable
    }
    fn limits() -> ConversionLimits {
        ConversionLimits {
            timeout: Duration::from_secs(3),
            output_bytes: 1024,
            stderr_bytes: 128,
        }
    }
    #[test]
    fn slow_converter_is_killed_reaped_and_releases_its_permit() {
        let directory = tempfile::tempdir().unwrap();
        let executable = mock(
            directory.path(),
            "echo $$ > \"$3.pid\"\necho partial > \"$3\"\nwhile :; do :; done",
        );
        let output = directory.path().join("output.geojson");
        let permit = Mutex::new(());
        let started = Instant::now();
        let mut slow_limits = limits();
        slow_limits.timeout = Duration::from_secs(2);
        let error = bounded_conversion(
            &executable,
            Path::new("unused"),
            &output,
            &slow_limits,
            &permit,
        )
        .unwrap_err();
        assert!(error.to_string().contains("deadline"), "{error}");
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(!output.exists());
        let pid: i32 = fs::read_to_string(output.with_extension("geojson.pid"))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        // SAFETY: signal zero only tests the fixture PID; wait() must have reaped it.
        assert_eq!(unsafe { libc::kill(pid, 0) }, -1);
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ESRCH)
        );
        assert!(permit.try_lock().is_ok());
    }
    #[test]
    fn converter_cannot_exceed_output_or_diagnostic_limits() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("output.geojson");
        let permit = Mutex::new(());
        let executable = mock(
            directory.path(),
            "while :; do printf '0123456789012345678901234567890123456789' >> \"$3\"; done",
        );
        assert!(
            bounded_conversion(
                &executable,
                Path::new("unused"),
                &output,
                &limits(),
                &permit
            )
            .is_err()
        );
        assert!(!output.exists());
        let executable = mock(
            directory.path(),
            "while :; do printf '0123456789012345678901234567890123456789' >&2; done",
        );
        let error = bounded_conversion(
            &executable,
            Path::new("unused"),
            &output,
            &limits(),
            &permit,
        )
        .unwrap_err();
        assert!(error.to_string().contains("diagnostics"), "{error}");
        assert!(error.to_string().len() < 512);
    }
    #[test]
    fn converter_permit_refuses_concurrent_work_and_success_preserves_output() {
        let directory = tempfile::tempdir().unwrap();
        let executable = mock(directory.path(), "printf '{}' > \"$3\"");
        let output = directory.path().join("output.geojson");
        let permit = Mutex::new(());
        let guard = permit.lock().unwrap();
        let error = bounded_conversion(
            &executable,
            Path::new("unused"),
            &output,
            &limits(),
            &permit,
        )
        .unwrap_err();
        assert!(error.to_string().contains("another spatial conversion"));
        assert!(!output.exists());
        drop(guard);
        bounded_conversion(
            &executable,
            Path::new("unused"),
            &output,
            &limits(),
            &permit,
        )
        .unwrap();
        assert_eq!(fs::read_to_string(output).unwrap(), "{}");
    }
}

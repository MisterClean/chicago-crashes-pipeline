//! Audited portal schemas and bounded, checksummed source artifacts.
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

const PORTAL_GET_ATTEMPTS: u32 = 3;
const PORTAL_RETRY_AFTER_LIMIT: Duration = Duration::from_secs(30);

fn portal_client() -> Result<reqwest::blocking::Client> {
    Ok(reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(90))
        .connect_timeout(Duration::from_secs(15))
        .retry(reqwest::retry::never())
        .build()?)
}

fn portal_retry_delay(headers: &reqwest::header::HeaderMap, fallback: Duration) -> Duration {
    headers
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .map(Duration::from_secs)
        .unwrap_or(fallback)
        .min(PORTAL_RETRY_AFTER_LIMIT)
}

fn wait_portal_retry(delay: Duration, check: &Check<'_>) -> Result<()> {
    let started = std::time::Instant::now();
    loop {
        check()?;
        let remaining = delay.saturating_sub(started.elapsed());
        if remaining.is_zero() {
            return Ok(());
        }
        std::thread::sleep(remaining.min(Duration::from_millis(100)));
    }
}

/// Retry only idempotent GET transport failures and explicitly transient status
/// codes. Response parsing and publication validation stay outside this loop.
fn portal_get(
    client: &reqwest::blocking::Client,
    request: reqwest::blocking::RequestBuilder,
    check: &Check<'_>,
) -> Result<reqwest::blocking::Response> {
    portal_get_with_backoff(client, request, check, Duration::from_secs(1))
}

fn portal_get_with_backoff(
    client: &reqwest::blocking::Client,
    request: reqwest::blocking::RequestBuilder,
    check: &Check<'_>,
    initial_delay: Duration,
) -> Result<reqwest::blocking::Response> {
    let request = request.build()?;
    ensure!(
        request.method() == reqwest::Method::GET,
        "portal retries require GET"
    );
    for attempt in 1..=PORTAL_GET_ATTEMPTS {
        check()?;
        let outcome = client.execute(request.try_clone().context("portal GET cannot be cloned")?);
        check()?;
        let fallback = initial_delay.saturating_mul(1 << (attempt - 1));
        let delay = match outcome {
            Ok(response) => {
                let status = response.status();
                if !matches!(status.as_u16(), 429 | 500 | 502 | 503 | 504)
                    || attempt == PORTAL_GET_ATTEMPTS
                {
                    return Ok(response.error_for_status()?);
                }
                let delay = portal_retry_delay(response.headers(), fallback);
                tracing::warn!(attempt, status=%status, retry_after_ms=delay.as_millis(), "retrying transient portal GET");
                delay
            }
            Err(error) => {
                let error = error.without_url();
                if (!error.is_timeout() && !error.is_connect()) || attempt == PORTAL_GET_ATTEMPTS {
                    let failure = if error.is_timeout() {
                        "timed out"
                    } else if error.is_connect() {
                        "connection failed"
                    } else {
                        "request failed"
                    };
                    let context = format!(
                        "portal GET {} {failure} on attempt {attempt}/{PORTAL_GET_ATTEMPTS}: {error}",
                        request.url().path()
                    );
                    return Err(error).context(context);
                }
                let delay = fallback.min(PORTAL_RETRY_AFTER_LIMIT);
                tracing::warn!(attempt, endpoint=request.url().path(), error=%error, retry_after_ms=delay.as_millis(), "retrying portal GET transport failure");
                delay
            }
        };
        wait_portal_retry(delay, check)?;
    }
    anyhow::bail!("portal GET retry budget exhausted")
}

const MAPPING: &str = include_str!("../resources/csv_column_mapping.json");
pub type Check<'a> = dyn Fn() -> Result<()> + Send + Sync + 'a;

pub const DATASETS: [&str; 4] = ["crashes", "people", "vehicles", "fatalities"];

#[derive(Clone, Copy)]
struct BulkTransferLimits {
    total_timeout: Duration,
    read_timeout: Duration,
    max_bytes: u64,
}
const BULK_TRANSFER_LIMITS: BulkTransferLimits = BulkTransferLimits {
    total_timeout: Duration::from_secs(2 * 60 * 60),
    read_timeout: Duration::from_secs(120),
    max_bytes: 8 * 1024 * 1024 * 1024,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SourceColumn {
    pub csv_header: String,
    pub api_field: String,
    #[serde(rename = "type")]
    pub data_type: String,
}
#[derive(Debug, Clone, Deserialize)]
pub struct SourceSpec {
    pub dataset_id: String,
    pub metadata_url: String,
    pub csv_download_url: String,
    pub columns: Vec<SourceColumn>,
    pub observed_csv_headers: Vec<String>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicationMode {
    Profiling,
    Production,
}

pub fn specification(dataset: &str) -> Result<SourceSpec> {
    let mut mapping: BTreeMap<String, SourceSpec> = serde_json::from_str(MAPPING)?;
    mapping
        .remove(dataset)
        .with_context(|| format!("unknown dataset {dataset}"))
}
pub fn mapping_sha256() -> String {
    format!("{:x}", Sha256::digest(MAPPING.as_bytes()))
}
pub fn file_sha256(path: &Path) -> Result<String> {
    file_sha256_guarded(path, &|| Ok(()))
}
pub fn file_sha256_guarded(path: &Path, check: &Check<'_>) -> Result<String> {
    let mut source = File::open(path)?;
    let mut buffer = [0_u8; 65536];
    let mut digest = Sha256::new();
    loop {
        check()?;
        let bytes = source.read(&mut buffer)?;
        if bytes == 0 {
            break;
        }
        digest.update(&buffer[..bytes]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
pub fn identifier(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}
pub fn literal(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

pub fn validate_headers(dataset: &str, headers: &[String]) -> Result<()> {
    let expected = specification(dataset)?;
    let observed: BTreeSet<_> = headers.iter().collect();
    ensure!(
        observed.len() == headers.len(),
        "duplicate CSV headers for {dataset}"
    );
    ensure!(
        observed == expected.observed_csv_headers.iter().collect(),
        "CSV schema drift for {dataset}; review explicit mapping"
    );
    Ok(())
}
pub fn validate_metadata(dataset: &str, metadata: &Value) -> Result<()> {
    let expected = specification(dataset)?;
    let expected: BTreeMap<_, _> = expected
        .columns
        .iter()
        .map(|c| {
            (
                c.api_field.as_str(),
                (c.csv_header.as_str(), c.data_type.as_str()),
            )
        })
        .collect();
    let mut observed = BTreeMap::new();
    for column in metadata["columns"]
        .as_array()
        .context("metadata columns missing")?
    {
        let field = column["fieldName"]
            .as_str()
            .context("metadata fieldName missing")?;
        if field.starts_with(':') {
            continue;
        }
        let name = column["name"].as_str().context("metadata name missing")?;
        let kind = column["dataTypeName"]
            .as_str()
            .context("metadata type missing")?;
        ensure!(
            observed.insert(field, (name, kind)).is_none(),
            "duplicate metadata field"
        );
    }
    ensure!(
        observed == expected,
        "portal metadata schema drift for {dataset}"
    );
    ensure!(
        metadata["rowsUpdatedAt"].is_number(),
        "source revision missing"
    );
    Ok(())
}
/// Scans at most one CSV record at a time, respecting embedded quoted newlines.
pub fn inspect_csv_guarded(
    path: &Path,
    dataset: &str,
    check: &Check<'_>,
) -> Result<(Vec<String>, u64)> {
    let mut reader = csv::ReaderBuilder::new().flexible(false).from_path(path)?;
    let headers: Vec<String> = reader
        .headers()?
        .iter()
        .map(|h| h.trim_start_matches('\u{feff}').to_owned())
        .collect();
    validate_headers(dataset, &headers)?;
    let mut record = csv::ByteRecord::new();
    let mut rows = 0;
    while reader.read_byte_record(&mut record)? {
        rows += 1;
        if rows % 1024 == 0 {
            check()?;
        }
    }
    ensure!(rows > 0, "refusing empty full source snapshot");
    Ok((headers, rows))
}

#[derive(Debug, Clone)]
pub struct VerifiedSource {
    pub dataset: String,
    pub path: PathBuf,
    pub manifest: Value,
}
impl VerifiedSource {
    pub fn rows(&self) -> Result<u64> {
        self.manifest["rows"]
            .as_u64()
            .context("manifest row count missing")
    }
    pub fn production_complete(&self) -> bool {
        let m = &self.manifest;
        m["stable_source_revision"] == true
            && m["profiling_only"] == false
            && m["source_revision_before"].is_number()
            && m["source_revision_before"] == m["source_revision_after"]
            && m["rows"].as_u64().is_some_and(|rows| rows > 0)
            && m["rows"] == m["expected_rows_before"]
            && m["rows"] == m["expected_rows_after"]
    }
}
/// Validate receipt, bytes, mapping and headers before a native engine opens input.
pub fn load_source_guarded(
    directory: &Path,
    dataset: &str,
    mode: PublicationMode,
    check: &Check<'_>,
) -> Result<VerifiedSource> {
    specification(dataset)?;
    let path = directory.join("sources").join(format!("{dataset}.csv"));
    let manifest: Value =
        serde_json::from_reader(File::open(path.with_extension("manifest.json"))?)?;
    ensure!(manifest["dataset"] == dataset, "manifest dataset mismatch");
    ensure!(
        manifest["mapping_sha256"] == mapping_sha256(),
        "mapping checksum differs; review source mapping"
    );
    ensure!(
        manifest["bytes"].as_u64() == Some(path.metadata()?.len()),
        "source size mismatch"
    );
    ensure!(
        manifest["sha256"] == file_sha256_guarded(&path, check)?,
        "source checksum mismatch"
    );
    let (headers, rows) = inspect_csv_guarded(&path, dataset, check)?;
    ensure!(
        manifest["rows"].as_u64() == Some(rows),
        "source record count mismatch"
    );
    ensure!(
        manifest["headers"] == json!(headers),
        "manifest header mismatch"
    );
    let source = VerifiedSource {
        dataset: dataset.to_owned(),
        path: path.canonicalize()?,
        manifest,
    };
    if mode == PublicationMode::Production {
        ensure!(
            source.production_complete(),
            "{dataset} is incomplete, unstable or profiling-only; strict reconciliation required before publication"
        );
    }
    Ok(source)
}

fn bounded_json<T: serde::de::DeserializeOwned>(
    mut response: reqwest::blocking::Response,
    max_bytes: usize,
    check: &Check<'_>,
) -> Result<T> {
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 65536];
    loop {
        check()?;
        let size = response.read(&mut buffer)?;
        if size == 0 {
            break;
        }
        ensure!(
            bytes.len().saturating_add(size) <= max_bytes,
            "portal JSON response exceeds bounded size"
        );
        bytes.extend_from_slice(&buffer[..size]);
    }
    Ok(serde_json::from_slice(&bytes)?)
}
fn metadata(client: &reqwest::blocking::Client, dataset: &str, check: &Check<'_>) -> Result<Value> {
    let response = portal_get(
        client,
        client.get(&specification(dataset)?.metadata_url),
        check,
    )?;
    let value = bounded_json(response, 8 * 1024 * 1024, check)?;
    validate_metadata(dataset, &value)?;
    Ok(value)
}
fn portal_count(
    client: &reqwest::blocking::Client,
    dataset: &str,
    check: &Check<'_>,
) -> Result<u64> {
    portal_count_filtered(client, dataset, None, check)
}
fn portal_count_filtered(
    client: &reqwest::blocking::Client,
    dataset: &str,
    filter: Option<&str>,
    check: &Check<'_>,
) -> Result<u64> {
    let id = specification(dataset)?.dataset_id;
    let mut request = client
        .get(format!("https://data.cityofchicago.org/resource/{id}.json"))
        .query(&[("$select", "count(*) as count")]);
    if let Some(filter) = filter {
        request = request.query(&[("$where", filter)]);
    }
    let response = portal_get(client, request, check)?;
    let count: Value = bounded_json(response, 65536, check)?;
    let count = count[0]["count"]
        .as_str()
        .context("portal count missing")?
        .parse::<u64>()?;
    ensure!(count > 0, "refusing empty source snapshot");
    Ok(count)
}

/// Bulk bodies need a longer deadline than metadata. Poll the existing guard
/// while the socket is idle so cancellation never waits for the bulk deadline.
fn transfer_bulk_csv(
    url: &str,
    directory: &Path,
    dataset: &str,
    check: &Check<'_>,
    limits: BulkTransferLimits,
) -> Result<(tempfile::NamedTempFile, u64, Option<u64>)> {
    check()?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let client = reqwest::Client::builder()
            .timeout(limits.total_timeout)
            .connect_timeout(Duration::from_secs(30))
            .read_timeout(limits.read_timeout)
            .build()?;
        let mut guard = tokio::time::interval(Duration::from_millis(100));
        guard.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let request = client
            .get(url)
            .header(reqwest::header::ACCEPT_ENCODING, "identity")
            .send();
        tokio::pin!(request);
        let mut response = loop {
            tokio::select! {
                response = &mut request => break response?.error_for_status()?,
                _ = guard.tick() => check()?,
            }
        };
        let expected_bytes = response.content_length();
        ensure!(
            expected_bytes.is_none_or(|bytes| bytes <= limits.max_bytes),
            "source Content-Length exceeds download size limit"
        );
        let mut output = tempfile::Builder::new()
            .prefix(&format!("{dataset}."))
            .suffix(".part")
            .tempfile_in(directory)?;
        let mut bytes = 0_u64;
        loop {
            let chunk = loop {
                tokio::select! {
                    chunk = response.chunk() => break chunk.context("read bulk CSV body")?,
                    _ = guard.tick() => check()?,
                }
            };
            let Some(chunk) = chunk else { break };
            for chunk in chunk.chunks(65536) {
                check()?;
                bytes = bytes
                    .checked_add(chunk.len() as u64)
                    .context("bulk CSV size overflow")?;
                ensure!(
                    bytes <= limits.max_bytes,
                    "source download exceeds size limit"
                );
                ensure!(
                    expected_bytes.is_none_or(|expected| bytes <= expected),
                    "bulk CSV body exceeds Content-Length"
                );
                output.write_all(chunk)?;
            }
        }
        ensure!(
            expected_bytes.is_none_or(|expected| bytes == expected),
            "bulk CSV Content-Length mismatch"
        );
        output.flush()?;
        output.as_file().sync_all()?;
        check()?;
        Ok((output, bytes, expected_bytes))
    })
}

/// Downloads to a new attempt directory without replacing a verified cache.
/// Incomplete transfers are removed; completed unverified CSVs are quarantined.
/// Stable API counts must exactly match CSV rows.
pub fn download_source(directory: &Path, dataset: &str) -> Result<VerifiedSource> {
    download_source_guarded(directory, dataset, &|| Ok(()))
}
pub fn download_source_guarded(
    directory: &Path,
    dataset: &str,
    check: &Check<'_>,
) -> Result<VerifiedSource> {
    check()?;
    let acquisition_started_at = chrono::Utc::now();
    let spec = specification(dataset)?;
    let client = portal_client()?;
    let before = metadata(&client, dataset, check)?;
    check()?;
    let count_before = portal_count(&client, dataset, check)?;
    check()?;
    let sources = directory.join("sources");
    fs::create_dir_all(&sources)?;
    let path = sources.join(format!("{dataset}.csv"));
    ensure!(
        !path.exists() && !path.with_extension("manifest.json").exists(),
        "source destination already exists; choose fresh attempt directory"
    );
    let (temporary, bytes, content_length) = transfer_bulk_csv(
        &spec.csv_download_url,
        &sources,
        dataset,
        check,
        BULK_TRANSFER_LIMITS,
    )?;
    let manifest_path = path.with_extension("manifest.json");
    let mut published_csv = false;
    let mut published_manifest = false;
    let result = (|| {
        let (headers, rows) = inspect_csv_guarded(temporary.path(), dataset, check)?;
        let after = metadata(&client, dataset, check)?;
        check()?;
        let count_after = portal_count(&client, dataset, check)?;
        check()?;
        let receipt = json!({"manifest_version":1,"dataset":dataset,"dataset_id":spec.dataset_id,"url":spec.csv_download_url,"metadata_url":spec.metadata_url,"source_revision_before":before["rowsUpdatedAt"],"source_revision_after":after["rowsUpdatedAt"],"source_revision":after["rowsUpdatedAt"],"stable_source_revision":before["rowsUpdatedAt"]==after["rowsUpdatedAt"],"profiling_only":false,"expected_rows_before":count_before,"expected_rows_after":count_after,"expected_rows":count_after,"headers":headers,"rows":rows,"bytes":bytes,"sha256":file_sha256_guarded(temporary.path(),check)?,"http_content_length":content_length,"mapping_sha256":mapping_sha256(),"mapping_baseline":"c08b80a","downloaded_at":chrono::Utc::now().to_rfc3339()});
        let mut receipt = receipt;
        receipt["acquisition_started_at"] = json!(acquisition_started_at.to_rfc3339());
        receipt["source_updated_before"] =
            json!((acquisition_started_at - chrono::Duration::seconds(10)).to_rfc3339());
        ensure!(
            before["rowsUpdatedAt"] == after["rowsUpdatedAt"],
            "portal changed during download; retry whole dataset"
        );
        ensure!(
            rows == count_before && rows == count_after,
            "CSV/API count mismatch for {dataset}: CSV={rows}, API before={count_before}, after={count_after}; reconcile via stable ordered API bootstrap"
        );
        let mut manifest_file = tempfile::Builder::new()
            .prefix(&format!("{dataset}."))
            .suffix(".manifest.part")
            .tempfile_in(&sources)?;
        serde_json::to_writer_pretty(&mut manifest_file, &receipt)?;
        manifest_file.as_file().sync_all()?;
        fs::hard_link(temporary.path(), &path)?;
        published_csv = true;
        fs::hard_link(manifest_file.path(), &manifest_path)?;
        published_manifest = true;
        load_source_guarded(directory, dataset, PublicationMode::Production, check)
    })();
    if result.is_err() {
        if published_manifest {
            fs::remove_file(&manifest_path)?;
        }
        if published_csv {
            fs::remove_file(&path)?;
        }
        let quarantine = directory.join("quarantine");
        fs::create_dir_all(&quarantine)?;
        temporary.persist_noclobber(
            quarantine.join(format!("{dataset}.{}.csv", uuid::Uuid::new_v4())),
        )?;
    }
    result
}

/// Strict catch-up fallback when portal bulk CSV omits rows. Pages are ordered
/// by the portal's unique row identity and written directly to CSV; the before/
/// after revision and exact API count must agree. Any mutation rejects the whole
/// attempt rather than moving a checkpoint past a skipped page.
pub fn download_api_source(directory: &Path, dataset: &str) -> Result<VerifiedSource> {
    download_api_source_guarded(directory, dataset, &|| Ok(()))
}
pub fn download_api_source_guarded(
    directory: &Path,
    dataset: &str,
    check: &Check<'_>,
) -> Result<VerifiedSource> {
    download_api_filtered_source(directory, dataset, None, check)
}
/// Complete, stable acquisition of an explicit event-date API window.
pub fn download_api_window_source(
    directory: &Path,
    dataset: &str,
    start: &str,
    end: &str,
    check: &Check<'_>,
) -> Result<VerifiedSource> {
    let start = chrono::NaiveDate::parse_from_str(start, "%Y-%m-%d")?;
    let end = chrono::NaiveDate::parse_from_str(end, "%Y-%m-%d")?;
    ensure!(start <= end, "reversed ingestion date window");
    let exclusive = end.succ_opt().context("date window overflow")?;
    let filter =
        format!("crash_date >= '{start}T00:00:00' AND crash_date < '{exclusive}T00:00:00'");
    download_api_filtered_source(directory, dataset, Some(&filter), check)
}

/// Decode source strings while retaining exact numeric and point JSON tokens.
fn api_csv_value(value: Option<&serde_json::value::RawValue>) -> Result<String> {
    let Some(value) = value else {
        return Ok(String::new());
    };
    let token = value.get();
    if token == "null" {
        Ok(String::new())
    } else if token.starts_with('"') {
        Ok(serde_json::from_str(token)?)
    } else {
        Ok(token.to_owned())
    }
}

fn download_api_filtered_source(
    directory: &Path,
    dataset: &str,
    filter: Option<&str>,
    check: &Check<'_>,
) -> Result<VerifiedSource> {
    check()?;
    let acquisition_started_at = chrono::Utc::now();
    let spec = specification(dataset)?;
    let client = portal_client()?;
    let before = metadata(&client, dataset, check)?;
    check()?;
    let count_before = portal_count_filtered(&client, dataset, filter, check)?;
    check()?;
    let sources = directory.join("sources");
    fs::create_dir_all(&sources)?;
    let path = sources.join(format!("{dataset}.csv"));
    ensure!(
        !path.exists() && !path.with_extension("manifest.json").exists(),
        "API bootstrap requires new attempt directory"
    );
    let temporary = sources.join(format!("{dataset}.{}.part", uuid::Uuid::new_v4()));
    let result = (|| {
        let output = File::options()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        let mut writer = csv::Writer::from_writer(output);
        let headers: Vec<_> = spec.columns.iter().map(|c| c.csv_header.as_str()).collect();
        writer.write_record(&headers)?;
        let selected = spec
            .columns
            .iter()
            .map(|c| c.api_field.as_str())
            .collect::<Vec<_>>()
            .join(",");
        let endpoint = format!(
            "https://data.cityofchicago.org/resource/{}.json",
            spec.dataset_id
        );
        let mut offset = 0_u64;
        loop {
            check()?;
            let mut request = client.get(&endpoint).query(&[
                ("$select", selected.as_str()),
                ("$order", ":id"),
                ("$limit", "5000"),
                ("$offset", &offset.to_string()),
            ]);
            if let Some(filter) = filter {
                request = request.query(&[("$where", filter)]);
            }
            let response = portal_get(&client, request, check)?;
            let page: Vec<BTreeMap<String, Box<serde_json::value::RawValue>>> =
                bounded_json(response, 32 * 1024 * 1024, check)?;
            if page.is_empty() {
                break;
            }
            ensure!(page.len() <= 5000, "portal ignored bounded page size");
            for record in &page {
                check()?;
                let values: Vec<String> = spec
                    .columns
                    .iter()
                    .map(|c| api_csv_value(record.get(&c.api_field).map(AsRef::as_ref)))
                    .collect::<Result<_>>()?;
                writer.write_record(&values)?;
            }
            offset += page.len() as u64;
            ensure!(
                offset <= count_before,
                "portal row count grew during bootstrap"
            );
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        drop(writer);
        let after = metadata(&client, dataset, check)?;
        check()?;
        let count_after = portal_count_filtered(&client, dataset, filter, check)?;
        check()?;
        ensure!(
            before["rowsUpdatedAt"] == after["rowsUpdatedAt"]
                && offset == count_before
                && offset == count_after,
            "source changed or API bootstrap was incomplete; retry"
        );
        let receipt = json!({"manifest_version":1,"dataset":dataset,"dataset_id":spec.dataset_id,"source_origin":"stable_ordered_api_bootstrap","source_filter":filter,"source_scope":if filter.is_some(){"event_date_window"}else{"full_dataset"},"source_revision_before":before["rowsUpdatedAt"],"source_revision_after":after["rowsUpdatedAt"],"source_revision":after["rowsUpdatedAt"],"stable_source_revision":true,"profiling_only":false,"expected_rows_before":count_before,"expected_rows_after":count_after,"expected_rows":count_after,"headers":headers,"rows":offset,"bytes":temporary.metadata()?.len(),"sha256":file_sha256_guarded(&temporary,check)?,"mapping_sha256":mapping_sha256(),"mapping_baseline":"c08b80a","downloaded_at":chrono::Utc::now().to_rfc3339()});
        let mut receipt = receipt;
        receipt["acquisition_started_at"] = json!(acquisition_started_at.to_rfc3339());
        receipt["source_updated_before"] =
            json!((acquisition_started_at - chrono::Duration::seconds(10)).to_rfc3339());
        let mut manifest = File::options()
            .write(true)
            .create_new(true)
            .open(path.with_extension("manifest.json"))?;
        serde_json::to_writer_pretty(&mut manifest, &receipt)?;
        manifest.sync_all()?;
        fs::hard_link(&temporary, &path)?;
        fs::remove_file(&temporary)?;
        load_source_guarded(directory, dataset, PublicationMode::Production, check)
    })();
    if result.is_err() && temporary.exists() {
        let quarantine = directory.join("quarantine");
        fs::create_dir_all(&quarantine)?;
        fs::rename(
            &temporary,
            quarantine.join(format!("{dataset}.api.{}.csv", uuid::Uuid::new_v4())),
        )?;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_duplicate_or_renamed_headers() {
        let mut headers = specification("fatalities").unwrap().observed_csv_headers;
        headers.push(headers[0].clone());
        assert!(validate_headers("fatalities", &headers).is_err());
    }
    #[test]
    fn refuses_profiling_count_gap_as_complete() {
        let source = VerifiedSource {
            dataset: "crashes".into(),
            path: PathBuf::new(),
            manifest: json!({"stable_source_revision":true,"profiling_only":true,"rows":1105499,"expected_rows_before":1105828,"expected_rows_after":1105828,"source_revision_before":1,"source_revision_after":1}),
        };
        assert!(!source.production_complete());
    }
    #[test]
    fn accepts_only_exact_stable_count_evidence() {
        let source = VerifiedSource {
            dataset: "crashes".into(),
            path: PathBuf::new(),
            manifest: json!({"stable_source_revision":true,"profiling_only":false,"rows":1,"expected_rows_before":1,"expected_rows_after":1,"source_revision_before":1,"source_revision_after":1}),
        };
        assert!(source.production_complete());
    }
    #[test]
    fn explicit_fatality_mapping_preserves_mixed_headers() {
        let spec = specification("fatalities").unwrap();
        assert!(
            spec.columns
                .iter()
                .any(|c| c.csv_header != c.api_field.to_uppercase())
        );
    }
}

#[cfg(test)]
mod portal_retry_tests {
    use super::*;
    use std::{
        net::{TcpListener, TcpStream},
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
        thread,
        time::Instant,
    };

    fn server(
        requests: usize,
        respond: impl Fn(usize, TcpStream) + Send + Sync + 'static,
    ) -> (String, Arc<AtomicUsize>, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let address = listener.local_addr().unwrap();
        let received = Arc::new(AtomicUsize::new(0));
        let count = received.clone();
        let respond = Arc::new(respond);
        let worker = thread::spawn(move || {
            let started = Instant::now();
            let mut responses = Vec::new();
            while count.load(Ordering::Acquire) < requests
                && started.elapsed() < Duration::from_secs(5)
            {
                let (mut stream, _) = match listener.accept() {
                    Ok(connection) => connection,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5));
                        continue;
                    }
                    Err(error) => panic!("fixture accept failed: {error}"),
                };
                stream
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut request = Vec::new();
                let mut byte = [0_u8; 1];
                while !request.ends_with(b"\r\n\r\n") {
                    assert!(request.len() < 16384);
                    stream.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                let index = count.fetch_add(1, Ordering::AcqRel);
                let respond = respond.clone();
                responses.push(thread::spawn(move || respond(index, stream)));
            }
            for response in responses {
                response.join().unwrap();
            }
        });
        (format!("http://{address}/source.json"), received, worker)
    }

    fn reply(stream: &mut TcpStream, status: u16, headers: &str) {
        let _ = stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Length: 2\r\nConnection: close\r\n{headers}\r\n{{}}").as_bytes());
    }

    #[test]
    fn transient_status_recovers_without_restarting_the_source_request() {
        for transient in [429, 500, 502, 503, 504] {
            let (url, received, worker) = server(2, move |index, mut stream| {
                reply(
                    &mut stream,
                    if index == 0 { transient } else { 200 },
                    "Retry-After: 0\r\n",
                );
            });
            let client = portal_client().unwrap();
            let response = portal_get_with_backoff(
                &client,
                client.get(url),
                &|| Ok(()),
                Duration::from_millis(5),
            )
            .unwrap();
            assert_eq!(response.status(), reqwest::StatusCode::OK);
            worker.join().unwrap();
            assert_eq!(received.load(Ordering::Acquire), 2);
        }
    }

    #[test]
    fn fatal_client_status_is_not_retried() {
        let (url, received, worker) = server(1, |_, mut stream| reply(&mut stream, 404, ""));
        let client = portal_client().unwrap();
        let checks = AtomicUsize::new(0);
        let check = || {
            checks.fetch_add(1, Ordering::AcqRel);
            Ok(())
        };
        let error =
            portal_get_with_backoff(&client, client.get(url), &check, Duration::from_millis(5))
                .unwrap_err();
        worker.join().unwrap();
        assert_eq!(
            error.downcast_ref::<reqwest::Error>().unwrap().status(),
            Some(reqwest::StatusCode::NOT_FOUND)
        );
        assert_eq!(received.load(Ordering::Acquire), 1);
        assert_eq!(checks.load(Ordering::Acquire), 2);
    }

    #[test]
    fn transient_attempt_budget_is_finite() {
        let (url, received, worker) = server(3, |_, mut stream| {
            reply(&mut stream, 503, "Retry-After: 0\r\n")
        });
        let client = portal_client().unwrap();
        let error = portal_get_with_backoff(
            &client,
            client.get(url),
            &|| Ok(()),
            Duration::from_millis(5),
        )
        .unwrap_err();
        worker.join().unwrap();
        assert_eq!(
            error.downcast_ref::<reqwest::Error>().unwrap().status(),
            Some(reqwest::StatusCode::SERVICE_UNAVAILABLE)
        );
        assert_eq!(received.load(Ordering::Acquire), 3);
    }

    #[test]
    fn cancellation_interrupts_retry_after_backoff() {
        let (url, received, worker) = server(1, |_, mut stream| {
            reply(&mut stream, 429, "Retry-After: 999\r\n")
        });
        let client = portal_client().unwrap();
        let checks = AtomicUsize::new(0);
        let check = || {
            ensure!(
                checks.fetch_add(1, Ordering::AcqRel) < 3,
                "fixture cancelled during backoff"
            );
            Ok(())
        };
        let started = Instant::now();
        let error =
            portal_get_with_backoff(&client, client.get(url), &check, Duration::from_millis(5))
                .unwrap_err();
        worker.join().unwrap();
        assert!(
            error
                .to_string()
                .contains("fixture cancelled during backoff")
        );
        assert!(started.elapsed() < Duration::from_secs(5));
        assert_eq!(received.load(Ordering::Acquire), 1);
    }

    #[test]
    fn send_timeouts_recover_on_a_later_attempt() {
        let (url, received, worker) = server(2, |index, mut stream| {
            if index == 0 {
                thread::sleep(Duration::from_millis(1400));
            }
            reply(&mut stream, 200, "");
        });
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_millis(500))
            .build()
            .unwrap();
        let response = portal_get_with_backoff(
            &client,
            client.get(url),
            &|| Ok(()),
            Duration::from_millis(5),
        )
        .unwrap();
        assert_eq!(response.status(), reqwest::StatusCode::OK);
        worker.join().unwrap();
        assert_eq!(received.load(Ordering::Acquire), 2);
    }

    #[test]
    fn exhausted_timeouts_preserve_actionable_context_without_query_values() {
        let (url, received, worker) = server(3, |_, mut stream| {
            thread::sleep(Duration::from_millis(1400));
            reply(&mut stream, 200, "");
        });
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_millis(500))
            .build()
            .unwrap();
        let error = portal_get_with_backoff(
            &client,
            client.get(format!("{url}?token=private-fixture-value")),
            &|| Ok(()),
            Duration::from_millis(5),
        )
        .unwrap_err();
        worker.join().unwrap();
        let message = error.to_string();
        assert!(
            message.contains("/source.json timed out on attempt 3/3"),
            "{message}"
        );
        assert!(!format!("{error:#}").contains("private-fixture-value"));
        assert!(error.downcast_ref::<reqwest::Error>().unwrap().is_timeout());
        assert_eq!(received.load(Ordering::Acquire), 3);
    }

    #[test]
    fn retry_after_is_an_integer_bounded_to_thirty_seconds() {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(reqwest::header::RETRY_AFTER, "999".parse().unwrap());
        assert_eq!(
            portal_retry_delay(&headers, Duration::from_secs(2)),
            Duration::from_secs(30)
        );
        headers.insert(
            reqwest::header::RETRY_AFTER,
            "not-an-integer".parse().unwrap(),
        );
        assert_eq!(
            portal_retry_delay(&headers, Duration::from_secs(2)),
            Duration::from_secs(2)
        );
    }
}

#[cfg(test)]
mod bulk_transport_tests {
    use super::*;
    use std::{
        net::{TcpListener, TcpStream},
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
        thread,
        time::Instant,
    };

    fn server(
        respond: impl FnOnce(TcpStream) + Send + 'static,
    ) -> (String, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let worker = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut request = Vec::new();
            let mut byte = [0_u8; 1];
            while !request.ends_with(b"\r\n\r\n") {
                assert!(request.len() < 16384, "oversized fixture request");
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
            }
            respond(stream);
        });
        (format!("http://{address}/rows.csv"), worker)
    }

    fn limits() -> BulkTransferLimits {
        BulkTransferLimits {
            total_timeout: Duration::from_secs(3),
            read_timeout: Duration::from_millis(500),
            max_bytes: 1024,
        }
    }

    #[test]
    fn truncated_body_removes_its_partial_and_preserves_unrelated_files() {
        let directory = tempfile::tempdir().unwrap();
        let unrelated = directory.path().join("unrelated.part");
        fs::write(&unrelated, "keep").unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\nabc")
                .unwrap();
        });
        let result = transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits());
        worker.join().unwrap();
        assert!(
            result.is_err(),
            "truncated Content-Length body was accepted"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 1);
        assert_eq!(fs::read_to_string(unrelated).unwrap(), "keep");
    }

    #[test]
    fn stalled_body_uses_its_read_deadline_and_removes_the_partial() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\na")
                .unwrap();
            thread::sleep(Duration::from_millis(800));
        });
        let mut limits = limits();
        limits.read_timeout = Duration::from_millis(150);
        let started = Instant::now();
        let result = transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits);
        let elapsed = started.elapsed();
        worker.join().unwrap();
        assert!(result.is_err(), "stalled body was accepted");
        assert!(
            elapsed < Duration::from_millis(700),
            "stall timeout took {elapsed:?}"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }

    #[test]
    fn total_deadline_stops_an_otherwise_progressing_chunked_body() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n",
                )
                .unwrap();
            for _ in 0..20 {
                if stream.write_all(b"1\r\na\r\n").is_err() {
                    return;
                }
                thread::sleep(Duration::from_millis(50));
            }
            let _ = stream.write_all(b"0\r\n\r\n");
        });
        let mut limits = limits();
        limits.total_timeout = Duration::from_millis(250);
        let started = Instant::now();
        let result = transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits);
        let elapsed = started.elapsed();
        worker.join().unwrap();
        assert!(result.is_err(), "progress bypassed the total deadline");
        assert!(
            elapsed < Duration::from_millis(900),
            "total deadline took {elapsed:?}"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }

    #[test]
    fn cancellation_interrupts_a_stalled_body_and_removes_written_bytes() {
        let directory = tempfile::tempdir().unwrap();
        let sent = Arc::new(AtomicBool::new(false));
        let worker_sent = sent.clone();
        let (url, worker) = server(move |mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\na")
                .unwrap();
            worker_sent.store(true, Ordering::Release);
            thread::sleep(Duration::from_millis(800));
        });
        let check = || -> Result<()> {
            if sent.load(Ordering::Acquire) {
                for entry in fs::read_dir(directory.path())? {
                    ensure!(entry?.metadata()?.len() == 0, "fixture lease cancelled");
                }
            }
            Ok(())
        };
        let mut limits = limits();
        limits.read_timeout = Duration::from_secs(2);
        let started = Instant::now();
        let error =
            transfer_bulk_csv(&url, directory.path(), "crashes", &check, limits).unwrap_err();
        let elapsed = started.elapsed();
        worker.join().unwrap();
        assert!(
            error.to_string().contains("fixture lease cancelled"),
            "{error:#}"
        );
        assert!(
            elapsed < Duration::from_millis(700),
            "cancellation took {elapsed:?}"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }

    #[test]
    fn excessive_declared_length_is_rejected_before_creating_a_file() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1025\r\nConnection: close\r\n\r\n")
                .unwrap();
        });
        let error =
            transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits()).unwrap_err();
        worker.join().unwrap();
        assert!(
            error.to_string().contains("Content-Length exceeds"),
            "{error:#}"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }

    #[test]
    fn unknown_length_still_enforces_the_streamed_byte_cap() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nabcde")
                .unwrap();
        });
        let mut limits = limits();
        limits.max_bytes = 4;
        let error =
            transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits).unwrap_err();
        worker.join().unwrap();
        assert!(
            error.to_string().contains("download exceeds size limit"),
            "{error:#}"
        );
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }

    #[test]
    fn chunked_body_without_length_counts_only_decoded_payload_bytes() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n").unwrap();
        });
        let mut limits = limits();
        limits.max_bytes = 5;
        let (output, bytes, expected) =
            transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits).unwrap();
        worker.join().unwrap();
        assert_eq!((bytes, expected), (5, None));
        assert_eq!(fs::read(output.path()).unwrap(), b"abcde");
    }

    #[test]
    fn healthy_progress_resets_the_read_deadline_and_matches_known_length() {
        let directory = tempfile::tempdir().unwrap();
        let (url, worker) = server(|mut stream| {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\n")
                .unwrap();
            for byte in b"abcde" {
                stream.write_all(&[*byte]).unwrap();
                thread::sleep(Duration::from_millis(150));
            }
        });
        let (output, bytes, expected) =
            transfer_bulk_csv(&url, directory.path(), "crashes", &|| Ok(()), limits()).unwrap();
        worker.join().unwrap();
        assert_eq!((bytes, expected), (5, Some(5)));
        assert_eq!(fs::read(output.path()).unwrap(), b"abcde");
        drop(output);
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }
}

fn canonical_decimal(value: &str) -> Result<String> {
    let value = value.trim();
    ensure!(
        !value.is_empty() && value.len() <= 128,
        "invalid source point coordinate length"
    );
    let (negative, value) = if let Some(value) = value.strip_prefix('-') {
        (true, value)
    } else {
        (false, value.strip_prefix('+').unwrap_or(value))
    };
    let (mantissa, exponent) = if let Some(index) = value.find(['e', 'E']) {
        let exponent = value[index + 1..]
            .parse::<i32>()
            .context("invalid source point exponent")?;
        (&value[..index], exponent)
    } else {
        (value, 0)
    };
    ensure!(
        exponent.unsigned_abs() <= 1000,
        "source point exponent exceeds bound"
    );
    let mut parts = mantissa.split('.');
    let integer = parts.next().unwrap_or("");
    let fraction = parts.next().unwrap_or("");
    ensure!(
        parts.next().is_none()
            && (!integer.is_empty() || !fraction.is_empty())
            && integer
                .bytes()
                .chain(fraction.bytes())
                .all(|value| value.is_ascii_digit()),
        "source point coordinates must be finite decimal numbers"
    );
    let digits = format!("{integer}{fraction}");
    let digits = digits.trim_start_matches('0');
    if digits.is_empty() {
        return Ok("0".to_owned());
    }
    let trimmed = digits.trim_end_matches('0');
    let exponent = exponent - (fraction.len() as i32) + (digits.len() - trimmed.len()) as i32;
    let point = trimmed.len() as i32 + exponent;
    let number = if point <= 0 {
        format!("0.{}{trimmed}", "0".repeat((-point) as usize))
    } else if point >= trimmed.len() as i32 {
        format!(
            "{trimmed}{}",
            "0".repeat((point - trimmed.len() as i32) as usize)
        )
    } else {
        let point = point as usize;
        format!("{}.{}", &trimmed[..point], &trimmed[point..])
    };
    Ok(if negative {
        format!("-{number}")
    } else {
        number
    })
}
/// Retain numeric JSON tokens before decimal canonicalization. Parsing these
/// through `Value::Number` first would round coordinates to binary floating point.
fn raw_point_coordinates(value: &str) -> Result<Vec<String>> {
    #[derive(Deserialize)]
    struct Point<'a> {
        #[serde(rename = "type")]
        kind: String,
        #[serde(borrow)]
        coordinates: [&'a serde_json::value::RawValue; 2],
    }
    let point: Point<'_> = serde_json::from_str(value)?;
    ensure!(
        point.kind == "Point",
        "source point must be a GeoJSON Point"
    );
    point
        .coordinates
        .iter()
        .map(|coordinate| {
            let token = coordinate.get();
            if token.starts_with('"') {
                Ok(serde_json::from_str(token)?)
            } else {
                Ok(token.to_owned())
            }
        })
        .collect()
}

/// Preserve the deployed archival point representation independently of Chicago
/// latitude/longitude validation and the geometry used for spatial selection.
pub fn canonical_source_point(value: &str) -> Result<String> {
    if value.is_empty() {
        return Ok(String::new());
    }
    let value = value.trim();
    let coordinates = if value.starts_with('{') {
        raw_point_coordinates(value)?
    } else {
        ensure!(
            value
                .get(..5)
                .is_some_and(|token| token.eq_ignore_ascii_case("POINT")),
            "source point must be WKT POINT or GeoJSON Point"
        );
        let body = value[5..]
            .trim()
            .strip_prefix('(')
            .and_then(|value| value.strip_suffix(')'))
            .context("invalid source point WKT")?;
        let coordinates = body
            .split_whitespace()
            .map(str::to_owned)
            .collect::<Vec<_>>();
        ensure!(
            coordinates.len() == 2,
            "source point requires exactly two coordinates"
        );
        coordinates
    };
    Ok(format!(
        "POINT ({} {})",
        canonical_decimal(&coordinates[0])?,
        canonical_decimal(&coordinates[1])?
    ))
}
/// Canonicalize only the small fatality source into owner scratch. Raw checked
/// source artifacts remain unchanged; no historical dataset is held in Rust RAM.
pub fn canonical_fatality_csv(
    path: &Path,
    temp_directory: &Path,
    check: &Check<'_>,
) -> Result<tempfile::NamedTempFile> {
    fs::create_dir_all(temp_directory)?;
    let mut output = tempfile::NamedTempFile::new_in(temp_directory)?;
    let mut reader = csv::Reader::from_path(path)?;
    let headers = reader.headers()?.clone();
    let column = specification("fatalities")?
        .columns
        .into_iter()
        .find(|column| column.api_field == "geocoded_column")
        .context("fatality point mapping missing")?;
    let index = headers
        .iter()
        .position(|header| header.trim_start_matches('\u{feff}') == column.csv_header)
        .context("fatality point header missing")?;
    let mut writer = csv::Writer::from_writer(output.as_file_mut());
    writer.write_record(&headers)?;
    let mut record = csv::StringRecord::new();
    let mut rows = 0_u64;
    while reader.read_record(&mut record)? {
        check()?;
        rows += 1;
        ensure!(
            rows <= 100000,
            "fatality source exceeds deployed 100000-row bound"
        );
        let point =
            canonical_source_point(record.get(index).context("fatality point field missing")?)?;
        let fields = record.iter().enumerate().map(|(column, value)| {
            if column == index {
                point.as_str()
            } else {
                value
            }
        });
        writer.write_record(fields)?;
    }
    writer.flush()?;
    drop(writer);
    Ok(output)
}

#[cfg(test)]
mod point_tests {
    use super::*;
    #[test]
    fn wkt_and_geojson_points_share_exact_decimal_canonical_form() {
        let wkt =
            canonical_source_point(" point ( -087.60000000000001234 +041.80000000000000987 ) ")
                .unwrap();
        let json=canonical_source_point(r#"{"type":"Point","coordinates":["-8.760000000000001234e1","4.180000000000000987e1"]}"#).unwrap();
        assert_eq!(wkt, json);
        assert_eq!(wkt, "POINT (-87.60000000000001234 41.80000000000000987)");
    }
    #[test]
    fn numeric_geojson_tokens_keep_distinctions_beyond_binary_float_precision() {
        let wkt =
            canonical_source_point("POINT (-87.60000000000001234 41.80000000000000987)").unwrap();
        let json = canonical_source_point(
            r#"{"type":"Point","coordinates":[-87.60000000000001234,41.80000000000000987]}"#,
        )
        .unwrap();
        assert_eq!(wkt, json);
        let changed = canonical_source_point(
            r#"{"type":"Point","coordinates":[-87.60000000000001235,41.80000000000000987]}"#,
        )
        .unwrap();
        assert_ne!(json, changed);
    }
    #[test]
    fn api_page_fields_preserve_exact_numeric_points_and_decode_strings_and_nulls() {
        let raw = r#"[{"location":{"type":"Point","coordinates":[-87.60000000000001234,41.80000000000000987]},"number":87.60000000000001234,"text":"a\\b\nc","absent":null}]"#;
        let page: Vec<BTreeMap<String, Box<serde_json::value::RawValue>>> =
            serde_json::from_str(raw).unwrap();
        let field = |name: &str| api_csv_value(page[0].get(name).map(AsRef::as_ref)).unwrap();
        assert_eq!(
            field("location"),
            r#"{"type":"Point","coordinates":[-87.60000000000001234,41.80000000000000987]}"#
        );
        assert_eq!(
            canonical_source_point(&field("location")).unwrap(),
            "POINT (-87.60000000000001234 41.80000000000000987)"
        );
        assert_eq!(field("number"), "87.60000000000001234");
        assert_eq!(field("text"), "a\\b\nc");
        assert_eq!(field("absent"), "");
        assert_eq!(field("missing"), "");
    }
    #[test]
    fn source_points_keep_archival_coordinates_and_canonical_zero() {
        assert_eq!(
            canonical_source_point("POINT (999.5000 -0.000)").unwrap(),
            "POINT (999.5 0)"
        );
    }
    #[test]
    fn nonfinite_malformed_or_three_dimensional_source_points_are_rejected() {
        for point in [
            "POINT (NaN 41)",
            "POINT (-87 Infinity)",
            "POINT (-87 41 1)",
            "LINESTRING (-87 41,-87 42)",
        ] {
            assert!(canonical_source_point(point).is_err());
        }
    }
}

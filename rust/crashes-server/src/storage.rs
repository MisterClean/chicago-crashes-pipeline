//! Private S3-compatible delivery. Credentials and signed request URLs never enter logs.

use anyhow::{Context, Result, anyhow, ensure};
use reqwest::blocking::Client;
use rusty_s3::{
    Bucket, Credentials, UrlStyle,
    actions::{DeleteObject, GetObject, HeadObject, ListObjectsV2, PutObject, S3Action},
};
use std::{
    fs::File,
    io::Read,
    path::Path,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

/// One bounded object-list page; the continuation token is opaque.
pub struct ObjectPage {
    pub objects: Vec<StoredObject>,
    pub next_continuation_token: Option<String>,
}

/// Object metadata used for age-based cleanup and retention.
pub struct StoredObject {
    pub key: String,
    pub bytes: u64,
    pub last_modified: chrono::DateTime<chrono::Utc>,
}

struct GuardedFile {
    file: File,
    cancelled: Arc<AtomicBool>,
}
impl Read for GuardedFile {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        if self.cancelled.load(Ordering::Acquire) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Interrupted,
                "artifact upload cancelled",
            ));
        }
        let bounded = buffer.len().min(65536);
        self.file.read(&mut buffer[..bounded])
    }
}

/// Export-only credentials, separate from the analytical database and API key.
/// This deliberately has no Debug implementation.
#[derive(Clone)]
pub struct ObjectStorage {
    bucket: Bucket,
    credentials: Credentials,
    client: Client,
}

fn env(name: &str) -> String {
    std::env::var(name).unwrap_or_default()
}

fn validate_key(key: &str) -> Result<()> {
    ensure!(
        key.len() <= 1024 && (key.starts_with("exports/") || key.starts_with("backups/")),
        "object key must use the exports/ or backups/ namespace"
    );
    ensure!(
        key.bytes()
            .all(|value| value.is_ascii_alphanumeric() || b"-_. /".contains(&value))
            && !key.contains(' '),
        "invalid object key characters"
    );
    ensure!(
        key.split('/')
            .all(|part| !part.is_empty() && part != "." && part != ".."),
        "invalid object key path"
    );
    Ok(())
}

impl ObjectStorage {
    /// Read the existing EXPORT_* configuration. Partial configuration is an error.
    /// Construct blocking clients on a blocking thread before starting async serving.
    pub fn from_env() -> Result<Option<Self>> {
        let endpoint = env("EXPORT_ENDPOINT");
        let bucket = env("EXPORT_BUCKET");
        let access = env("EXPORT_ACCESS_KEY_ID");
        let secret = env("EXPORT_SECRET_ACCESS_KEY");
        if [&endpoint, &bucket, &access, &secret]
            .iter()
            .all(|value| value.is_empty())
        {
            return Ok(None);
        }
        ensure!(
            [&endpoint, &bucket, &access, &secret]
                .iter()
                .all(|value| !value.is_empty()),
            "EXPORT_ENDPOINT, EXPORT_BUCKET, EXPORT_ACCESS_KEY_ID and EXPORT_SECRET_ACCESS_KEY must all be set"
        );
        let region = std::env::var("EXPORT_REGION").unwrap_or_else(|_| "auto".into());
        let path_style = env("EXPORT_ADDRESSING_STYLE") == "path";
        Ok(Some(Self::new(
            &endpoint, &bucket, &access, &secret, &region, path_style,
        )?))
    }

    fn new(
        endpoint: &str,
        bucket: &str,
        access: &str,
        secret: &str,
        region: &str,
        path_style: bool,
    ) -> Result<Self> {
        let endpoint = endpoint
            .parse::<reqwest::Url>()
            .context("invalid private storage endpoint")?;
        ensure!(
            endpoint.username().is_empty()
                && endpoint.password().is_none()
                && endpoint.query().is_none()
                && endpoint.fragment().is_none(),
            "storage endpoint may not contain credentials, query or fragment"
        );
        let is_local = endpoint
            .host_str()
            .is_some_and(|host| matches!(host, "127.0.0.1" | "localhost" | "::1"));
        ensure!(
            endpoint.scheme() == "https" || (endpoint.scheme() == "http" && is_local),
            "private storage requires HTTPS"
        );
        ensure!(
            !bucket.is_empty()
                && bucket.bytes().all(|value| value.is_ascii_lowercase()
                    || value.is_ascii_digit()
                    || b"-.".contains(&value)),
            "invalid bucket name"
        );
        let style = if path_style {
            UrlStyle::Path
        } else {
            UrlStyle::VirtualHost
        };
        let bucket = Bucket::new(endpoint, style, bucket.to_owned(), region.to_owned())
            .map_err(|_| anyhow!("invalid private storage bucket configuration"))?;
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(300))
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        Ok(Self {
            bucket,
            credentials: Credentials::new(access, secret),
            client,
        })
    }

    /// Stream an artifact, then verify remote size and SHA metadata before publication.
    /// Keys must contain a fresh job attempt token; retries never overwrite a live key.
    pub fn upload(&self, path: &Path, key: &str, sha256: &str) -> Result<()> {
        self.upload_guarded(path, key, sha256, &|| Ok(()))
    }

    /// Stream at most 64 KiB per read while a scoped watchdog checks ownership.
    /// Cancellation aborts subsequent reads and always prevents publishing a pointer;
    /// a socket stalled after the final read remains bounded by the 300-second timeout.
    pub fn upload_guarded(
        &self,
        path: &Path,
        key: &str,
        sha256: &str,
        check: &(dyn Fn() -> Result<()> + Sync),
    ) -> Result<()> {
        check()?;
        let done = AtomicBool::new(false);
        let cancelled = Arc::new(AtomicBool::new(false));
        let failure = Mutex::new(None);
        std::thread::scope(|scope| {
            let watcher = scope.spawn(|| {
                while !done.load(Ordering::Acquire) {
                    if let Err(error) = check() {
                        if let Ok(mut failure) = failure.lock() {
                            *failure = Some(error);
                        }
                        cancelled.store(true, Ordering::Release);
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
            });
            let result = self.upload_inner(path, key, sha256, cancelled.clone());
            done.store(true, Ordering::Release);
            watcher
                .join()
                .map_err(|_| anyhow!("artifact upload watchdog panicked"))?;
            if let Some(error) = failure
                .lock()
                .map_err(|_| anyhow!("upload watchdog lock poisoned"))?
                .take()
            {
                return Err(error);
            }
            result?;
            check()
        })
    }

    fn upload_inner(
        &self,
        path: &Path,
        key: &str,
        sha256: &str,
        cancelled: Arc<AtomicBool>,
    ) -> Result<()> {
        validate_key(key)?;
        ensure!(
            sha256.len() == 64 && sha256.bytes().all(|byte| byte.is_ascii_hexdigit()),
            "invalid artifact digest"
        );
        let bytes = path.metadata()?.len();
        ensure!(
            crate::exports::file_sha256(path)? == sha256,
            "local artifact checksum changed before upload"
        );
        let content_type = if key.ends_with(".zip") {
            "application/zip"
        } else if key.ends_with(".csv") {
            "text/csv"
        } else {
            "application/octet-stream"
        };
        let filename = key.rsplit('/').next().context("object filename missing")?;
        let disposition = format!("attachment; filename=\"{filename}\"");
        let mut action = PutObject::new(&self.bucket, Some(&self.credentials), key);
        action.headers_mut().insert("x-amz-meta-sha256", sha256);
        action.headers_mut().insert("content-type", content_type);
        action
            .headers_mut()
            .insert("content-disposition", disposition.as_str());
        let url = action.sign(Duration::from_secs(600));
        let response = self
            .client
            .put(url)
            .header("content-length", bytes)
            .header("content-type", content_type)
            .header("content-disposition", &disposition)
            .header("x-amz-meta-sha256", sha256)
            .body(reqwest::blocking::Body::sized(
                GuardedFile {
                    file: File::open(path)?,
                    cancelled,
                },
                bytes,
            ))
            .send()
            .map_err(|_| anyhow!("private artifact upload request failed"))?;
        ensure!(
            response.status().is_success(),
            "private artifact upload returned HTTP {}",
            response.status().as_u16()
        );
        self.verify(key, bytes, sha256)
    }

    /// Verify an existing uploaded object before publishing its durable queue pointer.
    pub fn verify(&self, key: &str, expected_bytes: u64, expected_sha256: &str) -> Result<()> {
        validate_key(key)?;
        let action = HeadObject::new(&self.bucket, Some(&self.credentials), key);
        let response = self
            .client
            .head(action.sign(Duration::from_secs(300)))
            .send()
            .map_err(|_| anyhow!("private artifact verification request failed"))?;
        ensure!(
            response.status().is_success(),
            "private artifact verification returned HTTP {}",
            response.status().as_u16()
        );
        let bytes = response
            .headers()
            .get("content-length")
            .context("private artifact length metadata missing")?
            .to_str()?
            .parse::<u64>()?;
        let digest = response
            .headers()
            .get("x-amz-meta-sha256")
            .context("private artifact checksum metadata missing")?
            .to_str()?;
        ensure!(
            bytes == expected_bytes && digest == expected_sha256,
            "uploaded artifact verification failed"
        );
        Ok(())
    }

    /// Sign a short-lived browser URL. Never log the result or return it for expired jobs.
    pub fn signed_download(&self, key: &str, seconds: u64) -> Result<String> {
        validate_key(key)?;
        ensure!(
            (1..=900).contains(&seconds),
            "download signature lifetime must be 1..900 seconds"
        );
        let action = GetObject::new(&self.bucket, Some(&self.credentials), key);
        Ok(action.sign(Duration::from_secs(seconds)).to_string())
    }

    /// Delete one explicitly expired/orphaned artifact. Missing keys are idempotent.
    pub fn delete(&self, key: &str) -> Result<()> {
        validate_key(key)?;
        let action = DeleteObject::new(&self.bucket, Some(&self.credentials), key);
        let response = self
            .client
            .delete(action.sign(Duration::from_secs(300)))
            .send()
            .map_err(|_| anyhow!("private artifact deletion request failed"))?;
        ensure!(
            response.status().is_success() || response.status() == reqwest::StatusCode::NOT_FOUND,
            "private artifact deletion returned HTTP {}",
            response.status().as_u16()
        );
        Ok(())
    }

    /// Fetch at most 1000 entries and 2 MiB XML. Cleanup callers must bound page count.
    pub fn list_page(
        &self,
        prefix: &str,
        continuation: Option<&str>,
        limit: u16,
    ) -> Result<ObjectPage> {
        ensure!(
            (1..=1000).contains(&limit),
            "object page limit must be 1..1000"
        );
        ensure!(
            prefix == "exports/"
                || prefix == "backups/"
                || prefix.starts_with("backups/full/")
                || prefix.starts_with("backups/control/"),
            "unsupported object list namespace"
        );
        let mut action = ListObjectsV2::new(&self.bucket, Some(&self.credentials));
        action.with_prefix(prefix);
        if let Some(token) = continuation {
            ensure!(token.len() <= 8192, "oversized continuation token");
            action.with_continuation_token(token);
        }
        action.with_max_keys(usize::from(limit));
        let response = self
            .client
            .get(action.sign(Duration::from_secs(300)))
            .send()
            .map_err(|_| anyhow!("private object list request failed"))?;
        ensure!(
            response.status().is_success(),
            "private object list returned HTTP {}",
            response.status().as_u16()
        );
        let mut bounded = response.take(2_097_153);
        let mut xml = String::new();
        bounded.read_to_string(&mut xml)?;
        ensure!(xml.len() <= 2_097_152, "object listing exceeds 2 MiB");
        let parsed = ListObjectsV2::parse_response(&xml)
            .map_err(|_| anyhow!("invalid private object listing"))?;
        ensure!(
            parsed.contents.len() <= usize::from(limit),
            "object listing exceeds requested page limit"
        );
        let objects = parsed
            .contents
            .into_iter()
            .map(|object| {
                Ok(StoredObject {
                    key: object.key,
                    bytes: object.size,
                    last_modified: chrono::DateTime::parse_from_rfc3339(&object.last_modified)?
                        .with_timezone(&chrono::Utc),
                })
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(ObjectPage {
            objects,
            next_continuation_token: parsed.next_continuation_token,
        })
    }

    /// Delete old unreferenced export attempts with bounded memory and request count.
    /// A crash after upload and before SQLite publication leaves one such orphan.
    pub fn cleanup_orphans(
        &self,
        before: chrono::DateTime<chrono::Utc>,
        retain: impl Fn(&str) -> Result<bool>,
        max_pages: u16,
    ) -> Result<usize> {
        ensure!(
            (1..=1000).contains(&max_pages),
            "orphan sweep pages must be 1..1000"
        );
        let mut continuation = None;
        let mut removed = 0;
        let mut removed_bytes = 0u64;
        for _ in 0..max_pages {
            let page = self.list_page("exports/", continuation.as_deref(), 1000)?;
            for object in page.objects {
                if object.last_modified < before && !retain(&object.key)? {
                    self.delete(&object.key)?;
                    removed += 1;
                    removed_bytes = removed_bytes.saturating_add(object.bytes);
                }
            }
            continuation = page.next_continuation_token;
            if continuation.is_none() {
                break;
            }
        }
        tracing::info!(
            removed,
            removed_bytes,
            "private export orphan sweep finished"
        );
        Ok(removed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::Digest;

    #[test]
    fn signed_download_uses_virtual_host_and_finite_lifetime() -> Result<()> {
        let storage = ObjectStorage::new(
            "https://example.com/",
            "private-bucket",
            "test-access",
            "test-secret",
            "auto",
            false,
        )?;
        let url = reqwest::Url::parse(
            &storage.signed_download("exports/job/attempt/artifact.csv", 300)?,
        )?;
        assert_eq!(url.host_str(), Some("private-bucket.example.com"));
        assert!(
            url.query_pairs()
                .any(|(name, value)| name == "X-Amz-Expires" && value == "300")
        );
        assert!(storage.signed_download("exports/../private", 300).is_err());
        assert!(
            storage
                .signed_download("exports/job/artifact.csv", 3600)
                .is_err()
        );
        Ok(())
    }

    #[test]
    fn storage_rejects_unencrypted_remote_endpoint() {
        assert!(
            ObjectStorage::new(
                "http://example.com/",
                "private-bucket",
                "test",
                "test",
                "auto",
                false
            )
            .is_err()
        );
    }

    fn mock_upload(
        expected_bytes: Vec<u8>,
        correct_head: bool,
    ) -> Result<(String, std::thread::JoinHandle<Result<()>>)> {
        use std::{
            io::{BufRead, BufReader, Write},
            net::TcpListener,
        };
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let endpoint = format!("http://{}/", listener.local_addr()?);
        let handle = std::thread::spawn(move || -> Result<()> {
            let expected_digest = format!("{:x}", sha2::Sha256::digest(&expected_bytes));
            for method in ["PUT", "HEAD"] {
                let (stream, _) = listener.accept()?;
                stream.set_read_timeout(Some(Duration::from_secs(5)))?;
                let mut input = BufReader::new(stream);
                let mut first = String::new();
                input.read_line(&mut first)?;
                let pieces = first.split_whitespace().collect::<Vec<_>>();
                ensure!(
                    pieces.first() == Some(&method),
                    "mock storage unexpected HTTP method"
                );
                let url = reqwest::Url::parse(&format!(
                    "http://localhost{}",
                    pieces.get(1).context("request target")?
                ))?;
                let signed = url
                    .query_pairs()
                    .find(|(name, _)| name == "X-Amz-SignedHeaders")
                    .map(|(_, value)| value.into_owned())
                    .context("signature missing")?;
                let mut headers = std::collections::BTreeMap::new();
                loop {
                    let mut line = String::new();
                    input.read_line(&mut line)?;
                    if line == "\r\n" {
                        break;
                    }
                    let (name, value) = line.split_once(':').context("malformed request header")?;
                    headers.insert(name.to_ascii_lowercase(), value.trim().to_owned());
                }
                if method == "PUT" {
                    for name in [
                        "host",
                        "content-type",
                        "content-disposition",
                        "x-amz-meta-sha256",
                    ] {
                        ensure!(
                            signed.split(';').any(|header| header == name),
                            "required upload header was not signed"
                        );
                    }
                    ensure!(
                        headers.get("x-amz-meta-sha256") == Some(&expected_digest),
                        "upload digest metadata differs"
                    );
                    let bytes: usize = headers
                        .get("content-length")
                        .context("length missing")?
                        .parse()?;
                    let mut body = vec![0u8; bytes];
                    input.read_exact(&mut body)?;
                    ensure!(body == expected_bytes, "upload body differs");
                    input.get_mut().write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    )?;
                } else {
                    let digest = if correct_head {
                        expected_digest.clone()
                    } else {
                        "0".repeat(64)
                    };
                    let response = format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nx-amz-meta-sha256: {}\r\nConnection: close\r\n\r\n",
                        expected_bytes.len(),
                        digest
                    );
                    input.get_mut().write_all(response.as_bytes())?;
                }
            }
            Ok(())
        });
        Ok((endpoint, handle))
    }

    #[test]
    fn real_http_upload_signs_metadata_streams_bytes_and_verifies_head() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("export.csv");
        let content = b"column\nvalue\n";
        std::fs::write(&path, content)?;
        let digest = crate::exports::file_sha256(&path)?;
        let (endpoint, server) = mock_upload(content.to_vec(), true)?;
        let storage = ObjectStorage::new(
            &endpoint,
            "private-bucket",
            "test-access",
            "test-secret",
            "auto",
            true,
        )?;
        storage.upload_guarded(&path, "exports/job/attempt/export.csv", &digest, &|| Ok(()))?;
        server
            .join()
            .map_err(|_| anyhow!("mock storage panicked"))??;
        Ok(())
    }

    #[test]
    fn real_http_upload_rejects_wrong_remote_checksum() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("export.csv");
        let content = b"column\nvalue\n";
        std::fs::write(&path, content)?;
        let digest = crate::exports::file_sha256(&path)?;
        let (endpoint, server) = mock_upload(content.to_vec(), false)?;
        let storage = ObjectStorage::new(
            &endpoint,
            "private-bucket",
            "test-access",
            "test-secret",
            "auto",
            true,
        )?;
        assert!(
            storage
                .upload(&path, "exports/job/attempt/export.csv", &digest)
                .is_err()
        );
        server
            .join()
            .map_err(|_| anyhow!("mock storage panicked"))??;
        Ok(())
    }

    #[test]
    fn cancelled_upload_never_opens_network_request() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("export.csv");
        std::fs::write(&path, b"column\nvalue\n")?;
        let storage = ObjectStorage::new(
            "http://127.0.0.1:1/",
            "private-bucket",
            "test-access",
            "test-secret",
            "auto",
            true,
        )?;
        let error = storage
            .upload_guarded(
                &path,
                "exports/job/attempt/export.csv",
                &crate::exports::file_sha256(&path)?,
                &|| anyhow::bail!("cancelled by test"),
            )
            .unwrap_err();
        assert!(error.to_string().contains("cancelled by test"));
        Ok(())
    }

    #[test]
    fn orphan_sweep_uses_bounded_listing_and_keeps_referenced_objects() -> Result<()> {
        use std::{
            io::{BufRead, BufReader, Write},
            net::TcpListener,
        };
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let endpoint = format!("http://{}/", listener.local_addr()?);
        let server = std::thread::spawn(move || -> Result<()> {
            for method in ["GET", "DELETE"] {
                let (stream, _) = listener.accept()?;
                stream.set_read_timeout(Some(Duration::from_secs(5)))?;
                let mut input = BufReader::new(stream);
                let mut first = String::new();
                input.read_line(&mut first)?;
                ensure!(
                    first.starts_with(method),
                    "unexpected orphan fixture method"
                );
                loop {
                    let mut line = String::new();
                    input.read_line(&mut line)?;
                    if line == "\r\n" {
                        break;
                    }
                }
                if method == "GET" {
                    let target = first
                        .split_whitespace()
                        .nth(1)
                        .context("list target missing")?;
                    let url = reqwest::Url::parse(&format!("http://localhost{target}"))?;
                    ensure!(
                        url.query_pairs()
                            .any(|(name, value)| name == "max-keys" && value == "1000"),
                        "object listing was not bounded"
                    );
                    let xml = r#"<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><MaxKeys>1000</MaxKeys><Contents><Key>exports/gone.csv</Key><LastModified>2020-01-01T00:00:00Z</LastModified><ETag>test</ETag><Size>4</Size></Contents><Contents><Key>exports/keep.csv</Key><LastModified>2020-01-01T00:00:00Z</LastModified><ETag>test</ETag><Size>8</Size></Contents></ListBucketResult>"#;
                    let response = format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{xml}",
                        xml.len()
                    );
                    input.get_mut().write_all(response.as_bytes())?;
                } else {
                    ensure!(
                        first.contains("exports/gone.csv"),
                        "orphan sweep deleted a retained object"
                    );
                    input
                        .get_mut()
                        .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")?;
                }
            }
            Ok(())
        });
        let storage = ObjectStorage::new(
            &endpoint,
            "private-bucket",
            "test-access",
            "test-secret",
            "auto",
            true,
        )?;
        let removed = storage.cleanup_orphans(
            chrono::Utc::now() - chrono::Duration::hours(25),
            |key| Ok(key == "exports/keep.csv"),
            1,
        )?;
        assert_eq!(removed, 1);
        server
            .join()
            .map_err(|_| anyhow!("orphan storage fixture panicked"))??;
        Ok(())
    }

    #[test]
    #[ignore = "requires the disposable localhost MinIO fixture; run bash scripts/test-s3.sh"]
    fn live_s3_roundtrip_verifies_signature_upload_head_presign_list_and_delete() -> Result<()> {
        let endpoint =
            std::env::var("TEST_EXPORT_ENDPOINT").context("TEST_EXPORT_ENDPOINT is required")?;
        let parsed = reqwest::Url::parse(&endpoint)?;
        ensure!(
            parsed
                .host_str()
                .is_some_and(|host| matches!(host, "127.0.0.1" | "localhost" | "::1")),
            "live S3 integration fixture must be localhost"
        );
        let bucket =
            std::env::var("TEST_EXPORT_BUCKET").context("TEST_EXPORT_BUCKET is required")?;
        let access = std::env::var("TEST_EXPORT_ACCESS_KEY_ID")
            .context("TEST_EXPORT_ACCESS_KEY_ID is required")?;
        let secret = std::env::var("TEST_EXPORT_SECRET_ACCESS_KEY")
            .context("TEST_EXPORT_SECRET_ACCESS_KEY is required")?;
        let storage = ObjectStorage::new(&endpoint, &bucket, &access, &secret, "us-east-1", true)?;
        let directory = tempfile::tempdir()?;
        let artifact = directory.path().join("artifact.csv");
        let contents = b"identity,value\r\nexact-id,UNKNOWN\r\nempty,\r\n";
        std::fs::write(&artifact, contents)?;
        let sha256 = crate::exports::file_sha256(&artifact)?;
        let key = format!(
            "exports/live-integration/{}/artifact.csv",
            uuid::Uuid::new_v4()
        );
        let result = (|| -> Result<()> {
            storage.upload_guarded(&artifact, &key, &sha256, &|| Ok(()))?;
            storage.verify(&key, contents.len() as u64, &sha256)?;
            let url = storage.signed_download(&key, 60)?;
            let response = storage
                .client
                .get(&url)
                .send()
                .map_err(|_| anyhow!("local presigned download request failed"))?;
            ensure!(
                response.status().is_success(),
                "local MinIO rejected the presigned download signature"
            );
            ensure!(
                response.bytes()?.as_ref() == contents,
                "local S3 roundtrip changed artifact bytes"
            );
            let unsigned = storage
                .client
                .get(storage.bucket.object_url(&key)?)
                .send()
                .map_err(|_| anyhow!("local unsigned object request failed"))?;
            ensure!(
                unsigned.status() == reqwest::StatusCode::FORBIDDEN,
                "local S3 bucket unexpectedly permits anonymous downloads"
            );
            let tampered = url.replacen("X-Amz-Signature=", "X-Amz-Signature=0", 1);
            let invalid = storage
                .client
                .get(tampered)
                .send()
                .map_err(|_| anyhow!("local invalid signature request failed"))?;
            ensure!(
                invalid.status() == reqwest::StatusCode::FORBIDDEN,
                "local S3 fixture accepted an invalid signature"
            );
            let page = storage.list_page("exports/", None, 1000)?;
            ensure!(
                page.objects
                    .iter()
                    .any(|object| object.key == key && object.bytes == contents.len() as u64),
                "local S3 signed list did not include uploaded artifact"
            );
            storage.delete(&key)?;
            let missing = storage
                .client
                .get(storage.signed_download(&key, 60)?)
                .send()
                .map_err(|_| anyhow!("local deleted object request failed"))?;
            ensure!(
                missing.status() == reqwest::StatusCode::NOT_FOUND,
                "deleted local object is still available"
            );
            Ok(())
        })();
        let cleanup = storage.delete(&key);
        result?;
        cleanup?;
        Ok(())
    }
}

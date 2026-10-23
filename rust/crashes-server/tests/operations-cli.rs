use anyhow::{Context, Result};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
    path::Path,
    process::{Command, Output},
    thread::{self, JoinHandle},
    time::Duration,
};

const API_KEY: &str = "operations-cli-test-key-32-characters";

struct Request {
    method: String,
    path: String,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}

struct Response {
    status: &'static str,
    body: String,
    extra_headers: &'static str,
}

impl Response {
    fn json(value: Value) -> Self {
        Self {
            status: "200 OK",
            body: value.to_string(),
            extra_headers: "",
        }
    }
}

fn mock(responses: Vec<Response>) -> Result<(String, JoinHandle<Result<Vec<Request>>>)> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let url = format!("http://{}", listener.local_addr()?);
    let server = thread::spawn(move || {
        let mut requests = Vec::new();
        for response in responses {
            let (mut stream, _) = listener.accept()?;
            stream.set_read_timeout(Some(Duration::from_secs(5)))?;
            let mut reader = BufReader::new(&stream);
            let mut first = String::new();
            reader.read_line(&mut first)?;
            let mut parts = first.split_whitespace();
            let method = parts.next().context("HTTP method")?.to_owned();
            let path = parts.next().context("HTTP path")?.to_owned();
            let mut headers = BTreeMap::new();
            loop {
                let mut line = String::new();
                reader.read_line(&mut line)?;
                if line == "\r\n" {
                    break;
                }
                let (name, value) = line.split_once(':').context("HTTP header")?;
                headers.insert(name.to_ascii_lowercase(), value.trim().to_owned());
            }
            let length = headers
                .get("content-length")
                .map(|value| value.parse())
                .transpose()?
                .unwrap_or(0);
            let mut body = vec![0; length];
            reader.read_exact(&mut body)?;
            drop(reader);
            requests.push(Request {
                method,
                path,
                headers,
                body,
            });
            if response.status.is_empty() {
                continue;
            }
            write!(
                stream,
                "HTTP/1.1 {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n{}\r\n{}",
                response.status,
                response.body.len(),
                response.extra_headers,
                response.body
            )?;
        }
        Ok(requests)
    });
    Ok((url, server))
}

fn cli(url: &str, data_dir: &Path, arguments: &[&str]) -> Result<Output> {
    Ok(Command::new(env!("CARGO_BIN_EXE_crashes-server"))
        .arg("--data-dir")
        .arg(data_dir)
        .args(["--library", "/missing-native-library"])
        .args(["admin", "--url", url, "--timeout-seconds", "5"])
        .args(arguments)
        .env("API_KEY", API_KEY)
        .env_remove("CRASHES_ADMIN_URL")
        .env_remove("HTTP_PROXY")
        .env_remove("HTTPS_PROXY")
        .env_remove("ALL_PROXY")
        .env_remove("http_proxy")
        .env_remove("https_proxy")
        .env_remove("all_proxy")
        .output()?)
}

fn requests(server: JoinHandle<Result<Vec<Request>>>) -> Result<Vec<Request>> {
    server.join().expect("mock HTTP server panic")
}

#[test]
fn admin_uses_auth_and_proxy_prefix_without_opening_or_creating_data() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let data_dir = directory.path().join("must-not-be-created");
    let (url, server) = mock(vec![Response::json(json!([]))])?;
    let output = cli(&format!("{url}/admin/api"), &data_dir, &["jobs"])?;
    assert!(output.status.success(), "{:?}", output);
    assert_eq!(serde_json::from_slice::<Value>(&output.stdout)?, json!([]));
    assert!(
        !data_dir.exists(),
        "HTTP CLI must never open live data files"
    );
    let sent = requests(server)?.remove(0);
    assert_eq!(sent.method, "GET");
    assert_eq!(sent.path, "/admin/api/jobs");
    assert_eq!(sent.headers["x-api-key"], API_KEY);
    assert!(sent.body.is_empty());
    assert!(!String::from_utf8_lossy(&output.stderr).contains(API_KEY));
    Ok(())
}

#[test]
fn admin_commands_dispatch_only_the_explicit_http_operation() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for (arguments, method, path, body) in [
        (vec!["schedules"], "GET", "/jobs/schedules", None),
        (vec!["queue"], "GET", "/jobs/executions", None),
        (vec!["backup"], "POST", "/jobs/backup", Some(json!({}))),
        (vec!["backups"], "GET", "/jobs/backups", None),
        (
            vec!["executions"],
            "GET",
            "/jobs/executions/recent?limit=50",
            None,
        ),
        (
            vec!["executions", "--job", "9", "--limit", "4"],
            "GET",
            "/jobs/9/executions?limit=4",
            None,
        ),
        (vec!["run", "9"], "POST", "/jobs/9/execute", Some(json!({}))),
        (
            vec!["enable", "9"],
            "PUT",
            "/jobs/9",
            Some(json!({"enabled":true})),
        ),
        (
            vec!["disable", "9"],
            "PUT",
            "/jobs/9",
            Some(json!({"enabled":false})),
        ),
        (
            vec!["scheduler", "status"],
            "GET",
            "/jobs/scheduler/status",
            None,
        ),
        (
            vec!["scheduler", "start"],
            "POST",
            "/jobs/scheduler/start",
            Some(json!({})),
        ),
        (
            vec!["scheduler", "stop"],
            "POST",
            "/jobs/scheduler/stop",
            Some(json!({})),
        ),
    ] {
        let (url, server) = mock(vec![Response::json(json!({"accepted":true}))])?;
        let output = cli(&url, directory.path(), &arguments)?;
        assert!(output.status.success(), "{arguments:?}: {output:?}");
        let sent = requests(server)?.remove(0);
        assert_eq!(sent.method, method, "{arguments:?}");
        assert_eq!(sent.path, path, "{arguments:?}");
        assert_eq!(sent.headers["x-api-key"], API_KEY);
        if let Some(body) = body {
            assert_eq!(serde_json::from_slice::<Value>(&sent.body)?, body);
        } else {
            assert!(sent.body.is_empty());
        }
    }
    Ok(())
}

#[test]
fn status_reports_native_jobs_and_partial_failure_then_exits_nonzero() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (url, server) = mock(vec![
        Response::json(json!({"status":"healthy"})),
        Response {
            status: "503 Service Unavailable",
            body: json!({"detail":"database unavailable"}).to_string(),
            extra_headers: "",
        },
        Response::json(json!({"engine":"2.0.0"})),
        Response::json(json!({"endpoints":[]})),
        Response::json(json!({"scheduler_enabled":true})),
        Response::json(json!({"total_jobs":0})),
        Response::json(json!([{"id":"daily-source-refresh","enabled":true}])),
        Response::json(json!([{"status":"completed","kind":"ingestion"}])),
    ])?;
    let output = cli(&url, directory.path(), &["status"])?;
    assert!(!output.status.success());
    let report: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(report["ok"], false);
    assert_eq!(report["checks"]["health"]["status"], "healthy");
    assert!(
        report["checks"]["ready"]["error"]
            .as_str()
            .unwrap()
            .contains("503")
    );
    assert_eq!(
        report["checks"]["schedules"][0]["id"],
        "daily-source-refresh"
    );
    assert_eq!(report["checks"]["queue"][0]["status"], "completed");
    let sent = requests(server)?;
    assert_eq!(sent.len(), 8);
    assert!(sent.iter().all(|request| request.method == "GET"));
    Ok(())
}

#[test]
fn admin_errors_fail_without_following_redirects_or_exposing_the_key() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for (status, body, extra_headers, expected) in [
        (
            "401 Unauthorized",
            json!({"detail":format!("invalid key {API_KEY}")}).to_string(),
            "",
            "HTTP 401",
        ),
        (
            "302 Found",
            "{}".into(),
            "Location: http://127.0.0.1:1/capture-secret\r\n",
            "HTTP 302",
        ),
        ("200 OK", "<html>login</html>".into(), "", "invalid JSON"),
    ] {
        let (url, server) = mock(vec![Response {
            status,
            body,
            extra_headers,
        }])?;
        let output = cli(&url, directory.path(), &["jobs"])?;
        assert!(!output.status.success());
        let error = String::from_utf8(output.stderr)?;
        assert!(error.contains(expected), "{error}");
        assert!(!error.contains(API_KEY), "error must redact API_KEY");
        assert!(output.stdout.is_empty());
        assert_eq!(requests(server)?.len(), 1);
    }
    Ok(())
}

#[test]
fn backups_reads_completed_receipts_through_proxy_without_mutating_or_opening_data() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let data_dir = directory.path().join("must-not-be-created");
    let history = json!({"last_full_backup_at":1767225600,"backups":[{"schema_version":1,"id":"00000000-0000-4000-8000-000000000001","engine":"2.0.0","created_at":"2026-01-01T00:00:00Z","files":[{"name":"current.duckdb","bytes":1024,"sha256":"a".repeat(64)},{"name":"control.sqlite","bytes":512,"sha256":"b".repeat(64)}],"restore_tested":false}]});
    let (url, server) = mock(vec![Response::json(history.clone())])?;
    let output = cli(&format!("{url}/admin/api"), &data_dir, &["backups"])?;
    assert!(output.status.success(), "{output:?}");
    assert_eq!(serde_json::from_slice::<Value>(&output.stdout)?, history);
    assert!(!data_dir.exists());
    let sent = requests(server)?;
    assert_eq!(sent.len(), 1);
    assert_eq!(sent[0].method, "GET");
    assert_eq!(sent[0].path, "/admin/api/jobs/backups");
    assert_eq!(sent[0].headers["x-api-key"], API_KEY);
    Ok(())
}

#[test]
fn backup_ambiguous_failures_require_history_check_without_automatic_retry() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for (status, body, expected) in [
        ("", String::new(), "request failed"),
        (
            "500 Internal Server Error",
            "Internal Server Error".into(),
            "server or proxy returned an error",
        ),
        (
            "502 Bad Gateway",
            json!({"detail":format!("upstream disconnected {API_KEY}")}).to_string(),
            "upstream disconnected [redacted]",
        ),
        ("200 OK", "<html>proxy error</html>".into(), "invalid JSON"),
    ] {
        let (url, server) = mock(vec![Response {
            status,
            body,
            extra_headers: "",
        }])?;
        let output = cli(&url, directory.path(), &["backup"])?;
        assert!(!output.status.success());
        let error = String::from_utf8(output.stderr)?;
        assert!(error.contains(expected), "{error}");
        assert!(error.contains("Backup outcome is unknown"), "{error}");
        assert!(error.contains("admin backups"), "{error}");
        assert!(error.contains("Railway SSH"), "{error}");
        assert!(!error.contains(API_KEY), "{error}");
        assert!(output.stdout.is_empty());
        let sent = requests(server)?;
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0].method, "POST");
        assert_eq!(sent[0].path, "/jobs/backup");
    }
    Ok(())
}

#[test]
fn backup_authentication_rejections_keep_key_guidance_without_claiming_work_started() -> Result<()>
{
    let directory = tempfile::tempdir()?;
    for status in ["401 Unauthorized", "403 Forbidden"] {
        let (url, server) = mock(vec![Response {
            status,
            body: "authentication required".into(),
            extra_headers: "",
        }])?;
        let output = cli(&url, directory.path(), &["backup"])?;
        assert!(!output.status.success());
        let error = String::from_utf8(output.stderr)?;
        assert!(error.contains("verify the URL and API_KEY"), "{error}");
        assert!(!error.contains("outcome is unknown"), "{error}");
        assert!(!error.contains(API_KEY), "{error}");
        assert_eq!(requests(server)?.len(), 1);
    }
    Ok(())
}

fn schedule(enabled: bool, request: Value) -> Value {
    json!({"id":"daily-source-refresh","kind":"ingestion","request":request,"enabled":enabled,"interval_seconds":86400,"next_run_at":1900000000,"timeout_seconds":7200,"max_attempts":4})
}

#[test]
fn native_schedule_toggle_preserves_request_and_all_operational_settings() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for (action, original, enabled) in [
        ("schedule-enable", false, true),
        ("schedule-disable", true, false),
    ] {
        let original_request = json!({"endpoints":["crashes","people","vehicles"],"mode":"api","config":{"hold":true},"custom_audit":"retained"});
        let (url, server) = mock(vec![
            Response::json(json!([schedule(original, original_request.clone())])),
            Response::json(json!({"id":"daily-source-refresh","saved":true})),
        ])?;
        let output = cli(&url, directory.path(), &[action, "daily-source-refresh"])?;
        assert!(output.status.success(), "{output:?}");
        let sent = requests(server)?;
        assert_eq!(sent[0].method, "GET");
        assert_eq!(sent[0].path, "/jobs/schedules");
        assert_eq!(sent[1].method, "POST");
        assert_eq!(sent[1].path, "/jobs/schedules/daily-source-refresh");
        let body: Value = serde_json::from_slice(&sent[1].body)?;
        assert_eq!(body["endpoints"], original_request["endpoints"]);
        assert_eq!(body["config"], original_request["config"]);
        assert_eq!(body["custom_audit"], "retained");
        assert_eq!(body["enabled"], enabled);
        assert_eq!(body["next_run_at"], 1900000000);
        assert_eq!(body["interval_seconds"], 86400);
        assert_eq!(body["timeout_seconds"], 7200);
        assert_eq!(body["max_attempts"], 4);
    }
    Ok(())
}

#[test]
fn native_schedule_run_requires_enabled_unheld_schedule_and_running_scheduler() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for (enabled, request, scheduler, expected) in [
        (false, json!({}), None, "schedule is disabled"),
        (true, json!({"held":true}), None, "request is held"),
        (
            true,
            json!({"config":{"disabled":true}}),
            None,
            "request is held",
        ),
        (true, json!({}), Some(false), "scheduler is stopped"),
    ] {
        let mut responses = vec![Response::json(json!([schedule(enabled, request)]))];
        if let Some(scheduler) = scheduler {
            responses.push(Response::json(json!({"scheduler_enabled":scheduler})));
        }
        let (url, server) = mock(responses)?;
        let output = cli(
            &url,
            directory.path(),
            &["schedule-run", "daily-source-refresh"],
        )?;
        assert!(!output.status.success());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains(expected),
            "{output:?}"
        );
        assert!(
            requests(server)?
                .iter()
                .all(|request| request.method == "GET")
        );
    }
    Ok(())
}

#[test]
fn native_schedule_run_marks_due_and_reports_dispatch_without_claiming_completion() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (url, server) = mock(vec![
        Response::json(json!([schedule(
            true,
            json!({"endpoints":["crashes"],"mode":"api"})
        )])),
        Response::json(json!({"scheduler_enabled":true})),
        Response::json(json!({"id":"daily-source-refresh","saved":true})),
    ])?;
    let earliest = chrono::Utc::now().timestamp();
    let output = cli(
        &url,
        directory.path(),
        &["schedule-run", "daily-source-refresh"],
    )?;
    assert!(output.status.success(), "{output:?}");
    let receipt: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(receipt["dispatch"], "due");
    assert!(receipt.get("execution_id").is_none());
    let sent = requests(server)?;
    assert_eq!(sent[2].method, "POST");
    let body: Value = serde_json::from_slice(&sent[2].body)?;
    assert_eq!(body["enabled"], true);
    assert_eq!(body["interval_seconds"], 86400);
    assert_eq!(body["max_attempts"], 4);
    assert!(
        (earliest..=chrono::Utc::now().timestamp())
            .contains(&body["next_run_at"].as_i64().unwrap())
    );
    Ok(())
}

#[test]
fn invalid_operational_arguments_fail_before_sending_requests() -> Result<()> {
    let directory = tempfile::tempdir()?;
    for arguments in [
        vec!["executions", "--limit", "201"],
        vec!["run", "0"],
        vec!["schedule-run", "../scheduler/stop"],
        vec!["scheduler", "delete"],
    ] {
        let output = cli("http://127.0.0.1:1", directory.path(), &arguments)?;
        assert!(!output.status.success());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("request failed"));
    }
    for url in [
        "file:///data/current.duckdb",
        "http://operator:secret@127.0.0.1:1",
        "http://127.0.0.1:1?key=secret",
    ] {
        let output = cli(url, directory.path(), &["jobs"])?;
        assert!(!output.status.success());
        assert!(String::from_utf8_lossy(&output.stderr).contains("admin URL"));
        assert!(!String::from_utf8_lossy(&output.stderr).contains("operator:secret"));
    }
    Ok(())
}

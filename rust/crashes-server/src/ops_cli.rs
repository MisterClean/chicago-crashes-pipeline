//! HTTP operations for a running owner; this module never opens its database files.
use anyhow::{Context, Result, bail, ensure};
use clap::{Args, Subcommand};
use reqwest::{
    Method, Url,
    blocking::Client,
    header::{HeaderMap, HeaderValue},
    redirect::Policy,
};
use serde_json::{Value, json};
use std::{io::Read, time::Duration};

const MAX_RESPONSE_BYTES: u64 = 8 * 1024 * 1024;
const BACKUP_OUTCOME_UNKNOWN: &str = "Backup outcome is unknown; check `admin backups` before retrying. For long backups use the backend loopback API through Railway SSH.";

fn request_failure_context(method: &Method, path: &str, message: &str, backup: bool) -> String {
    let context = format!("{method} {path} {message}");
    if backup {
        format!("{context}; {BACKUP_OUTCOME_UNKNOWN}")
    } else {
        context
    }
}

#[derive(Args)]
pub(crate) struct Options {
    /// Backend or frontend admin proxy base URL (for example, https://host/admin/api).
    #[arg(
        long,
        env = "CRASHES_ADMIN_URL",
        default_value = "http://127.0.0.1:8003",
        global = true
    )]
    url: String,
    /// Deadline for each HTTP request, including a query waiting for the SQL lane.
    #[arg(long, default_value_t = 180, value_parser = clap::value_parser!(u64).range(1..=900), global = true)]
    timeout_seconds: u64,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Check health, readiness, runtime, source freshness, jobs and scheduler state.
    Status,
    /// List administrative ingestion jobs, including their enabled states and holds.
    Jobs,
    /// List native recurring ingestion schedules.
    Schedules,
    /// Make an enabled native schedule due on the next scheduler tick.
    ScheduleRun {
        #[arg(value_parser = schedule_id)]
        id: String,
    },
    /// Enable a native schedule, retaining its request, cadence and holds.
    ScheduleEnable {
        #[arg(value_parser = schedule_id)]
        id: String,
    },
    /// Disable a native schedule, retaining its request and cadence.
    ScheduleDisable {
        #[arg(value_parser = schedule_id)]
        id: String,
    },
    /// Show recent administrative ingestion execution history and publication receipts.
    Executions {
        #[arg(long, value_parser = clap::value_parser!(i64).range(1..))]
        job: Option<i64>,
        #[arg(long, default_value_t = 50, value_parser = clap::value_parser!(u16).range(1..=200))]
        limit: u16,
    },
    /// Show the durable worker queue/history (up to 100 records, including exports).
    Queue,
    /// Create and verify a paired DuckDB/SQLite backup through the running owner.
    Backup,
    /// List completed paired backup receipts, including configured offsite publication.
    Backups,
    /// Queue one administrative ingestion job; publication guards still apply.
    Run {
        #[arg(value_parser = clap::value_parser!(i64).range(1..))]
        job: i64,
    },
    /// Enable an administrative ingestion job without changing its schedule or hold.
    Enable {
        #[arg(value_parser = clap::value_parser!(i64).range(1..))]
        job: i64,
    },
    /// Disable future dispatch of an administrative ingestion job.
    Disable {
        #[arg(value_parser = clap::value_parser!(i64).range(1..))]
        job: i64,
    },
    /// Read or change the durable gate controlling future automatic dispatch.
    Scheduler {
        #[command(subcommand)]
        action: SchedulerAction,
    },
}

#[derive(Subcommand)]
enum SchedulerAction {
    Status,
    Start,
    /// Existing queued and running work continues.
    Stop,
}

fn schedule_id(id: &str) -> std::result::Result<String, String> {
    if !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
    {
        Ok(id.into())
    } else {
        Err("schedule id must be 1..128 letters, digits, hyphens or underscores".into())
    }
}

struct Backend {
    client: Client,
    base: Url,
    api_key: String,
}

impl Backend {
    fn new(options: &Options) -> Result<Self> {
        let mut base = Url::parse(&options.url).context("invalid admin URL")?;
        ensure!(
            matches!(base.scheme(), "http" | "https") && base.host_str().is_some(),
            "admin URL must be an HTTP or HTTPS URL with a host"
        );
        ensure!(
            base.username().is_empty()
                && base.password().is_none()
                && base.query().is_none()
                && base.fragment().is_none(),
            "admin URL must not contain credentials, a query or a fragment; provide the key in API_KEY"
        );
        base.set_path(&format!("{}/", base.path().trim_end_matches('/')));
        let api_key = match std::env::var("API_KEY") {
            Ok(value) => value,
            Err(std::env::VarError::NotPresent) => String::new(),
            Err(std::env::VarError::NotUnicode(_)) => bail!("API_KEY must be valid Unicode"),
        };
        let mut headers = HeaderMap::new();
        if !api_key.is_empty() {
            let mut key = HeaderValue::from_str(&api_key)
                .context("API_KEY cannot be represented as an HTTP header")?;
            key.set_sensitive(true);
            headers.insert("x-api-key", key);
        }
        let client = Client::builder()
            .default_headers(headers)
            .timeout(Duration::from_secs(options.timeout_seconds))
            .connect_timeout(Duration::from_secs(options.timeout_seconds.min(10)))
            // A frontend login/redirect must not forward administrative credentials.
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .build()
            .context("build admin HTTP client")?;
        Ok(Self {
            client,
            base,
            api_key,
        })
    }

    fn request(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        let backup = method == Method::POST && path == "jobs/backup";
        let url = self.base.join(path).context("build admin request URL")?;
        let mut request = self.client.request(method.clone(), url);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request
            .send()
            .with_context(|| request_failure_context(&method, path, "request failed", backup))?;
        let status = response.status();
        let mut bytes = Vec::new();
        response
            .take(MAX_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes)
            .with_context(|| {
                request_failure_context(&method, path, "response could not be read", backup)
            })?;
        ensure!(
            bytes.len() as u64 <= MAX_RESPONSE_BYTES,
            "{}",
            request_failure_context(&method, path, "response exceeded 8 MiB", backup)
        );
        if !status.is_success() {
            let value = serde_json::from_slice::<Value>(&bytes).ok();
            let detail = value.as_ref().and_then(|value| value["detail"].as_str());
            let detail = detail.unwrap_or(if matches!(status.as_u16(), 401 | 403) {
                "authentication failed; verify the URL and API_KEY"
            } else {
                "server or proxy returned an error"
            });
            let detail = if self.api_key.is_empty() {
                detail.to_owned()
            } else {
                detail.replace(&self.api_key, "[redacted]")
            };
            bail!(
                "{method} {path}: HTTP {status}: {}",
                if backup && status.is_server_error() {
                    format!(
                        "{}; {BACKUP_OUTCOME_UNKNOWN}",
                        detail.chars().take(1000).collect::<String>()
                    )
                } else {
                    detail.chars().take(1000).collect::<String>()
                }
            );
        }
        serde_json::from_slice(&bytes).with_context(|| {
            request_failure_context(&method, path, "returned invalid JSON", backup)
        })
    }

    fn update_schedule(&self, id: &str, enabled: Option<bool>) -> Result<Value> {
        let schedules = self.request(Method::GET, "jobs/schedules", None)?;
        let record = schedules
            .as_array()
            .context("backend schedules response must be an array")?
            .iter()
            .find(|schedule| schedule["id"].as_str() == Some(id))
            .with_context(|| format!("native schedule {id} not found"))?;
        let schedule: crate::control::Schedule =
            serde_json::from_value(record.clone()).context("invalid native schedule response")?;
        ensure!(
            schedule.kind == "ingestion",
            "only native ingestion schedules can be updated"
        );
        let mut request = schedule.request;
        ensure!(
            request.is_object(),
            "native schedule request must be an object"
        );
        let next_run_at = if enabled.is_some() {
            schedule.next_run_at
        } else {
            ensure!(
                schedule.enabled,
                "native schedule is disabled; enable it explicitly first"
            );
            for key in ["held", "hold", "disabled"] {
                ensure!(
                    request[key] != true && request["config"][key] != true,
                    "native schedule request is held or disabled"
                );
            }
            let scheduler = self.request(Method::GET, "jobs/scheduler/status", None)?;
            ensure!(
                scheduler["scheduler_enabled"] == true,
                "scheduler is stopped; start it explicitly before making a native schedule due"
            );
            chrono::Utc::now().timestamp()
        };
        request["interval_seconds"] = json!(schedule.interval_seconds);
        request["timeout_seconds"] = json!(schedule.timeout_seconds);
        request["max_attempts"] = json!(schedule.max_attempts);
        request["next_run_at"] = json!(next_run_at);
        request["enabled"] = json!(enabled.unwrap_or(schedule.enabled));
        let mut receipt =
            self.request(Method::POST, &format!("jobs/schedules/{id}"), Some(request))?;
        if enabled.is_none() {
            receipt["dispatch"] = json!("due");
            receipt["message"] = json!(
                "Schedule is due; check queue for actual execution. Its next interval is measured from this requested time."
            );
        }
        Ok(receipt)
    }
}

pub(crate) fn run(options: &Options) -> Result<()> {
    let backend = Backend::new(options)?;
    let value = match &options.command {
        Command::Status => {
            let mut checks = serde_json::Map::new();
            let mut healthy = true;
            for (name, path) in [
                ("health", "health"),
                ("ready", "ready"),
                ("runtime", "runtime/info"),
                ("sync", "sync/status"),
                ("scheduler", "jobs/scheduler/status"),
                ("jobs", "jobs/summary"),
                ("schedules", "jobs/schedules"),
                ("queue", "jobs/executions"),
            ] {
                let value = match backend.request(Method::GET, path, None) {
                    Ok(value) => value,
                    Err(error) => {
                        healthy = false;
                        json!({"error":format!("{error:#}")})
                    }
                };
                checks.insert(name.into(), value);
            }
            println!(
                "{}",
                serde_json::to_string_pretty(&json!({"ok":healthy,"checks":checks}))?
            );
            ensure!(healthy, "one or more backend status checks failed");
            return Ok(());
        }
        Command::Jobs => backend.request(Method::GET, "jobs", None)?,
        Command::Schedules => backend.request(Method::GET, "jobs/schedules", None)?,
        Command::ScheduleRun { id } => backend.update_schedule(id, None)?,
        Command::ScheduleEnable { id } => backend.update_schedule(id, Some(true))?,
        Command::ScheduleDisable { id } => backend.update_schedule(id, Some(false))?,
        Command::Executions { job, limit } => {
            let path = match job {
                Some(job) => format!("jobs/{job}/executions?limit={limit}"),
                None => format!("jobs/executions/recent?limit={limit}"),
            };
            backend.request(Method::GET, &path, None)?
        }
        Command::Queue => backend.request(Method::GET, "jobs/executions", None)?,
        Command::Backup => backend.request(Method::POST, "jobs/backup", Some(json!({})))?,
        Command::Backups => backend.request(Method::GET, "jobs/backups", None)?,
        Command::Run { job } => backend.request(
            Method::POST,
            &format!("jobs/{job}/execute"),
            Some(json!({})),
        )?,
        Command::Enable { job } | Command::Disable { job } => backend.request(
            Method::PUT,
            &format!("jobs/{job}"),
            Some(json!({"enabled":matches!(options.command, Command::Enable { .. })})),
        )?,
        Command::Scheduler { action } => {
            let (method, action) = match action {
                SchedulerAction::Status => (Method::GET, "status"),
                SchedulerAction::Start => (Method::POST, "start"),
                SchedulerAction::Stop => (Method::POST, "stop"),
            };
            let body = if method == Method::POST {
                Some(json!({}))
            } else {
                None
            };
            backend.request(method, &format!("jobs/scheduler/{action}"), body)?
        }
    };
    println!("{}", serde_json::to_string_pretty(&value)?);
    Ok(())
}

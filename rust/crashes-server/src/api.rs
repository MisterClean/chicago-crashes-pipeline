//! HTTP compatibility boundary. Public reads never grant operational privileges.
use crate::{
    control::ControlStore,
    db::Database,
    layers,
    queries::{self, DateRange, LocationRequest},
    storage::ObjectStorage,
};
use anyhow::{Context, Result, anyhow, ensure};
use axum::{
    Json, Router,
    body::Body,
    extract::{DefaultBodyLimit, Multipart, Request, State},
    http::{Method, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{any, post},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};
use subtle::ConstantTimeEq;
use tokio::sync::Semaphore;
use tokio_util::io::ReaderStream;

#[derive(Clone)]
pub struct AppState {
    pub db: Arc<Database>,
    pub control: ControlStore,
    pub directory: PathBuf,
    pub api_key: Arc<String>,
    pub production: bool,
    pub storage: Option<Arc<ObjectStorage>>,
    pub admission: Arc<Semaphore>,
    pub profiling_data: bool,
    pub pubcache: Arc<crate::cache::ResponseCache>,
}

#[derive(Clone, Debug)]
struct ApiError(StatusCode, String);
impl ApiError {
    fn bad(error: impl std::fmt::Display) -> Self {
        Self(StatusCode::BAD_REQUEST, error.to_string())
    }
}
impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.1.fmt(f)
    }
}
impl std::error::Error for ApiError {}
impl From<anyhow::Error> for ApiError {
    fn from(error: anyhow::Error) -> Self {
        if let Some(error) = error.downcast_ref::<Self>() {
            return error.clone();
        }
        if let Some(error) = error.downcast_ref::<crate::compat::Error>() {
            return Self(
                StatusCode::from_u16(error.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                error.detail.clone(),
            );
        }
        let message = error.to_string();
        if message == "DuckDB statement execution deadline exceeded" {
            return Self(
                StatusCode::GATEWAY_TIMEOUT,
                "Query execution deadline exceeded".into(),
            );
        }

        if message == "queue full; retry later" {
            return Self(
                StatusCode::TOO_MANY_REQUESTS,
                "Work queue is full; retry later".into(),
            );
        }
        if [
            "Unknown place type:",
            "Layer not found or inactive:",
            "Feature not found in layer",
            "Place not found",
            "Place label not found",
            "Job not found",
            "Export not found",
            "Route not found",
        ]
        .iter()
        .any(|prefix| message.starts_with(prefix))
        {
            return Self(StatusCode::NOT_FOUND, "Resource not found".into());
        }
        if message == "Selection geometry must be valid and nonempty"
            || message == "Selection geometry must be Polygon or MultiPolygon"
            || message == "upload requires 1..100000 features"
            || message == "invalid upload geometry"
            || message == "label field absent from upload"
            || message == "invalid layer sort_type"
        {
            return Self::bad(message);
        }
        tracing::error!(error=%error,"request failed");
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Request could not be completed".into(),
        )
    }
}
impl From<std::io::Error> for ApiError {
    fn from(error: std::io::Error) -> Self {
        anyhow::Error::from(error).into()
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = self.0;
        let mut response = (status, Json(json!({"detail":self.1}))).into_response();
        if status == StatusCode::TOO_MANY_REQUESTS || status == StatusCode::SERVICE_UNAVAILABLE {
            response
                .headers_mut()
                .insert(header::RETRY_AFTER, header::HeaderValue::from_static("1"));
        }
        response
    }
}

fn public(method: &Method, path: &str) -> bool {
    (*method == Method::GET
        && matches!(
            path,
            "" | "/"
                | "/health"
                | "/ready"
                | "/version"
                | "/sync/status"
                | "/admin"
                | "/admin/app.js"
                | "/admin/styles.css"
        ))
        || (*method == Method::GET
            && (path.starts_with("/dashboard/") || path.starts_with("/places/")))
        || (*method == Method::POST && path == "/dashboard/location-report")
}
fn local_signature(key: &str, id: &str, expires: i64) -> Result<String> {
    use hmac::{Hmac, Mac};
    let mut mac = Hmac::<sha2::Sha256>::new_from_slice(key.as_bytes())
        .map_err(|_| anyhow!("local signature key invalid"))?;
    mac.update(format!("local-export:{id}:{expires}").as_bytes());
    Ok(hex::encode(mac.finalize().into_bytes()))
}

fn artifact_signature(state: &AppState, request: &Request) -> bool {
    use hmac::{Hmac, Mac};
    let parts = request
        .uri()
        .path()
        .split('/')
        .filter(|v| !v.is_empty())
        .collect::<Vec<_>>();
    if request.method() != Method::GET || !matches!(parts.as_slice(), ["exports", _, "artifact"]) {
        return false;
    }
    let query = request
        .uri()
        .query()
        .and_then(|q| reqwest::Url::parse(&format!("http://local/?{q}")).ok());
    let query = query
        .map(|u| u.query_pairs().into_owned().collect::<BTreeMap<_, _>>())
        .unwrap_or_default();
    let Some(expires) = query.get("expires").and_then(|v| v.parse::<i64>().ok()) else {
        return false;
    };
    let now = chrono::Utc::now().timestamp();
    if expires <= now || expires > now + 300 {
        return false;
    }
    let Some(token) = query.get("token").and_then(|v| hex::decode(v).ok()) else {
        return false;
    };
    let Ok(mut mac) = Hmac::<sha2::Sha256>::new_from_slice(state.api_key.as_bytes()) else {
        return false;
    };
    mac.update(format!("local-export:{}:{expires}", parts[1]).as_bytes());
    mac.verify_slice(&token).is_ok()
}

async fn authorize(State(state): State<AppState>, request: Request, next: Next) -> Response {
    if !public(request.method(), request.uri().path().trim_end_matches('/'))
        && !state.api_key.is_empty()
        && !artifact_signature(&state, &request)
    {
        let actual = request
            .headers()
            .get("x-api-key")
            .map(|x| x.as_bytes())
            .unwrap_or_default();
        let expected = state.api_key.as_bytes();
        if actual.len() != expected.len() || !bool::from(actual.ct_eq(expected)) {
            return (
                StatusCode::UNAUTHORIZED,
                Json(json!({"detail":"A valid API key is required"})),
            )
                .into_response();
        }
    }
    next.run(request).await
}

/// Install explicit public routes and bounded authenticated administrative work.
pub fn router(state: AppState) -> Router {
    crate::compat::start_clock();
    let routes = Router::new()
        .route("/", any(dispatch))
        .route("/{*path}", any(dispatch))
        .route("/spatial/layers", post(upload).get(dispatch))
        .route("/spatial/layers/preview-fields", post(upload))
        .route("/spatial/layers/{id}/replace", post(upload))
        .layer(DefaultBodyLimit::max(64 * 1024 * 1024))
        .layer(middleware::from_fn_with_state(state.clone(), authorize))
        .layer(tower_http::trace::TraceLayer::new_for_http().make_span_with(|request:&Request|tracing::info_span!("http_request",method=%request.method(),path=%request.uri().path())))
        .with_state(state);
    // The embedded UI uses this path both directly and through Next's /admin proxy.
    Router::new()
        .nest("/admin/api", routes.clone())
        .merge(routes)
}

async fn blocking<T: Send + 'static>(
    state: &AppState,
    f: impl FnOnce() -> Result<T> + Send + 'static,
) -> std::result::Result<T, ApiError> {
    // Reject excess work before allocating another blocking thread or wait queue.
    let permit = state.admission.clone().try_acquire_owned().map_err(|_| {
        ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Service is busy; retry later".into(),
        )
    })?;
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        f()
    })
    .await
    .map_err(|_| ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Worker failed".into()))?
    .map_err(Into::into)
}

async fn dispatch(
    State(state): State<AppState>,
    request: Request,
) -> std::result::Result<Response, ApiError> {
    let raw_path = request.uri().path();
    let path = raw_path
        .split('/')
        .map(|part| {
            let decoded = percent_encoding::percent_decode_str(part)
                .decode_utf8()
                .map_err(ApiError::bad)?;
            if decoded.contains('/') || decoded.contains('\0') {
                return Err(ApiError::bad("Invalid path segment"));
            }
            Ok(decoded.into_owned())
        })
        .collect::<std::result::Result<Vec<_>, ApiError>>()?
        .join("/")
        .trim_end_matches('/')
        .to_owned();
    let method = request.method().clone();
    let segments = path
        .split('/')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();
    if let ["places", "types", kind, "items", rest @ ..] = segments.as_slice() {
        validate_place(kind, rest.first().copied())?;
    }
    if method == Method::POST && path == "/dashboard/location-report/export" {
        return Err(ApiError(
            StatusCode::GONE,
            "Inline exports are retired; submit to POST /exports".into(),
        ));
    }

    let query: BTreeMap<String, String> = request
        .uri()
        .query()
        .map(|q| {
            reqwest::Url::parse(&format!("http://local/?{q}")).map(|u| {
                u.query_pairs()
                    .map(|(k, v)| (k.into_owned(), v.into_owned()))
                    .collect()
            })
        })
        .transpose()
        .map_err(ApiError::bad)?
        .unwrap_or_default();
    if method == Method::GET && (path.is_empty() || path == "/health" || path == "/version") {
        return Ok(Json(json!({"status":"healthy","backend":"rust","source_sha256":env!("CRASHES_SOURCE_SHA256"),"duckdb":"2.0.0","version":env!("CARGO_PKG_VERSION"),"profiling_data":state.profiling_data})).into_response());
    }
    if method == Method::GET {
        let asset = match path.as_str() {
            "/admin" => Some((
                "text/html; charset=utf-8",
                include_str!("../static/admin/index.html"),
            )),
            "/admin/app.js" => Some((
                "text/javascript; charset=utf-8",
                include_str!("../static/admin/app.js"),
            )),
            "/admin/styles.css" => Some((
                "text/css; charset=utf-8",
                include_str!("../static/admin/styles.css"),
            )),
            _ => None,
        };
        if let Some((kind, content)) = asset {
            return Ok((
                [
                    (header::CONTENT_TYPE, kind),
                    (header::CACHE_CONTROL, "no-cache"),
                ],
                content,
            )
                .into_response());
        }
    }
    let bytes = axum::body::to_bytes(request.into_body(), 1_048_576)
        .await
        .map_err(|_| {
            ApiError(
                StatusCode::PAYLOAD_TOO_LARGE,
                "JSON request exceeds 1 MiB".into(),
            )
        })?;
    let body: Value = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).map_err(ApiError::bad)?
    };
    if method == Method::GET && path.starts_with("/exports/") && path.ends_with("/artifact") {
        let id = path.split('/').nth(2).unwrap_or_default();
        let job = state
            .control
            .get(id)?
            .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Export not found".into()))?;
        if job.status == "expired" || job.expires_at <= chrono::Utc::now().timestamp() {
            return Err(ApiError(
                StatusCode::GONE,
                "Export is unavailable or expired".into(),
            ));
        }
        if job.status != "completed" {
            return Err(ApiError(StatusCode::CONFLICT, "Export is not ready".into()));
        }
        if state.storage.is_some() {
            return Err(ApiError(
                StatusCode::GONE,
                "Use the signed object download link".into(),
            ));
        }
        let file = PathBuf::from(job.artifact_path.context("artifact pointer missing")?);
        let root = state
            .directory
            .join("exports")
            .canonicalize()
            .map_err(|_| ApiError(StatusCode::GONE, "Export artifact is unavailable".into()))?;
        let canonical = file
            .canonicalize()
            .map_err(|_| ApiError(StatusCode::GONE, "Export artifact is unavailable".into()))?;
        if !canonical.starts_with(root) {
            return Err(anyhow!("artifact outside private export directory").into());
        }
        let opened = tokio::fs::File::open(&canonical)
            .await
            .map_err(anyhow::Error::from)?;
        let name = file
            .file_name()
            .context("export filename")?
            .to_string_lossy();
        return Ok((
            [
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"{name}\""),
                ),
                (
                    header::CONTENT_TYPE,
                    if name.ends_with(".zip") {
                        "application/zip".into()
                    } else {
                        "text/csv".into()
                    },
                ),
                (header::CACHE_CONTROL, "private, no-store".into()),
            ],
            Body::from_stream(ReaderStream::new(opened)),
        )
            .into_response());
    }
    let dates = DateRange {
        start_date: query.get("start_date").cloned(),
        end_date: query.get("end_date").cloned(),
    };
    queries::date_predicate(&dates).map_err(ApiError::bad)?;
    if method == Method::GET {
        match path.as_str() {
            "/dashboard/trends/weekly" => {
                number(&query, "weeks", 52, 104)?;
            }
            "/dashboard/crashes/geojson" => {
                number(&query, "limit", 10000, 50000)?;
            }
            "/dashboard/crashes/by-cause" => {
                number(&query, "limit", 10, 50)?;
            }
            _ => {}
        }
    }

    let body = if method == Method::POST
        && matches!(
            path.as_str(),
            "/dashboard/location-report" | "/exports" | "/dashboard/location-report/export"
        ) {
        let mut location = body.clone();
        if path != "/dashboard/location-report" {
            let datasets = body
                .get("datasets")
                .context(ApiError::bad("datasets required"))?;
            let datasets: Vec<String> =
                serde_json::from_value(datasets.clone()).map_err(ApiError::bad)?;
            if datasets.is_empty() || datasets.len() > 4 {
                return Err(ApiError::bad("choose 1..4 datasets"));
            }
            let mut unique = std::collections::HashSet::new();
            for dataset in &datasets {
                crate::exports::export_columns(dataset).map_err(ApiError::bad)?;
                if !unique.insert(dataset) {
                    return Err(ApiError::bad("duplicate datasets"));
                }
            }
            if let Some(object) = location.as_object_mut() {
                object.remove("datasets");
            }
        }
        let location: LocationRequest = serde_json::from_value(location).map_err(ApiError::bad)?;
        if location.resolved_area.is_some() {
            return Err(ApiError::bad("resolved_area is internal"));
        }
        location.validate().map_err(ApiError::bad)?;
        if let Some(kind) = &location.place_type {
            validate_place(kind, location.place_id.as_deref())?;
        }

        body
    } else {
        body
    };
    if cacheable(&method, &path) {
        return cached_read(state, method, path, query, dates, body).await;
    }
    let state_for_work = state.clone();
    let mut value = blocking(&state, move || {
        execute(&state_for_work, &method, &path, &query, &dates, &body)
    })
    .await?;
    let status = if value.get("_accepted") == Some(&Value::Bool(true)) {
        StatusCode::ACCEPTED
    } else {
        StatusCode::OK
    };
    if let Some(object) = value.as_object_mut() {
        object.remove("_accepted");
    }
    Ok((status, Json(value)).into_response())
}

fn cacheable(method: &Method, path: &str) -> bool {
    if *method == Method::POST {
        return path == "/dashboard/location-report";
    }
    if *method != Method::GET {
        return false;
    }
    if matches!(
        path,
        "/dashboard/stats"
            | "/dashboard/trends/weekly"
            | "/dashboard/crashes/geojson"
            | "/dashboard/crashes/by-hour"
            | "/dashboard/crashes/by-cause"
    ) {
        return true;
    }
    let parts = path
        .split('/')
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>();
    matches!(
        parts.as_slice(),
        ["places", "types"]
            | ["places", "types", _, "items"]
            | ["places", "types", _, "items", _, "geometry"]
    )
}

fn json_bytes(bytes: Arc<[u8]>, status: &'static str) -> Response {
    (
        [
            (
                header::CONTENT_TYPE,
                header::HeaderValue::from_static("application/json"),
            ),
            (
                header::CACHE_CONTROL,
                header::HeaderValue::from_static("no-store"),
            ),
            (
                header::HeaderName::from_static("x-cache"),
                header::HeaderValue::from_static(status),
            ),
        ],
        Body::from(axum::body::Bytes::from_owner(bytes)),
    )
        .into_response()
}

async fn cached_read(
    state: AppState,
    method: Method,
    path: String,
    query: BTreeMap<String, String>,
    dates: DateRange,
    body: Value,
) -> std::result::Result<Response, ApiError> {
    let enabled = state.pubcache.enabled();
    // Report partial-month flags and relative weekly windows have wall-clock context.
    let context = if path == "/dashboard/location-report"
        || (path == "/dashboard/trends/weekly"
            && dates.start_date.is_none()
            && dates.end_date.is_none())
    {
        chrono::Utc::now()
            .with_timezone(&chrono_tz::America::Chicago)
            .format("%Y-%m-%dT%H")
            .to_string()
    } else {
        String::new()
    };
    let mut before = state.db.generation();
    let mut key =
        crate::cache::ResponseCache::key(before, method.as_str(), &path, &query, &body, &context)?;
    if enabled
        && let Some(bytes) = state.pubcache.get(&key)
        && before == state.db.generation()
    {
        state.pubcache.record_hit();
        return Ok(json_bytes(bytes, "HIT"));
    }
    let _fill = if enabled {
        Some(state.pubcache.fill_guard().await.map_err(|_| {
            ApiError(
                StatusCode::SERVICE_UNAVAILABLE,
                "Service is busy; retry later".into(),
            )
        })?)
    } else {
        None
    };
    // Another public miss may have filled this key while we waited. Mutations
    // invalidate by epoch without querying DuckDB or blocking cache hits on SQL.
    before = state.db.generation();
    key =
        crate::cache::ResponseCache::key(before, method.as_str(), &path, &query, &body, &context)?;
    if enabled {
        if let Some(bytes) = state.pubcache.get(&key)
            && before == state.db.generation()
        {
            state.pubcache.record_hit();
            return Ok(json_bytes(bytes, "HIT"));
        }
        state.pubcache.record_miss();
    }
    let state_for_work = state.clone();
    let value = blocking(&state, move || {
        execute(&state_for_work, &method, &path, &query, &dates, &body)
    })
    .await?;
    let bytes: Arc<[u8]> = serde_json::to_vec(&value)
        .map_err(anyhow::Error::from)?
        .into();
    if enabled && before == state.db.generation() {
        state.pubcache.insert(key, bytes.clone());
    }
    Ok(json_bytes(bytes, if enabled { "MISS" } else { "BYPASS" }))
}

fn execute(
    state: &AppState,
    method: &Method,
    path: &str,
    query: &BTreeMap<String, String>,
    dates: &DateRange,
    body: &Value,
) -> Result<Value> {
    let db = &state.db;
    if let Some(response) =
        crate::compat::dispatch(db, &state.control, method.as_str(), path, body, query)
    {
        return response;
    }
    if let Some(result) = crate::admin::dispatch(&state.control, method.as_str(), path, body, query)
    {
        return result;
    }
    let parts: Vec<_> = path.split('/').filter(|p| !p.is_empty()).collect();
    if *method == Method::GET {
        return match parts.as_slice() {
            ["runtime", "info"] => {
                let settings=db.query("SELECT current_setting('memory_limit') AS memory_limit,current_setting('threads') AS sql_threads",&[])?.into_iter().next().context("runtime settings missing")?;
                Ok(
                    json!({"backend":"rust","source_sha256":env!("CRASHES_SOURCE_SHA256"),"engine":"2.0.0","resources":{"pid":std::process::id()},"memory_limit":settings["memory_limit"],"sql_threads":settings["sql_threads"],"serialized":true,"profiling_data":state.profiling_data,"public_cache":state.pubcache.stats()}),
                )
            }
            ["ready"] => {
                for table in [
                    "crashes",
                    "crash_people",
                    "crash_vehicles",
                    "vision_zero_fatalities",
                    "spatial_layers",
                    "spatial_layer_features",
                ] {
                    db.query(&format!("SELECT 1 FROM {table} LIMIT 1"), &[])?;
                }
                Ok(json!({"status":"ready","profiling_data":state.profiling_data}))
            }
            ["dashboard", "stats"] => queries::dashboard_stats(db, dates),
            ["dashboard", "trends", "weekly"] => {
                queries::weekly_trends(db, dates, number(query, "weeks", 52, 104)?)
            }
            ["dashboard", "crashes", "geojson"] => {
                queries::crashes_geojson(db, dates, number(query, "limit", 10000, 50000)?)
            }
            ["dashboard", "crashes", "by-hour"] => queries::crashes_by_hour(db, dates),
            ["dashboard", "crashes", "by-cause"] => {
                queries::crashes_by_cause(db, dates, number(query, "limit", 10, 50)?)
            }
            ["places", "types"] => queries::place_types(db),
            ["places", "types", kind, "items"] => queries::places(db, kind),
            ["places", "types", kind, "items", id, "geometry"] => {
                queries::place_geometry(db, kind, id)
            }
            ["spatial", "layers"] => queries::layers(db),
            ["spatial", "layers", id] => layer_metadata(db, id.parse().map_err(ApiError::bad)?),
            ["spatial", "layers", id, "geojson"] => {
                queries::layer_geojson(db, id.parse().map_err(ApiError::bad)?)
            }
            ["exports"] => Ok(json!(
                state
                    .control
                    .list(Some("export"), 100)?
                    .iter()
                    .map(|j| j.public_json())
                    .collect::<Vec<_>>()
            )),
            ["exports", id] => Ok(state
                .control
                .get(id)?
                .context("Export not found")?
                .public_json()),
            ["exports", id, "download"] => {
                let job = state.control.get(id)?.context("Export not found")?;
                let now = chrono::Utc::now().timestamp();
                if job.status == "expired" || job.expires_at <= now {
                    return Err(ApiError(StatusCode::GONE, "Export expired".into()).into());
                }
                if job.status != "completed" {
                    return Err(ApiError(StatusCode::CONFLICT, "Export is not ready".into()).into());
                }
                let pointer = job.artifact_path.context("artifact pointer missing")?;
                let url = if let Some(storage) = &state.storage {
                    storage.signed_download(&pointer, (job.expires_at - now).min(300) as u64)?
                } else {
                    {
                        let expires = job.expires_at.min(now + 300);
                        format!(
                            "/api/exports/{id}/artifact?expires={expires}&token={}",
                            local_signature(&state.api_key, id, expires)?
                        )
                    }
                };
                Ok(json!({"url":url}))
            }
            ["jobs"] | ["jobs", "executions"] => Ok(json!(
                state
                    .control
                    .list(None, 100)?
                    .iter()
                    .map(|j| j.public_json())
                    .collect::<Vec<_>>()
            )),
            ["jobs", "schedules"] => Ok(serde_json::to_value(state.control.schedules()?)?),
            ["jobs", id] => Ok(state
                .control
                .get(id)?
                .context("Job not found")?
                .public_json()),
            _ => Err(anyhow!("Route not found")),
        };
    }
    if *method == Method::POST {
        match parts.as_slice() {
            ["dashboard", "location-report"] => {
                return queries::location_report(db, &serde_json::from_value(body.clone())?);
            }
            ["exports"] => {
                let mut value = body.clone();
                let datasets = value
                    .as_object_mut()
                    .context("object required")?
                    .remove("datasets")
                    .context("datasets required")?;
                let datasets: Vec<String> = serde_json::from_value(datasets)?;
                ensure!(
                    !datasets.is_empty() && datasets.len() <= 4,
                    "choose 1..4 datasets"
                );
                let mut unique = std::collections::HashSet::new();
                for d in &datasets {
                    crate::exports::export_columns(d)?;
                    ensure!(unique.insert(d), "duplicate datasets");
                }
                let mut request: LocationRequest = serde_json::from_value(value)?;
                request.resolved_area = Some(queries::selected_crashes(db, &request)?.query_area);
                let mut result = state
                    .control
                    .enqueue(&json!({"location":request,"datasets":datasets}))?
                    .public_json();
                result["_accepted"] = json!(true);
                return Ok(result);
            }
            ["exports", id, "cancel"] | ["jobs", id, "cancel"] => {
                return Ok(state
                    .control
                    .cancel(id)?
                    .context("Job not found")?
                    .public_json());
            }
            ["jobs", "schedules", id] => {
                state.control.put_schedule(
                    id,
                    body,
                    body["next_run_at"]
                        .as_i64()
                        .unwrap_or_else(|| chrono::Utc::now().timestamp()),
                    body["enabled"].as_bool().unwrap_or(false),
                )?;
                return Ok(json!({"id":id,"saved":true}));
            }
            ["jobs", "data", "delete"] => {
                let table = body["table_name"]
                    .as_str()
                    .context(ApiError::bad("table_name required"))?;
                ensure!(
                    [
                        "crashes",
                        "crash_people",
                        "crash_vehicles",
                        "vision_zero_fatalities"
                    ]
                    .contains(&table),
                    ApiError::bad("invalid table_name")
                );
                ensure!(
                    body["confirm"] == true || body["confirm_deletion"] == true,
                    ApiError::bad("explicit deletion confirmation is required")
                );
                if let Some(range) = body.get("date_range").filter(|v| !v.is_null()) {
                    let range = range
                        .as_object()
                        .context(ApiError::bad("date_range must be an object"))?;
                    for (key, value) in range {
                        ensure!(
                            ["start", "end"].contains(&key.as_str())
                                && (value.is_null() || value.is_string()),
                            ApiError::bad("date_range start/end must be ISO date strings or null")
                        );
                    }
                }
                let dates = DateRange {
                    start_date: body["date_range"]["start"].as_str().map(str::to_owned),
                    end_date: body["date_range"]["end"].as_str().map(str::to_owned),
                };
                queries::date_predicate(&dates).map_err(ApiError::bad)?;
                let mut request = body.clone();
                if let Some(object) = request.as_object_mut() {
                    object.remove("backup_id");
                }
                if body["backup"] != false {
                    let backup = crate::recovery::backup(
                        db,
                        &state.control,
                        &state.directory.join("backups"),
                        state.storage.as_deref(),
                    )?;
                    request["backup_id"] = backup["id"].clone();
                }
                let operation_id = uuid::Uuid::new_v4().to_string();
                request["operation_id"] = json!(operation_id);
                let receipt = crate::mutations::delete_data(db, &request)?;
                crate::admin::record_deletion(&state.control, &operation_id, &receipt)?;
                return Ok(receipt);
            }
            ["jobs", "backup"] => {
                return crate::recovery::backup(
                    db,
                    &state.control,
                    &state.directory.join("backups"),
                    state.storage.as_deref(),
                );
            }
            _ => {}
        }
    }
    if *method == Method::PATCH && matches!(parts.as_slice(), ["spatial", "layers", _]) {
        let id: i64 = parts[2].parse().map_err(ApiError::bad)?;
        layer_metadata(db, id)?;
        let object = body
            .as_object()
            .context(ApiError::bad("layer update must be an object"))?;
        if object.is_empty() {
            return Err(ApiError::bad("layer update must contain fields").into());
        }
        for (field, value) in object {
            match field.as_str() {
                "name" => ensure!(
                    value
                        .as_str()
                        .is_some_and(|v| !v.trim().is_empty() && v.len() <= 200),
                    ApiError::bad("name must be 1..200 bytes")
                ),
                "description" => ensure!(
                    value.is_null() || value.as_str().is_some_and(|v| v.len() <= 10000),
                    ApiError::bad("description must be a string of at most 10000 bytes")
                ),
                "label_field" => ensure!(
                    value.is_null()
                        || value
                            .as_str()
                            .is_some_and(|v| !v.is_empty() && v.len() <= 255),
                    ApiError::bad("label_field must be a nonempty string or null")
                ),
                "is_active" => ensure!(
                    value.is_boolean(),
                    ApiError::bad("is_active must be boolean")
                ),
                "sort_type" => ensure!(
                    value.is_null()
                        || matches!(value.as_str(), Some("alphabetic" | "numeric" | "natural")),
                    ApiError::bad("sort_type must be alphabetic, numeric or natural")
                ),
                _ => return Err(ApiError::bad("unsupported layer update field").into()),
            }
        }
        db.transaction(|s| {
            for (field,value) in object {s.execute(&format!("UPDATE spatial_layers SET {field}=$1,updated_at=current_timestamp WHERE id=$2"),&[value.clone(),json!(id)])?;}
            crate::mutations::record(s,"layer_patch",&json!({"id":id,"patch":body}))?;
            Ok(())
        })?;
        return layer_metadata(db, id);
    }
    if *method == Method::DELETE && matches!(parts.as_slice(), ["spatial", "layers", _]) {
        let id: i64 = parts[2].parse().map_err(ApiError::bad)?;
        layer_metadata(db, id)?;
        db.transaction(|s| {
            s.execute(
                "DELETE FROM spatial_layer_features WHERE layer_id=$1",
                &[json!(id)],
            )?;
            s.execute("DELETE FROM spatial_layers WHERE id=$1", &[json!(id)])?;
            crate::mutations::record(s, "layer_delete", &json!({"id":id}))?;
            Ok(())
        })?;
        return Ok(json!({"deleted":id}));
    }
    Err(anyhow!("Route not found"))
}

fn validate_place(kind: &str, id: Option<&str>) -> std::result::Result<(), ApiError> {
    if let Some(layer) = kind.strip_prefix("layer:") {
        layer
            .parse::<i64>()
            .map_err(|_| ApiError::bad("Invalid layer ID"))?;
        if let Some(id) = id {
            id.parse::<i64>()
                .map_err(|_| ApiError::bad("Invalid feature ID"))?;
        }
    } else if ![
        "wards",
        "community_areas",
        "house_districts",
        "senate_districts",
        "police_beats",
    ]
    .contains(&kind)
    {
        return Err(ApiError(StatusCode::NOT_FOUND, "Unknown place type".into()));
    }
    Ok(())
}

fn layer_metadata(db: &Database, id: i64) -> Result<Value> {
    let mut layer = db
        .query("SELECT * FROM spatial_layers WHERE id=$1", &[json!(id)])?
        .into_iter()
        .next()
        .context("Layer not found or inactive: metadata")?;
    let samples = db.query(
        "SELECT id,properties FROM spatial_layer_features WHERE layer_id=$1 ORDER BY id LIMIT 5",
        &[json!(id)],
    )?;
    let mut properties = Vec::new();
    let mut feature_samples = Vec::new();
    for row in samples {
        let value = match &row["properties"] {
            Value::String(value) => serde_json::from_str(value)?,
            value => value.clone(),
        };
        feature_samples.push(json!({"id":row["id"],"properties":value}));
        properties.push(value);
    }
    let fields=db.query("SELECT DISTINCT unnest(json_keys(properties)) AS field FROM spatial_layer_features WHERE layer_id=$1 ORDER BY field",&[json!(id)])?;
    layer["sample_properties"] = json!(properties);
    layer["feature_samples"] = json!(feature_samples);
    layer["fields"] = json!(
        fields
            .iter()
            .map(|r| r["field"].clone())
            .collect::<Vec<_>>()
    );
    Ok(layer)
}

fn number(
    query: &BTreeMap<String, String>,
    name: &str,
    default: usize,
    max: usize,
) -> Result<usize> {
    let value = query
        .get(name)
        .map(|v| v.parse())
        .transpose()
        .map_err(ApiError::bad)?
        .unwrap_or(default);
    if value == 0 || value > max {
        return Err(ApiError::bad(format!("{name} must be between 1 and {max}")).into());
    }
    Ok(value)
}

async fn upload(
    State(state): State<AppState>,
    request: Request,
) -> std::result::Result<Response, ApiError> {
    use axum::extract::FromRequest;
    let preview = request.uri().path().ends_with("preview-fields");
    let segments = request
        .uri()
        .path()
        .split('/')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();
    let replace = if let ["spatial", "layers", id, "replace"] = segments.as_slice() {
        Some(id.parse::<i64>().map_err(ApiError::bad)?)
    } else {
        None
    };
    let mut multipart = Multipart::from_request(request, &state)
        .await
        .map_err(ApiError::bad)?;
    let temporary = tempfile::TempDir::new().map_err(anyhow::Error::from)?;
    let path = temporary.path().join("upload");
    let mut filename = None;
    let mut name = String::new();
    let mut label = None;
    let mut metadata = json!({});
    let mut seen = std::collections::HashSet::new();
    while let Some(mut field) = multipart.next_field().await.map_err(ApiError::bad)? {
        let field_name = field.name().unwrap_or_default().to_owned();
        if !seen.insert(field_name.clone()) {
            return Err(ApiError::bad("duplicate upload field"));
        }
        match field_name.as_str() {
            "file" => {
                filename = Some(
                    field
                        .file_name()
                        .ok_or_else(|| ApiError::bad("filename required"))?
                        .to_owned(),
                );
                let mut file = tokio::fs::File::create(&path)
                    .await
                    .map_err(anyhow::Error::from)?;
                let mut size = 0;
                while let Some(chunk) = field.chunk().await.map_err(ApiError::bad)? {
                    size += chunk.len();
                    if size > 50 * 1024 * 1024 {
                        return Err(ApiError::bad("upload exceeds 50MiB"));
                    }
                    tokio::io::AsyncWriteExt::write_all(&mut file, &chunk)
                        .await
                        .map_err(anyhow::Error::from)?;
                }
                // Tokio may return from write_all before its filesystem task
                // finishes. Complete it before synchronous validation reopens
                // this path, including the final multipart chunk's write errors.
                tokio::io::AsyncWriteExt::flush(&mut file)
                    .await
                    .map_err(anyhow::Error::from)?;
            }
            "name" => name = field.text().await.map_err(ApiError::bad)?,
            "label_field" => label = Some(field.text().await.map_err(ApiError::bad)?),
            "description" => {
                metadata["description"] = json!(field.text().await.map_err(ApiError::bad)?)
            }
            "sort_type" => {
                let value = field.text().await.map_err(ApiError::bad)?;
                if !["alphabetic", "numeric", "natural"].contains(&value.as_str()) {
                    return Err(ApiError::bad("invalid sort_type"));
                }
                metadata["sort_type"] = json!(value);
            }
            "srid" => {
                if field.text().await.map_err(ApiError::bad)? != "4326" {
                    return Err(ApiError::bad("only EPSG:4326 uploads are supported"));
                }
            }
            _ => return Err(ApiError::bad("unsupported upload field")),
        }
    }
    let filename = filename.ok_or_else(|| ApiError::bad("file is required"))?;
    if label.as_deref() == Some("") {
        label = None;
    }
    if !preview && replace.is_none() && (name.trim().is_empty() || name.len() > 200) {
        return Err(ApiError::bad("layer name must be 1..200 bytes"));
    }
    if metadata["description"]
        .as_str()
        .is_some_and(|v| v.len() > 10000)
    {
        return Err(ApiError::bad("description exceeds 10000 bytes"));
    }
    metadata["original_filename"] = json!(filename);
    let db = state.db.clone();
    let result = blocking(&state, move || {
        let _keep = temporary;
        let prepared = layers::prepare_upload(&path, &filename)
            .map_err(|error| ApiError::bad(format!("Invalid spatial upload: {error}")))?;
        if preview {
            layers::preview_upload(&db, &prepared.geojson)
        } else {
            let name = if let Some(id) = replace {
                layer_metadata(&db, id)?["name"]
                    .as_str()
                    .context("layer name missing")?
                    .to_owned()
            } else {
                name
            };
            let result = layers::publish_upload_metadata(
                &db,
                &prepared.geojson,
                &name,
                label.as_deref(),
                replace,
                &metadata,
            )?;
            layer_metadata(
                &db,
                result["id"]
                    .as_i64()
                    .context("published layer identity missing")?,
            )
        }
    })
    .await?;
    Ok(Json(result).into_response())
}

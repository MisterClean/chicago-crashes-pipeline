//! Real-engine HTTP contracts. Every fixture owns a temporary database and queue.
use crate::{
    api::{self, AppState},
    control::ControlStore,
    db::Database,
};
use axum::{
    Router,
    body::{Body, to_bytes},
    http::{HeaderMap, Request, StatusCode},
};
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tower::ServiceExt;

const KEY: &str = "local-test-key-at-least-thirty-two-bytes";

#[tokio::test]
async fn embedded_admin_routes_work_behind_the_frontend_proxy_and_keep_authentication() {
    let (state, _directory) = fixture().unwrap();
    let app = api::router(state);
    let direct = send(app.clone(), "GET", "/jobs/summary", Value::Null, Some(KEY)).await;
    let proxied = send(
        app.clone(),
        "GET",
        "/admin/api/jobs/summary",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(direct.0, StatusCode::OK);
    assert_eq!(proxied.0, StatusCode::OK);
    assert_eq!(proxied.1, direct.1);
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/admin/api/jobs/summary",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/admin/api/jobs/summary",
            Value::Null,
            Some("invalid")
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/admin/api/dashboard/stats",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::OK
    );
    let geometry = json!({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"Boundary"},"geometry":{"type":"Polygon","coordinates":[[[-87.7,41.8],[-87.6,41.8],[-87.6,41.9],[-87.7,41.8]]]}}]});
    let (status, preview) = multipart(
        app.clone(),
        "/admin/api/spatial/layers/preview-fields",
        &[],
        &geometry.to_string(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert_eq!(preview["recommended_field"], "name");
    assert_eq!(
        send(
            app,
            "POST",
            "/admin/api/spatial/layers/preview-fields",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
}

fn fixture() -> Option<(AppState, tempfile::TempDir)> {
    let _ = tracing_subscriber::fmt()
        .with_max_level(tracing::Level::ERROR)
        .try_init();
    let library = crate::test_support::library();
    let directory = tempfile::tempdir().unwrap();
    let db = Database::open(
        &directory.path().join("fixture.duckdb"),
        &library,
        "64MB",
        1,
        &directory.path().join("spill"),
    )
    .unwrap();
    crate::test_support::load_spatial(&db);
    db.execute("SET geometry_always_xy=true", &[]).unwrap();
    let sql=include_str!("../sql/query_fixture.sql")
        .replace("CREATE TABLE spatial_layers (id BIGINT, name VARCHAR, feature_count BIGINT,is_active BOOLEAN,label_field VARCHAR,sort_type VARCHAR)","CREATE TABLE spatial_layers (id BIGINT,name VARCHAR,slug VARCHAR,description VARCHAR,geometry_type VARCHAR,srid INTEGER,feature_count BIGINT,original_filename VARCHAR,is_active BOOLEAN,label_field VARCHAR,sort_type VARCHAR,created_at TIMESTAMP,updated_at TIMESTAMP)")
        .replace("INSERT INTO spatial_layers VALUES","INSERT INTO spatial_layers (id,name,feature_count,is_active,label_field,sort_type) VALUES")
        .replace("properties JSON,geometry GEOMETRY)","properties JSON,geometry GEOMETRY,created_at TIMESTAMP,updated_at TIMESTAMP)")
        .replace("INSERT INTO spatial_layer_features\n","INSERT INTO spatial_layer_features (id,layer_id,properties,geometry)\n");
    for statement in sql.split(';').filter(|s| !s.trim().is_empty()) {
        db.execute(statement, &[]).unwrap();
    }
    db.execute("CREATE TABLE vision_zero_fatalities(person_id VARCHAR,crash_date TIMESTAMP,latitude DOUBLE,longitude DOUBLE,geometry GEOMETRY)",&[]).unwrap();
    std::fs::create_dir_all(directory.path().join("exports")).unwrap();
    let state = AppState {
        db: Arc::new(db),
        control: ControlStore::open(directory.path().join("control.sqlite"), 2, 10).unwrap(),
        directory: directory.path().to_owned(),
        api_key: Arc::new(KEY.into()),
        production: false,
        storage: None,
        admission: Arc::new(tokio::sync::Semaphore::new(4)),
        profiling_data: true,
        pubcache: Arc::new(crate::cache::ResponseCache::new(
            0,
            Duration::from_secs(300),
        )),
    };
    Some((state, directory))
}

async fn send(
    app: Router,
    method: &str,
    path: &str,
    body: Value,
    key: Option<&str>,
) -> (StatusCode, Value, HeaderMap) {
    let mut builder = Request::builder().method(method).uri(path);
    if let Some(key) = key {
        builder = builder.header("x-api-key", key);
    }
    let payload = if body.is_null() {
        String::new()
    } else {
        body.to_string()
    };
    let response = app
        .oneshot(
            builder
                .header("content-type", "application/json")
                .body(Body::from(payload))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = to_bytes(response.into_body(), 2_000_000).await.unwrap();
    let value =
        serde_json::from_slice(&bytes).unwrap_or_else(|_| json!(String::from_utf8_lossy(&bytes)));
    (status, value, headers)
}

fn place() -> Value {
    json!({"place_type":"layer:4","place_id":"259","start_date":"2024-01-01","end_date":"2024-01-31"})
}

#[tokio::test]
async fn public_report_rejects_unbounded_month_expansion_before_database_admission() {
    let (mut state, _directory) = fixture().unwrap();
    state.admission = Arc::new(tokio::sync::Semaphore::new(0));
    let app = api::router(state);
    for (start, end) in [
        ("-250000-01-01", "2026-01-01"),
        ("0000-01-01", "2026-01-01"),
        ("0001-01-01", "9999-12-31"),
    ] {
        let mut request = place();
        request["start_date"] = json!(start);
        request["end_date"] = json!(end);
        let (status, _, _) = send(
            app.clone(),
            "POST",
            "/dashboard/location-report",
            request,
            None,
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{start}..{end}");
    }
    let (status, _, _) = send(
        app,
        "GET",
        "/dashboard/stats?start_date=-250000-01-01",
        Value::Null,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn public_report_bounds_one_sided_date_ranges_after_resolving_matching_months() {
    let (state, _directory) = fixture().unwrap();
    let app = api::router(state);
    for dates in [
        json!({"start_date":"0001-01-01"}),
        json!({"end_date":"9999-12-31"}),
    ] {
        let mut request = json!({"place_type":"layer:4","place_id":"259"});
        for (key, value) in dates.as_object().unwrap() {
            request[key] = value.clone();
        }
        let (status, body, _) = send(
            app.clone(),
            "POST",
            "/dashboard/location-report",
            request,
            None,
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
        assert_eq!(body["detail"], crate::queries::REPORT_RANGE_ERROR);
    }
    let request = json!({"place_type":"layer:4","place_id":"259"});
    let (status, report, _) = send(app, "POST", "/dashboard/location-report", request, None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(report["stats"]["total_crashes"], 2);
}
fn export() -> Value {
    let mut v = place();
    v["datasets"] = json!(["crashes"]);
    v
}

#[tokio::test]
async fn public_dashboard_and_sync_reads_work_without_operational_credentials() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    for path in [
        "/health",
        "/ready",
        "/dashboard/stats",
        "/dashboard/trends/weekly",
        "/sync/status",
        "/places/types",
    ] {
        let (status, _, _) = send(app.clone(), "GET", path, Value::Null, None).await;
        assert_eq!(status, StatusCode::OK, "{path}");
    }
    let (status, report, _) = send(app, "POST", "/dashboard/location-report", place(), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(report["stats"]["total_crashes"], 1);
    assert_eq!(report["hour_day_counts"].as_array().unwrap().len(), 168);
}

#[tokio::test]
async fn protected_operations_require_header_key_and_do_not_accept_query_credentials() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    for (method, path, body) in [
        ("GET", "/jobs", Value::Null),
        ("GET", "/spatial/layers", Value::Null),
        ("POST", "/exports", export()),
        ("POST", "/sync/trigger", json!({})),
    ] {
        assert_eq!(
            send(app.clone(), method, path, body.clone(), None).await.0,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            send(app.clone(), method, path, body, Some("wrong")).await.0,
            StatusCode::UNAUTHORIZED
        );
    }
    assert_eq!(
        send(
            app.clone(),
            "GET",
            &format!("/jobs?api_key={KEY}"),
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(app, "GET", "/jobs", Value::Null, Some(KEY)).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn encoded_layer_ids_resolve_and_wrong_features_return_not_found() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/places/types/layer%3A4/items",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/places/types/layer%3A4/items/259/geometry",
            Value::Null,
            None
        )
        .await
        .1["name"],
        "10"
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/places/types/layer%3A4/items/999/geometry",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        send(
            app,
            "GET",
            "/places/types/layer%3A4%2Fitems",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
}

#[tokio::test]
async fn invalid_dates_limits_and_report_selectors_are_client_errors() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    for path in [
        "/dashboard/stats?start_date=bad",
        "/dashboard/stats?start_date=2025-01-01&end_date=2024-01-01",
        "/dashboard/trends/weekly?weeks=0",
        "/dashboard/crashes/geojson?limit=50001",
        "/dashboard/crashes/by-cause?limit=51",
        "/dashboard/crashes/by-cause?limit=nope",
    ] {
        assert_eq!(
            send(app.clone(), "GET", path, Value::Null, None).await.0,
            StatusCode::BAD_REQUEST,
            "{path}"
        );
    }
    for body in [
        json!({}),
        json!({"latitude":41.8}),
        json!({"latitude":41.8,"longitude":-87.6,"radius_feet":26401}),
        json!({"polygon":[[0,0],[1,1]]}),
        json!({"place_type":"layer:4","place_id":"259","resolved_area":{}}),
    ] {
        assert_eq!(
            send(
                app.clone(),
                "POST",
                "/dashboard/location-report",
                body,
                None
            )
            .await
            .0,
            StatusCode::BAD_REQUEST
        );
    }
    let crossing = json!({"polygon":[[-87.7,41.7],[-87.5,41.9],[-87.7,41.9],[-87.5,41.7]]});
    assert_eq!(
        send(app, "POST", "/dashboard/location-report", crossing, None)
            .await
            .0,
        StatusCode::BAD_REQUEST
    );
}

#[tokio::test]
async fn exports_validate_datasets_freeze_geometry_and_obey_durable_queue_capacity() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    for datasets in [json!([]), json!(["crashes", "crashes"]), json!(["unknown"])] {
        let mut body = place();
        body["datasets"] = datasets;
        assert_eq!(
            send(app.clone(), "POST", "/exports", body, Some(KEY))
                .await
                .0,
            StatusCode::BAD_REQUEST
        );
    }
    let (status, job, _) = send(app.clone(), "POST", "/exports", export(), Some(KEY)).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    let stored = state
        .control
        .get(job["id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(
        stored.request["location"]["resolved_area"]["geometry"]["type"],
        "Polygon"
    );
    state
        .db
        .execute("DELETE FROM spatial_layer_features WHERE id=259", &[])
        .unwrap();
    let frozen: crate::queries::LocationRequest =
        serde_json::from_value(stored.request["location"].clone()).unwrap();
    assert!(crate::queries::selected_crashes(&state.db, &frozen).is_ok());
    state.control.enqueue(&json!({"other":true})).unwrap();
    let (_, _, _) = send(app.clone(), "GET", "/exports", Value::Null, Some(KEY)).await;
    // Use an existing valid feature: the queued request retained deleted feature259.
    let mut body = export();
    body["place_id"] = json!("260");
    let (status, _, headers) = send(app, "POST", "/exports", body, Some(KEY)).await;
    assert_eq!(status, StatusCode::TOO_MANY_REQUESTS);
    assert!(headers.contains_key("retry-after"));
}

#[tokio::test]
async fn export_download_uses_short_lived_signed_local_url_without_header_leak() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let job = state.control.enqueue(&export()).unwrap();
    assert_eq!(
        send(
            app.clone(),
            "GET",
            &format!("/exports/{}/download", job.id),
            Value::Null,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::CONFLICT
    );
    let running = state.control.claim("export").unwrap().unwrap();
    let directory = state
        .directory
        .join("exports")
        .join(&job.id)
        .join(running.attempt_token.as_ref().unwrap());
    std::fs::create_dir_all(&directory).unwrap();
    let path = directory.join("crashes.csv");
    std::fs::write(&path, b"id\na\n").unwrap();
    state
        .control
        .finish(
            &job.id,
            running.attempt_token.as_ref().unwrap(),
            Some(path.to_str().unwrap()),
            &json!({}),
        )
        .unwrap();
    let (status, body, _) = send(
        app.clone(),
        "GET",
        &format!("/exports/{}/download", job.id),
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let url = body["url"].as_str().unwrap();
    assert!(!url.contains(KEY));
    let backend = url.strip_prefix("/api").unwrap();
    assert_eq!(
        send(app.clone(), "GET", backend, Value::Null, None).await.0,
        StatusCode::OK
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            &format!("/exports/{}/artifact", job.id),
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            &backend.replace("token=", "token=00"),
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    state
        .control
        .connect()
        .unwrap()
        .execute("UPDATE rust_jobs SET expires_at=0 WHERE id=?", [&job.id])
        .unwrap();
    assert_eq!(
        send(
            app,
            "GET",
            &format!("/exports/{}/download", job.id),
            Value::Null,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::GONE
    );
}

#[tokio::test]
async fn cancelled_export_cannot_be_claimed_and_missing_export_is_404() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let job = state.control.enqueue(&export()).unwrap();
    let (status, body, _) = send(
        app.clone(),
        "POST",
        &format!("/exports/{}/cancel", job.id),
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "cancelled");
    assert!(state.control.claim("export").unwrap().is_none());
    assert_eq!(
        send(app, "GET", "/exports/missing", Value::Null, Some(KEY))
            .await
            .0,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn sql_errors_are_sanitized_and_excess_admission_returns_503() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let permit = state.admission.clone().acquire_many_owned(4).await.unwrap();
    let (status, _, headers) =
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(headers.contains_key("retry-after"));
    assert_eq!(
        send(app.clone(), "GET", "/health", Value::Null, None)
            .await
            .0,
        StatusCode::OK
    );
    drop(permit);
    state.db.execute("DROP TABLE crash_people", &[]).unwrap();
    let (status, body, _) = send(app, "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(body, json!({"detail":"Request could not be completed"}));
}

#[tokio::test]
async fn admin_assets_are_embedded_and_spatial_metadata_mutations_are_authenticated() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    for path in ["/admin", "/admin/", "/admin/app.js", "/admin/styles.css"] {
        assert_eq!(
            send(app.clone(), "GET", path, Value::Null, None).await.0,
            StatusCode::OK
        );
    }
    let (status, body, _) = send(
        app.clone(),
        "GET",
        "/spatial/layers/4",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(
        body["fields"]
            .as_array()
            .unwrap()
            .contains(&json!("district"))
    );
    let patch = json!({"description":"Edited","sort_type":"natural","is_active":false,"label_field":"district"});
    assert_eq!(
        send(
            app.clone(),
            "PATCH",
            "/spatial/layers/4",
            patch.clone(),
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    let (status, body, _) = send(app.clone(), "PATCH", "/spatial/layers/4", patch, Some(KEY)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["description"], "Edited");
    assert_eq!(
        send(
            app.clone(),
            "DELETE",
            "/spatial/layers/4",
            Value::Null,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(
        send(app, "GET", "/spatial/layers/4", Value::Null, Some(KEY))
            .await
            .0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        state
            .db
            .query("SELECT count(*) AS n FROM rust_mutations", &[])
            .unwrap()[0]["n"],
        2
    );
}

#[test]
fn native_cancellation_interrupts_work_and_leaves_connection_usable() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let started = Instant::now();
    let result = state.db.with_session(|s| {
        s.guarded(
            || {
                anyhow::ensure!(started.elapsed() < Duration::from_millis(100), "cancelled");
                Ok(())
            },
            || {
                s.query(
                    "SELECT sum(sqrt(i::DOUBLE)) FROM range(10000000000) t(i)",
                    &[],
                )
            },
        )
    });
    assert!(result.is_err());
    assert!(started.elapsed() < Duration::from_secs(3));
    assert_eq!(state.db.query("SELECT 42 AS n", &[]).unwrap()[0]["n"], 42);
}

#[test]
fn native_buffer_failure_rolls_back_and_does_not_poison_connection() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    state.db.execute("SET memory_limit='1MB'", &[]).unwrap();
    let result = state
        .db
        .transaction(|s| s.query("SELECT count(DISTINCT i) FROM range(1000000) t(i)", &[]));
    assert!(result.is_err());
    assert_eq!(state.db.query("SELECT 42 AS n", &[]).unwrap()[0]["n"], 42);
}

#[test]
fn panic_callbacks_exit_promptly_and_roll_back_without_poisoning_owner() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let db = state.db.clone();
    let (send, receive) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let result: anyhow::Result<()> = db.transaction(|s| {
            s.guarded(
                || Ok(()),
                || {
                    s.execute("CREATE TABLE must_rollback(x INTEGER)", &[])?;
                    panic!("deliberate fixture panic")
                },
            )
        });
        send.send(result.is_err()).unwrap();
    });
    assert!(
        receive
            .recv_timeout(Duration::from_secs(2))
            .expect("guarded panic must not deadlock watchdog")
    );
    assert_eq!(state.db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name='must_rollback'",&[]).unwrap()[0]["n"],0);
    assert_eq!(state.db.query("SELECT 42 AS n", &[]).unwrap()[0]["n"], 42);
}

async fn multipart(
    app: Router,
    path: &str,
    fields: &[(&str, &str)],
    data: &str,
) -> (StatusCode, Value) {
    multipart_with_chunks(app, path, fields, data, None).await
}

async fn multipart_with_chunks(
    app: Router,
    path: &str,
    fields: &[(&str, &str)],
    data: &str,
    chunk_size: Option<usize>,
) -> (StatusCode, Value) {
    let boundary = "rust-multipart-contract";
    let mut payload = String::new();
    for (name, value) in fields {
        payload.push_str(&format!(
            "--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        ));
    }
    payload.push_str(&format!("--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"boundary.geojson\"\r\nContent-Type: application/geo+json\r\n\r\n{data}\r\n--{boundary}--\r\n"));
    let body = if let Some(chunk_size) = chunk_size {
        Body::from_stream(tokio_util::io::ReaderStream::with_capacity(
            std::io::Cursor::new(payload),
            chunk_size,
        ))
    } else {
        Body::from(payload)
    };
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("x-api-key", KEY)
                .header(
                    "content-type",
                    format!("multipart/form-data; boundary={boundary}"),
                )
                .body(body)
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1_000_000).await.unwrap();
    (status, serde_json::from_slice(&bytes).unwrap())
}

#[tokio::test]
async fn spatial_preview_reads_complete_streamed_uploads_including_final_chunks() {
    let (state, _directory) = fixture().unwrap();
    let app = api::router(state);
    let label = "Boundary label ".repeat(64);
    let geometry = json!({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":label},"geometry":{"type":"Polygon","coordinates":[[[-87.7,41.8],[-87.6,41.8],[-87.6,41.9],[-87.7,41.8]]]}}]}).to_string();
    for chunk_size in [1, 17, 4096] {
        let (status, preview) = multipart_with_chunks(
            app.clone(),
            "/spatial/layers/preview-fields",
            &[],
            &geometry,
            Some(chunk_size),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "chunk_size={chunk_size}: {preview}");
        assert_eq!(preview["feature_count"], 1);
        let name = preview["fields"]
            .as_array()
            .unwrap()
            .iter()
            .find(|field| field["name"] == "name")
            .unwrap();
        assert_eq!(name["sample_values"], json!([label]));
    }
}

#[tokio::test]
async fn spatial_multipart_preview_upload_and_replace_preserve_metadata_and_layer_identity() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let geometry=json!({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"district":5,"name":"Test area"},"geometry":{"type":"Polygon","coordinates":[[[-87.7,41.7],[-87.5,41.7],[-87.5,41.9],[-87.7,41.9],[-87.7,41.7]]]}}]}).to_string();
    let (status, preview) = multipart(
        app.clone(),
        "/spatial/layers/preview-fields",
        &[],
        &geometry,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert!(
        preview["fields"]
            .as_array()
            .unwrap()
            .iter()
            .any(|field| field["name"] == "district")
    );
    let (status, layer) = multipart(
        app.clone(),
        "/spatial/layers",
        &[
            ("name", "New layer"),
            ("description", "Uploaded description"),
            ("label_field", "district"),
            ("sort_type", "numeric"),
            ("srid", "4326"),
        ],
        &geometry,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{layer}");
    assert_eq!(layer["id"], 5);
    assert_eq!(layer["description"], "Uploaded description");
    assert_eq!(layer["original_filename"], "boundary.geojson");
    assert_eq!(layer["sort_type"], "numeric");
    let (_, items, _) = send(
        app.clone(),
        "GET",
        "/places/types/layer%3A5/items",
        Value::Null,
        None,
    )
    .await;
    let old_id = items[0]["id"].clone();
    assert_eq!(items[0]["name"], "5");
    let (status, replaced) =
        multipart(app.clone(), "/spatial/layers/5/replace", &[], &geometry).await;
    assert_eq!(status, StatusCode::OK, "{replaced}");
    assert_eq!(replaced["id"], 5);
    assert_eq!(replaced["name"], "New layer");
    assert_eq!(replaced["description"], "Uploaded description");
    assert_eq!(replaced["label_field"], "district");
    let (_, items, _) = send(
        app.clone(),
        "GET",
        "/places/types/layer%3A5/items",
        Value::Null,
        None,
    )
    .await;
    assert_ne!(items[0]["id"], old_id);
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/places/types/layer%3A4/items/259/geometry",
            Value::Null,
            None
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(
        send(
            app,
            "POST",
            "/dashboard/location-report/export",
            export(),
            Some(KEY)
        )
        .await
        .0,
        StatusCode::GONE
    );
}

#[tokio::test]
async fn confirmed_date_bounded_deletion_audits_and_only_mutates_the_requested_table() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let request = json!({"table_name":"crashes","confirm":true,"backup":false,"backup_id":"client-must-not-forge","date_range":{"start":"2024-01-01","end":"2024-01-31"}});
    assert_eq!(
        send(
            app.clone(),
            "POST",
            "/jobs/data/delete",
            request.clone(),
            None
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    let mut unconfirmed = request.clone();
    unconfirmed["confirm"] = json!(false);
    assert_eq!(
        send(
            app.clone(),
            "POST",
            "/jobs/data/delete",
            unconfirmed,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
    let (status, receipt, _) = send(app, "POST", "/jobs/data/delete", request, Some(KEY)).await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(receipt["records_deleted"], 3);
    assert_eq!(receipt["can_restore"], false);
    assert_eq!(
        state
            .db
            .query("SELECT count(*) AS n FROM crashes", &[])
            .unwrap()[0]["n"],
        2
    );
    assert_eq!(
        state
            .db
            .query("SELECT count(*) AS n FROM crash_people", &[])
            .unwrap()[0]["n"],
        3
    );
    assert_eq!(
        state
            .db
            .query("SELECT count(*) AS n FROM rust_mutations", &[])
            .unwrap()[0]["n"],
        1
    );
}

#[test]
fn direct_transaction_panic_rolls_back_before_releasing_admission() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let result: anyhow::Result<()> = state.db.transaction(|s| {
        s.execute("CREATE TABLE direct_panic_rollback(x INTEGER)", &[])?;
        panic!("deliberate transaction fixture panic")
    });
    assert!(result.is_err());
    assert_eq!(state.db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name='direct_panic_rollback'",&[]).unwrap()[0]["n"],0);
    assert_eq!(state.db.query("SELECT 42 AS n", &[]).unwrap()[0]["n"], 42);
}

#[tokio::test]
async fn runtime_info_is_protected_and_does_not_disclose_paths_or_credentials() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    assert_eq!(
        send(app.clone(), "GET", "/runtime/info", Value::Null, None)
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
    let (status, body, _) = send(app, "GET", "/runtime/info", Value::Null, Some(KEY)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["backend"], "rust");
    assert_eq!(body["engine"], "2.0.0");
    assert_eq!(body["serialized"], true);
    assert!(body["max_temp_directory_size"].as_str().is_some());
    assert!(body["resources"]["pid"].as_u64().is_some());
    assert!(!body.to_string().contains(KEY));
    assert!(!body.to_string().contains(_dir.path().to_str().unwrap()));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn public_cache_singleflight_computes_one_response_and_canonicalizes_query_order() {
    let Some((mut state, _dir)) = fixture() else {
        return;
    };
    state.pubcache = Arc::new(crate::cache::ResponseCache::new(
        1024 * 1024,
        Duration::from_secs(300),
    ));
    let app = api::router(state.clone());
    let mut tasks = Vec::new();
    for _ in 0..8 {
        let app = app.clone();
        tasks.push(tokio::spawn(async move {
            send(
                app,
                "GET",
                "/dashboard/stats?end_date=2024-01-31&start_date=2024-01-01",
                Value::Null,
                None,
            )
            .await
        }));
    }
    let mut misses = 0;
    let mut hits = 0;
    for task in tasks {
        let (status, body, headers) = task.await.unwrap();
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["total_crashes"], 3);
        match headers["x-cache"].to_str().unwrap() {
            "MISS" => misses += 1,
            "HIT" => hits += 1,
            value => panic!("unexpected cache state {value}"),
        };
    }
    assert_eq!((misses, hits), (1, 7));
    assert_eq!(state.pubcache.stats().misses, 1);
    let (_, _, headers) = send(
        app,
        "GET",
        "/dashboard/stats?start_date=2024-01-01&end_date=2024-01-31",
        Value::Null,
        None,
    )
    .await;
    assert_eq!(headers["x-cache"], "HIT");
}

#[tokio::test]
async fn journaled_facts_layers_and_deletion_changes_invalidate_public_cached_reads() {
    let Some((mut state, _dir)) = fixture() else {
        return;
    };
    state.pubcache = Arc::new(crate::cache::ResponseCache::new(
        1024 * 1024,
        Duration::from_secs(300),
    ));
    let app = api::router(state.clone());
    let (_, first, headers) = send(app.clone(), "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(first["total_crashes"], 5);
    assert_eq!(
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None)
            .await
            .2["x-cache"],
        "HIT"
    );
    let generation = state.db.generation();
    state
        .db
        .transaction(|s| {
            s.execute(
                "UPDATE crashes SET injuries_total=10 WHERE crash_record_id='a'",
                &[],
            )?;
            crate::mutations::record(s, "facts.publish", &json!({"fixture":true}))
        })
        .unwrap();
    assert!(state.db.generation() > generation);
    let (_, changed, headers) =
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(changed["total_injuries"], 10);
    let (_, items, headers) = send(
        app.clone(),
        "GET",
        "/places/types/layer%3A4/items",
        Value::Null,
        None,
    )
    .await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(items[0]["name"], "1");
    let (status, _, _) = send(
        app.clone(),
        "PATCH",
        "/spatial/layers/4",
        json!({"label_field":null}),
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (_, items, headers) = send(
        app.clone(),
        "GET",
        "/places/types/layer%3A4/items",
        Value::Null,
        None,
    )
    .await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(items[0]["name"], "District 1");
    let(status,_,_)=send(app.clone(),"POST","/jobs/data/delete",json!({"table_name":"crashes","confirm":true,"backup":false,"date_range":{"start":"2024-01-01","end":"2024-01-31"}}),Some(KEY)).await;
    assert_eq!(status, StatusCode::OK);
    let (_, changed, headers) = send(app, "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(changed["total_crashes"], 2);
}

#[tokio::test]
async fn public_cache_never_stores_errors_or_operational_status() {
    let Some((mut state, _dir)) = fixture() else {
        return;
    };
    state.pubcache = Arc::new(crate::cache::ResponseCache::new(
        1024 * 1024,
        Duration::from_secs(300),
    ));
    let app = api::router(state.clone());
    state.db.execute("DROP TABLE crash_people", &[]).unwrap();
    assert_eq!(
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None)
            .await
            .0,
        StatusCode::INTERNAL_SERVER_ERROR
    );
    assert_eq!(state.pubcache.stats().entries, 0);
    state
        .db
        .execute(
            "CREATE TABLE crash_people(person_type VARCHAR,crash_date TIMESTAMP)",
            &[],
        )
        .unwrap();
    let (status, _, headers) =
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers["x-cache"], "MISS");
    let (_, _, headers) = send(app.clone(), "GET", "/sync/status", Value::Null, None).await;
    assert!(!headers.contains_key("x-cache"));
    let (_, _, headers) = send(app, "GET", "/exports", Value::Null, Some(KEY)).await;
    assert!(!headers.contains_key("x-cache"));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn mutation_epoch_invalidates_hits_before_commit_and_rollbacks_only_cause_misses() {
    let Some((mut state, _dir)) = fixture() else {
        return;
    };
    state.pubcache = Arc::new(crate::cache::ResponseCache::new(
        1024 * 1024,
        Duration::from_secs(300),
    ));
    let app = api::router(state.clone());
    assert_eq!(
        send(app.clone(), "GET", "/dashboard/stats", Value::Null, None)
            .await
            .2["x-cache"],
        "MISS"
    );
    let db = state.db.clone();
    let (ready_tx, ready_rx) = std::sync::mpsc::channel();
    let (commit_tx, commit_rx) = std::sync::mpsc::channel();
    let writer = std::thread::spawn(move || {
        db.transaction(|s| {
            s.execute(
                "UPDATE crashes SET injuries_total=100 WHERE crash_record_id='a'",
                &[],
            )?;
            crate::mutations::record(s, "facts.publish", &json!({}))?;
            ready_tx.send(()).unwrap();
            commit_rx.recv().unwrap();
            Ok(())
        })
    });
    ready_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    let pending = tokio::spawn(send(
        app.clone(),
        "GET",
        "/dashboard/stats",
        Value::Null,
        None,
    ));
    tokio::time::sleep(Duration::from_millis(30)).await;
    assert!(
        !pending.is_finished(),
        "old cached result must not bypass an advanced mutation epoch"
    );
    commit_tx.send(()).unwrap();
    writer.join().unwrap().unwrap();
    let (_, body, headers) = pending.await.unwrap();
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(body["total_injuries"], 100);
    let generation = state.db.generation();
    let result: anyhow::Result<()> = state.db.transaction(|s| {
        s.execute(
            "UPDATE crashes SET injuries_total=500 WHERE crash_record_id='a'",
            &[],
        )?;
        crate::mutations::record(s, "facts.publish", &json!({}))?;
        anyhow::bail!("deliberate rollback")
    });
    assert!(result.is_err());
    assert!(state.db.generation() > generation);
    let (_, body, headers) = send(app, "GET", "/dashboard/stats", Value::Null, None).await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(body["total_injuries"], 100);
}

#[tokio::test]
async fn post_report_cache_separates_body_date_ranges_and_never_serves_a_post_as_get() {
    let Some((mut state, _dir)) = fixture() else {
        return;
    };
    state.pubcache = Arc::new(crate::cache::ResponseCache::new(
        1024 * 1024,
        Duration::from_secs(300),
    ));
    let app = api::router(state);
    let (status, body, headers) = send(
        app.clone(),
        "POST",
        "/dashboard/location-report",
        place(),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(body["stats"]["total_crashes"], 1);
    assert_eq!(
        send(
            app.clone(),
            "POST",
            "/dashboard/location-report",
            place(),
            None
        )
        .await
        .2["x-cache"],
        "HIT"
    );
    let mut wider = place();
    wider["end_date"] = json!("2024-03-31");
    let (_, body, headers) = send(
        app.clone(),
        "POST",
        "/dashboard/location-report",
        wider,
        None,
    )
    .await;
    assert_eq!(headers["x-cache"], "MISS");
    assert_eq!(body["stats"]["total_crashes"], 2);
    assert_eq!(
        send(app, "GET", "/dashboard/location-report", Value::Null, None)
            .await
            .0,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn legacy_sync_counts_match_admin_aliases_without_double_counting() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    assert_eq!(
        send(app.clone(), "GET", "/sync/counts", Value::Null, None)
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
    let (status, body, _) = send(app.clone(), "GET", "/sync/counts", Value::Null, Some(KEY)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "success");
    assert_eq!(body["counts"]["crashes"], 5);
    assert_eq!(body["counts"]["people"], 3);
    assert_eq!(body["counts"]["crash_people"], 3);
    assert_eq!(body["counts"]["vehicles"], 5);
    assert_eq!(body["counts"]["crash_vehicles"], 5);
    assert_eq!(body["counts"]["fatalities"], 0);
    assert_eq!(body["counts"]["vision_zero_fatalities"], 0);
    assert_eq!(body["total_records"], 13);
    let (status, body, _) = send(app, "GET", "/sync/endpoints", Value::Null, Some(KEY)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["total_endpoints"], 4);
}

#[tokio::test]
async fn manual_sync_preserves_singular_endpoint_dates_force_and_legacy_history_atomically() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    let request = json!({"endpoint":"fatalities","mode":"incremental","start_date":"2024-01-01","end_date":"2024-01-31","force":true,"config":{"repair_null_people_dates":false}});
    let (status, body, _) = send(app.clone(), "POST", "/sync/trigger", request, Some(KEY)).await;
    assert_eq!(status, StatusCode::ACCEPTED, "{body}");
    assert_eq!(body["status"], "pending");
    assert_eq!(body["sync_id"], body["queue_id"]);
    let job = state
        .control
        .get(body["sync_id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(job.request["endpoints"], json!(["fatalities"]));
    assert_eq!(job.request["endpoint"], "fatalities");
    assert_eq!(job.request["mode"], "api");
    assert_eq!(job.request["requested_mode"], "incremental");
    assert_eq!(job.request["start_date"], "2024-01-01");
    assert_eq!(job.request["end_date"], "2024-01-31");
    assert_eq!(job.request["force"], true);
    assert_eq!(job.request["config"]["repair_null_people_dates"], false);
    let (_, history, _) = send(
        app.clone(),
        "GET",
        "/jobs/executions/recent",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(history[0]["execution_id"], body["sync_id"]);
    let (_, status, _) = send(app, "GET", "/sync/status", Value::Null, None).await;
    assert_eq!(status["status"], "pending");
    assert_eq!(status["current_operation"], body["sync_id"]);
    assert_eq!(status["stats"]["total_syncs"], 1);
    assert!(status["uptime"].is_string());
    assert_eq!(status["crashes_count"], 5);
}

#[tokio::test]
async fn manual_sync_defaults_to_core_api_and_invalid_or_guarded_requests_never_queue() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    for (body, expected) in [
        (json!({"endpoint":"unknown"}), StatusCode::BAD_REQUEST),
        (
            json!({"endpoint":"people","datasets":["vehicles"]}),
            StatusCode::BAD_REQUEST,
        ),
        (
            json!({"start_date":"2024-01-31","end_date":"2024-01-01"}),
            StatusCode::BAD_REQUEST,
        ),
        (
            json!({"mode":"full","start_date":"2024-01-01"}),
            StatusCode::BAD_REQUEST,
        ),
        (json!({"mode":"full"}), StatusCode::CONFLICT),
        (
            json!({"mode":"incremental","endpoint":"people"}),
            StatusCode::CONFLICT,
        ),
        (
            json!({"endpoint":"people","force":true,"config":{"held":true}}),
            StatusCode::CONFLICT,
        ),
    ] {
        let (status, value, _) = send(app.clone(), "POST", "/sync/trigger", body, Some(KEY)).await;
        assert_eq!(status, expected, "{value}");
    }
    assert!(
        state
            .control
            .list(Some("ingestion"), 100)
            .unwrap()
            .is_empty()
    );
    let (status, body, _) = send(app, "POST", "/sync/trigger", json!({}), Some(KEY)).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    let job = state
        .control
        .get(body["sync_id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(
        job.request["endpoints"],
        json!(["crashes", "people", "vehicles"])
    );
    assert_eq!(job.request["mode"], "api");
    assert_eq!(job.request["date_range_days"], 30);
    assert_eq!(job.request["force"], false);
}

#[tokio::test]
async fn retired_live_diagnostics_are_explicit_and_spatial_introspection_is_allowlisted() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state);
    for (method, path) in [
        ("POST", "/sync/test"),
        ("GET", "/validate/crashes"),
        ("POST", "/spatial/load?directory=/private"),
    ] {
        let (status, body, _) = send(app.clone(), method, path, Value::Null, Some(KEY)).await;
        assert_eq!(status, StatusCode::GONE, "{body}");
        assert!(body["detail"].as_str().unwrap().contains("retired"));
    }
    let (status, body, _) = send(
        app.clone(),
        "GET",
        "/spatial/tables",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(
        body["tables"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["table_name"] == "crashes")
    );
    let (status, body, _) = send(
        app.clone(),
        "GET",
        "/spatial/tables/crashes?limit=1",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["record_count"], 1);
    assert!(
        body["sample_data"][0]["geometry"]
            .as_str()
            .unwrap()
            .starts_with("<geometry:")
    );
    assert_eq!(
        send(
            app.clone(),
            "GET",
            "/spatial/tables/crashes?limit=101",
            Value::Null,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        send(
            app,
            "GET",
            "/spatial/tables/rust_jobs",
            Value::Null,
            Some(KEY)
        )
        .await
        .0,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn scheduler_routes_require_auth_and_persist_gate_without_cancelling_jobs() {
    let Some((state, _dir)) = fixture() else {
        return;
    };
    let app = api::router(state.clone());
    for (method, path) in [
        ("GET", "/jobs/scheduler/status"),
        ("POST", "/jobs/scheduler/start"),
        ("POST", "/jobs/scheduler/stop"),
    ] {
        assert_eq!(
            send(app.clone(), method, path, Value::Null, None).await.0,
            StatusCode::UNAUTHORIZED
        );
    }
    let (_, status, _) = send(
        app.clone(),
        "GET",
        "/jobs/scheduler/status",
        Value::Null,
        Some(KEY),
    )
    .await;
    assert_eq!(status["is_running"], false);
    let (_, sync, _) = send(
        app.clone(),
        "POST",
        "/sync/trigger",
        json!({"endpoint":"crashes"}),
        Some(KEY),
    )
    .await;
    for (path, enabled) in [
        ("/jobs/scheduler/start", true),
        ("/jobs/scheduler/start", true),
        ("/jobs/scheduler/stop", false),
        ("/jobs/scheduler/stop", false),
    ] {
        let (code, status, _) = send(app.clone(), "POST", path, Value::Null, Some(KEY)).await;
        assert_eq!(code, StatusCode::OK, "{status}");
        assert_eq!(status["is_running"], enabled);
        assert_eq!(
            state.control.configuration("scheduler_enabled").unwrap(),
            Some(json!(enabled))
        );
        let (_, status, _) = send(
            app.clone(),
            "GET",
            "/jobs/scheduler/status",
            Value::Null,
            Some(KEY),
        )
        .await;
        assert_eq!(status["scheduler_enabled"], enabled);
    }
    assert_eq!(
        state
            .control
            .get(sync["sync_id"].as_str().unwrap())
            .unwrap()
            .unwrap()
            .status,
        "queued"
    );
}

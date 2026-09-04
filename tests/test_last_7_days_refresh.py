"""Manual refresh requests persist work; execution belongs to the durable worker."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from src.api.routers import sync
from src.models.jobs import JobStatus, JobType, RecurrenceType
from src.services.sync_service import EndpointSyncResult, SyncResult
from src.utils.config import settings


@pytest.fixture
def job_service(monkeypatch):
    service = MagicMock()
    service.create_job.return_value = SimpleNamespace(id=17)
    service.execute_job = AsyncMock(return_value="exec_17_queued")
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(sync, "JobService", factory)
    # Any accidental immediate execution would fail this test suite.
    monkeypatch.setattr(
        sync,
        "SyncService",
        MagicMock(side_effect=AssertionError("The API must enqueue, not ingest")),
    )
    return service


@pytest.fixture
def client(job_service):
    app = FastAPI()
    app.include_router(sync.router)
    return TestClient(app, raise_server_exceptions=False)


def test_last_seven_days_preserves_dates_and_queues_api_mode(client, job_service):
    response = client.post(
        "/sync/trigger",
        json={
            "start_date": "2026-08-28",
            "end_date": "2026-09-04",
            "endpoint": "crashes",
            "force": True,
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["sync_id"] == "exec_17_queued"
    assert response.json()["started_at"]
    job_service.create_job.assert_called_once()
    data = job_service.create_job.call_args.args[0]
    assert data["config"] == {
        "endpoints": ["crashes"],
        "start_date": "2026-08-28",
        "end_date": "2026-09-04",
        "mode": "api",
    }
    assert data["job_type"] == JobType.CUSTOM
    assert data["enabled"] is False
    assert data["recurrence_type"] == RecurrenceType.ONCE
    assert job_service.create_job.call_args.kwargs == {"created_by": "manual-sync"}
    job_service.execute_job.assert_awaited_once_with(17, force=True)


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": "2024-01-01"},
        {"end_date": "2024-01-07"},
        {"start_date": "2024-01-01", "end_date": "2024-01-07"},
    ],
)
def test_all_endpoints_and_partial_date_bounds_preserved(client, job_service, dates):
    response = client.post("/sync/trigger", json=dates)
    assert response.status_code == 202
    config = job_service.create_job.call_args.args[0]["config"]
    assert config["endpoints"] == list(settings.api.endpoints)
    assert config["start_date"] == dates.get("start_date")
    assert config["end_date"] == dates.get("end_date")
    assert config["mode"] == "api"
    job_service.execute_job.assert_awaited_once_with(17, force=False)


@pytest.mark.parametrize(
    "mode,job_type",
    [
        (None, JobType.INCREMENTAL),
        ("incremental", JobType.INCREMENTAL),
        ("full", JobType.FULL_REFRESH),
        ("api", JobType.CUSTOM),
    ],
)
def test_undated_refresh_mode(client, job_service, mode, job_type):
    response = client.post("/sync/trigger", json={} if mode is None else {"mode": mode})
    assert response.status_code == 202
    data = job_service.create_job.call_args.args[0]
    assert data["job_type"] == job_type
    assert data["config"]["mode"] == (mode or "incremental")
    assert data["timeout_minutes"] == (480 if mode == "full" else 60)


@pytest.mark.parametrize(
    "payload",
    [
        {"start_date": "2024-01-15", "end_date": "2024-01-01"},
        {"start_date": "not-a-date"},
        {"end_date": "2024-02-30"},
        {"start_date": "2024-01-01T00:00:00"},
        {"start_date": ""},
        {"mode": "full", "start_date": "2024-01-01"},
        {"mode": "full", "end_date": "2024-01-07"},
        {"endpoint": "unknown"},
        {"mode": "unknown"},
    ],
)
def test_invalid_requests_do_not_enqueue(client, job_service, payload):
    response = client.post("/sync/trigger", json=payload)
    assert response.status_code == 422
    job_service.create_job.assert_not_called()
    job_service.execute_job.assert_not_awaited()


@pytest.mark.parametrize("method", ["create_job", "execute_job"])
def test_enqueue_database_failure_is_service_unavailable(client, job_service, method):
    getattr(job_service, method).side_effect = OperationalError(
        "SELECT private_credentials", {}, Exception("internal-host-secret")
    )
    response = client.post("/sync/trigger", json={})
    assert response.status_code == 503
    assert "internal-host-secret" not in response.text
    assert "private_credentials" not in response.text
    if method == "create_job":
        job_service.execute_job.assert_not_awaited()


@pytest.mark.parametrize("active_status", [JobStatus.PENDING, JobStatus.RUNNING])
def test_status_reads_durable_execution(client, monkeypatch, active_status):
    session = MagicMock()
    latest_query, successful_query, active_query = MagicMock(), MagicMock(), MagicMock()
    counts_query = MagicMock()
    counts_query.group_by.return_value.all.return_value = [(JobStatus.COMPLETED, 1)]
    session.query.side_effect = [
        latest_query,
        successful_query,
        active_query,
        counts_query,
    ]
    latest_query.order_by.return_value.first.return_value = SimpleNamespace(
        error_message=None, execution_id="exec_latest"
    )
    successful_query.filter.return_value.scalar.return_value = datetime(2026, 9, 3)
    active_query.filter.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=active_status, execution_id="exec_active")
    )
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(sync, "SessionLocal", factory)
    response = client.get("/sync/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == active_status.value
    assert data["current_operation"] == "exec_active"
    assert data["last_sync"].startswith("2026-09-03")
    assert data["stats"]["last_execution_id"] == "exec_latest"


def test_status_database_failure_is_service_unavailable(client, monkeypatch):
    monkeypatch.setattr(
        sync,
        "SessionLocal",
        MagicMock(
            side_effect=OperationalError(
                "SELECT private_credentials", {}, Exception("internal-host-secret")
            )
        ),
    )
    response = client.get("/sync/status")
    assert response.status_code == 503
    assert "internal-host-secret" not in response.text
    assert "private_credentials" not in response.text


def test_sync_result_processing_counts_remain_distinct():
    result = SyncResult(started_at=datetime(2026, 9, 4))
    result.endpoint_results["crashes"] = EndpointSyncResult(
        name="crashes",
        records_fetched=42,
        records_inserted=30,
        records_updated=10,
        records_skipped=2,
    )
    result.endpoint_results["people"] = EndpointSyncResult(
        name="people",
        records_fetched=7,
        records_inserted=5,
        records_updated=1,
        records_skipped=1,
    )
    assert result.total_records == 49
    assert result.total_inserted == 35
    assert result.total_updated == 11
    assert result.total_skipped == 3
    empty = SyncResult(started_at=datetime(2026, 9, 4))
    assert empty.total_records == empty.total_inserted == empty.total_updated == 0

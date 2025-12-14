"""Test for last 7 days data refresh functionality."""

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.api.dependencies import sync_state as global_sync_state
from src.services.sync_service import EndpointSyncResult, SyncResult
from src.utils.config import settings

BASE_SYNC_STATS = {
    "total_syncs": 0,
    "successful_syncs": 0,
    "failed_syncs": 0,
    "last_error": None,
    "total_records_processed": 0,
    "last_sync_duration": None,
}


def make_sync_result(endpoint_counts: dict) -> SyncResult:
    """Construct a SyncResult populated with endpoint metrics."""
    result = SyncResult(started_at=datetime.utcnow())
    for name, counts in endpoint_counts.items():
        result.endpoint_results[name] = EndpointSyncResult(
            name=name,
            batches_processed=counts.get("batches", 1),
            records_fetched=counts.get("fetched", 0),
            records_inserted=counts.get("inserted", 0),
            records_updated=counts.get("updated", 0),
            records_skipped=counts.get("skipped", 0),
        )
    result.completed_at = datetime.utcnow()
    return result


class TestLast7DaysRefresh:
    """Test the functionality to refresh the last 7 days of data."""

    @pytest.fixture(autouse=True)
    def reset_sync_state(self):
        """Ensure shared sync state starts clean for every test."""
        global_sync_state["status"] = "idle"
        global_sync_state["last_sync"] = None
        global_sync_state["current_operation"] = None
        global_sync_state["stats"].update(BASE_SYNC_STATS)
        yield
        global_sync_state["status"] = "idle"
        global_sync_state["current_operation"] = None

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)

    @pytest.fixture
    def seven_days_ago_date(self):
        """Get the date 7 days ago in YYYY-MM-DD format."""
        return (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    @pytest.fixture
    def today_date(self):
        """Get today's date in YYYY-MM-DD format."""
        return datetime.now().strftime("%Y-%m-%d")

    @pytest.fixture
    def sample_recent_crashes(self):
        """Sample crash records from the last 7 days."""
        base_date = datetime.now() - timedelta(days=7)
        return [
            {
                "crash_record_id": f"RECENT{i}",
                "crash_date": (base_date + timedelta(days=i)).isoformat(),
                "latitude": "41.8781",
                "longitude": "-87.6298",
                "injuries_total": "1",
                "street_name": "MICHIGAN AVE",
            }
            for i in range(7)
        ]

    @patch("src.api.routers.sync.SyncService")
    def test_trigger_last_7_days_sync(
        self,
        mock_sync_service_cls,
        client,
        seven_days_ago_date,
        today_date,
        sample_recent_crashes,
    ):
        """Test triggering a sync for the last 7 days of data."""
        sync_result = make_sync_result(
            {
                "crashes": {
                    "fetched": len(sample_recent_crashes),
                    "inserted": len(sample_recent_crashes),
                }
            }
        )

        mock_service = mock_sync_service_cls.return_value
        mock_service.sync = AsyncMock(return_value=sync_result)

        response = client.post(
            "/sync/trigger",
            json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "endpoint": "crashes",
                "force": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "sync_id" in data
        assert "started_at" in data

        time.sleep(0.05)

        mock_service.sync.assert_awaited_once_with(
            endpoints=["crashes"],
            start_date=seven_days_ago_date,
            end_date=today_date,
        )

    @patch("src.api.routers.sync.SyncService")
    def test_last_7_days_data_processing(
        self,
        mock_sync_service_cls,
        client,
        seven_days_ago_date,
        today_date,
    ):
        """Test that sync results update aggregated stats."""
        sync_result = make_sync_result(
            {
                "crashes": {
                    "fetched": 42,
                    "inserted": 30,
                    "updated": 10,
                    "skipped": 2,
                }
            }
        )

        mock_service = mock_sync_service_cls.return_value
        mock_service.sync = AsyncMock(return_value=sync_result)

        base_processed = global_sync_state["stats"]["total_records_processed"]

        response = client.post(
            "/sync/trigger",
            json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "endpoint": "crashes",
                "force": True,
            },
        )

        assert response.status_code == 200

        time.sleep(0.05)

        assert (
            global_sync_state["stats"]["total_records_processed"]
            == base_processed + sync_result.total_records
        )
        assert global_sync_state["stats"]["successful_syncs"] == 1
        assert global_sync_state["status"] == "idle"

    def test_sync_status_during_last_7_days_refresh(self, client):
        """Test sync status endpoint reflects running state."""
        global_sync_state["status"] = "running"
        global_sync_state["current_operation"] = "Manual sync test"

        status_response = client.get("/sync/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["status"] == "running"
        assert "Manual sync" in data["current_operation"]

    @patch("src.api.routers.sync.SyncService")
    def test_invalid_date_range_for_refresh(self, mock_sync_service_cls, client):
        """Test sync with invalid date range."""
        mock_service = mock_sync_service_cls.return_value
        all_endpoints_result = make_sync_result(
            {name: {"fetched": 0} for name in settings.api.endpoints}
        )
        mock_service.sync = AsyncMock(return_value=all_endpoints_result)

        response = client.post(
            "/sync/trigger",
            json={
                "start_date": "2024-01-15",
                "end_date": "2024-01-01",
                "endpoint": "crashes",
            },
        )

        assert response.status_code == 200
        time.sleep(0.05)

    def test_concurrent_sync_prevention(self, client, seven_days_ago_date):
        """Test that a running sync rejects new trigger requests."""
        global_sync_state["status"] = "running"
        global_sync_state["current_operation"] = "Manual sync 123"

        response = client.post(
            "/sync/trigger",
            json={"start_date": seven_days_ago_date, "endpoint": "crashes"},
        )

        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"]

    @patch("src.api.routers.sync.SyncService")
    def test_empty_result_handling(
        self,
        mock_sync_service_cls,
        client,
        seven_days_ago_date,
        today_date,
    ):
        """Test handling when no records are found in the last 7 days."""
        mock_service = mock_sync_service_cls.return_value
        mock_service.sync = AsyncMock(
            return_value=make_sync_result({"crashes": {"fetched": 0}})
        )

        response = client.post(
            "/sync/trigger",
            json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "endpoint": "crashes",
            },
        )

        assert response.status_code == 200
        time.sleep(0.05)

    @patch("src.api.routers.sync.SyncService")
    def test_multiple_endpoint_sync_last_7_days(
        self,
        mock_sync_service_cls,
        client,
        seven_days_ago_date,
        today_date,
    ):
        """Test syncing multiple endpoints for the last 7 days."""
        mock_service = mock_sync_service_cls.return_value
        mock_service.sync = AsyncMock(
            return_value=make_sync_result({"crashes": {"fetched": 0}})
        )

        response = client.post(
            "/sync/trigger",
            json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "force": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

        time.sleep(0.05)

        mock_service.sync.assert_awaited_once_with(
            endpoints=list(settings.api.endpoints.keys()),
            start_date=seven_days_ago_date,
            end_date=today_date,
        )

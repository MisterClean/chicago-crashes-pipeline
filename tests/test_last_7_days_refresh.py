"""Test for last 7 days data refresh functionality."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app


class TestLast7DaysRefresh:
    """Test the functionality to refresh the last 7 days of data."""
    
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
    def sample_recent_crashes(self, seven_days_ago_date):
        """Sample crash records from the last 7 days."""
        base_date = datetime.now() - timedelta(days=7)
        return [
            {
                "crash_record_id": f"RECENT{i}",
                "crash_date": (base_date + timedelta(days=i)).isoformat(),
                "latitude": "41.8781",
                "longitude": "-87.6298",
                "injuries_total": "1",
                "street_name": "MICHIGAN AVE"
            }
            for i in range(7)  # Create 7 records, one for each of the last 7 days
        ]
    
    @patch("api.routers.sync.SODAClient")
    @patch("api.routers.sync.DataSanitizer") 
    @patch("api.routers.sync.DatabaseService")
    def test_trigger_last_7_days_sync(
        self, 
        mock_db_service, 
        mock_sanitizer, 
        mock_client_class,
        client, 
        seven_days_ago_date, 
        today_date, 
        sample_recent_crashes
    ):
        """Test triggering a sync for the last 7 days of data."""
        # Mock SODAClient
        mock_client_instance = AsyncMock()
        mock_client_class.return_value = mock_client_instance
        mock_client_instance.fetch_all_records.return_value = sample_recent_crashes
        
        # Mock DataSanitizer
        mock_sanitizer_instance = MagicMock()
        mock_sanitizer.return_value = mock_sanitizer_instance
        mock_sanitizer_instance.sanitize_crash_record.side_effect = lambda x: {
            **x,
            "sanitized": True
        }
        
        # Mock DatabaseService
        mock_db_instance = MagicMock()
        mock_db_service.return_value = mock_db_instance
        mock_db_instance.insert_crash_records.return_value = {
            "inserted": len(sample_recent_crashes),
            "updated": 0,
            "skipped": 0
        }
        
        # Trigger sync for last 7 days
        response = client.post("/sync/trigger", json={
            "start_date": seven_days_ago_date,
            "end_date": today_date,
            "endpoint": "crashes",
            "force": True
        })
        
        # Verify successful trigger
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "sync_id" in data
        assert "started_at" in data
        
        # Give background task a moment to start
        import time
        time.sleep(0.1)
        
        # Verify client was called with correct date range
        mock_client_instance.fetch_all_records.assert_called_once()
        call_kwargs = mock_client_instance.fetch_all_records.call_args[1]
        assert call_kwargs["start_date"] == seven_days_ago_date
        assert call_kwargs["end_date"] == today_date
        assert call_kwargs["date_field"] == "crash_date"
    
    @patch("api.routers.sync.SODAClient")
    @patch("api.routers.sync.DataSanitizer") 
    @patch("api.routers.sync.DatabaseService")
    def test_last_7_days_data_processing(
        self, 
        mock_db_service, 
        mock_sanitizer, 
        mock_client_class,
        client, 
        seven_days_ago_date, 
        today_date, 
        sample_recent_crashes
    ):
        """Test that last 7 days data is properly processed and sanitized."""
        # Mock SODAClient
        mock_client_instance = AsyncMock()
        mock_client_class.return_value = mock_client_instance
        mock_client_instance.fetch_all_records.return_value = sample_recent_crashes
        
        # Mock DataSanitizer - track sanitization calls
        mock_sanitizer_instance = MagicMock()
        mock_sanitizer.return_value = mock_sanitizer_instance
        sanitized_records = []
        
        def track_sanitization(record):
            sanitized = {**record, "sanitized": True}
            sanitized_records.append(sanitized)
            return sanitized
        
        mock_sanitizer_instance.sanitize_crash_record.side_effect = track_sanitization
        
        # Mock DatabaseService
        mock_db_instance = MagicMock()
        mock_db_service.return_value = mock_db_instance
        mock_db_instance.insert_crash_records.return_value = {
            "inserted": len(sample_recent_crashes),
            "updated": 0,
            "skipped": 0
        }
        
        # Trigger sync
        response = client.post("/sync/trigger", json={
            "start_date": seven_days_ago_date,
            "end_date": today_date,
            "endpoint": "crashes",
            "force": True
        })
        
        assert response.status_code == 200
        
        # Give background task time to complete
        import time
        time.sleep(0.5)
        
        # Verify all records were sanitized
        assert mock_sanitizer_instance.sanitize_crash_record.call_count == len(sample_recent_crashes)
        
        # Verify database insertion was called
        mock_db_instance.insert_crash_records.assert_called_once()
        inserted_records = mock_db_instance.insert_crash_records.call_args[0][0]
        assert len(inserted_records) == len(sample_recent_crashes)
        assert all(record.get("sanitized") for record in inserted_records)
    
    def test_sync_status_during_last_7_days_refresh(self, client, seven_days_ago_date, today_date):
        """Test sync status endpoint while a 7-day refresh is running."""
        # First check initial status
        status_response = client.get("/sync/status")
        assert status_response.status_code == 200
        initial_status = status_response.json()
        assert initial_status["status"] == "idle"
        
        # Trigger 7-day sync (this will run in background)
        with patch("api.routers.sync.SODAClient"), \
             patch("api.routers.sync.DataSanitizer"), \
             patch("api.routers.sync.DatabaseService"):
            
            trigger_response = client.post("/sync/trigger", json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "endpoint": "crashes"
            })
            assert trigger_response.status_code == 200
            
            # Check status immediately after trigger
            status_response = client.get("/sync/status")
            assert status_response.status_code == 200
            running_status = status_response.json()
            assert running_status["status"] == "running"
            assert "Manual sync" in running_status["current_operation"]
    
    def test_invalid_date_range_for_refresh(self, client):
        """Test sync with invalid date range."""
        # Test with end date before start date
        response = client.post("/sync/trigger", json={
            "start_date": "2024-01-15",
            "end_date": "2024-01-01",  # Before start date
            "endpoint": "crashes"
        })
        
        # Should still trigger (validation happens in the background task)
        assert response.status_code == 200
    
    def test_concurrent_sync_prevention(self, client, seven_days_ago_date, today_date):
        """Test that concurrent syncs are prevented."""
        with patch("api.routers.sync.SODAClient"), \
             patch("api.routers.sync.DataSanitizer"), \
             patch("api.routers.sync.DatabaseService"):
            
            # Trigger first sync
            response1 = client.post("/sync/trigger", json={
                "start_date": seven_days_ago_date,
                "endpoint": "crashes"
            })
            assert response1.status_code == 200
            
            # Try to trigger second sync immediately
            response2 = client.post("/sync/trigger", json={
                "start_date": seven_days_ago_date,
                "endpoint": "crashes"
            })
            
            # Should be rejected due to sync already running
            assert response2.status_code == 409
            assert "already in progress" in response2.json()["detail"]
    
    @patch("api.routers.sync.SODAClient")
    def test_empty_result_handling(self, mock_client_class, client, seven_days_ago_date, today_date):
        """Test handling when no records are found in the last 7 days."""
        # Mock SODAClient to return empty results
        mock_client_instance = AsyncMock()
        mock_client_class.return_value = mock_client_instance
        mock_client_instance.fetch_all_records.return_value = []
        
        with patch("api.routers.sync.DataSanitizer"), \
             patch("api.routers.sync.DatabaseService"):
            
            response = client.post("/sync/trigger", json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "endpoint": "crashes"
            })
            
            assert response.status_code == 200
            # The sync should still succeed even with no records
    
    def test_multiple_endpoint_sync_last_7_days(self, client, seven_days_ago_date, today_date):
        """Test syncing multiple endpoints for the last 7 days."""
        with patch("api.routers.sync.SODAClient") as mock_client_class, \
             patch("api.routers.sync.DataSanitizer") as mock_sanitizer, \
             patch("api.routers.sync.DatabaseService") as mock_db_service:
            
            # Mock all required methods
            mock_client_instance = AsyncMock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.fetch_all_records.return_value = []
            
            mock_sanitizer_instance = MagicMock()
            mock_sanitizer.return_value = mock_sanitizer_instance
            
            mock_db_instance = MagicMock()
            mock_db_service.return_value = mock_db_instance
            mock_db_instance.insert_crash_records.return_value = {"inserted": 0, "updated": 0, "skipped": 0}
            mock_db_instance.insert_person_records.return_value = {"inserted": 0, "updated": 0, "skipped": 0}
            mock_db_instance.insert_vehicle_records.return_value = {"inserted": 0, "updated": 0, "skipped": 0}
            mock_db_instance.insert_fatality_records.return_value = {"inserted": 0, "updated": 0, "skipped": 0}
            
            # Trigger sync without specifying endpoint (should sync all endpoints)
            response = client.post("/sync/trigger", json={
                "start_date": seven_days_ago_date,
                "end_date": today_date,
                "force": True
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "running"
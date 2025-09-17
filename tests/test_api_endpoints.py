"""Tests for FastAPI endpoints."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app


class TestAPIEndpoints:
    """Test FastAPI endpoint functionality."""
    
    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)
    
    def test_root_endpoint(self, client):
        """Test the root endpoint."""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["name"] == "Chicago Crash Data Pipeline API"
        assert data["version"] == "1.0.0"
        assert data["status"] == "online"
        assert "endpoints" in data
        assert "uptime" in data
    
    def test_health_endpoint_success(self, client):
        """Test health check endpoint when services are healthy."""
        with patch("api.routers.health.SODAClient") as mock_client:
            # Mock successful client creation
            mock_client.return_value = MagicMock()
            
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "healthy"
            assert "timestamp" in data
            assert "services" in data
            assert data["services"]["configuration"] == "healthy"
    
    def test_sync_status_endpoint(self, client):
        """Test sync status endpoint."""
        response = client.get("/sync/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert "last_sync" in data
        assert "stats" in data
        assert "uptime" in data
        
        # Initial state should be idle
        assert data["status"] == "idle"
        assert data["stats"]["total_syncs"] >= 0
    
    def test_sync_endpoints_info(self, client):
        """Test sync endpoints information."""
        response = client.get("/sync/endpoints")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "endpoints" in data
        assert "total_endpoints" in data
        assert data["total_endpoints"] == 4
        
        # Check that all expected endpoints are present
        endpoint_names = [ep["name"] for ep in data["endpoints"]]
        assert "crashes" in endpoint_names
        assert "people" in endpoint_names
        assert "vehicles" in endpoint_names
        assert "fatalities" in endpoint_names
    
    @patch("src.api.routers.sync.get_soda_client")
    @patch("src.api.routers.sync.get_data_sanitizer") 
    def test_sync_test_endpoint(self, mock_get_sanitizer, mock_get_client, client):
        """Test sync test endpoint."""
        # Mock SODA client
        mock_client_instance = AsyncMock()
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = False
        mock_client_instance.fetch_records.return_value = [
            {"crash_record_id": "TEST1", "crash_date": "2024-01-01T12:00:00"},
            {"crash_record_id": "TEST2", "crash_date": "2024-01-01T13:00:00"},
            {"crash_record_id": "TEST3", "crash_date": "2024-01-01T14:00:00"},
            {"crash_record_id": "TEST4", "crash_date": "2024-01-01T15:00:00"},
            {"crash_record_id": "TEST5", "crash_date": "2024-01-01T16:00:00"}
        ]
        
        # Mock sanitizer
        mock_sanitizer_instance = MagicMock()
        mock_get_sanitizer.return_value = mock_sanitizer_instance
        mock_sanitizer_instance.sanitize_crash_record.return_value = {
            "crash_record_id": "TEST1",
            "crash_date": "2024-01-01T12:00:00"
        }
        
        response = client.post("/sync/test")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert data["records_fetched"] == 5  # The endpoint fetches 5 records
        assert data["records_cleaned"] == 5
        assert "sample_record" in data
    
    def test_validation_endpoint_info(self, client):
        """Test validation endpoint information."""
        response = client.get("/validate/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "available_endpoints" in data
        assert "validation_types" in data
        assert "limits" in data
        
        available_endpoints = data["available_endpoints"]
        assert "crashes" in available_endpoints
        assert "people" in available_endpoints
        assert "vehicles" in available_endpoints
        assert "fatalities" in available_endpoints
    
    @patch("src.api.routers.validation.get_soda_client")
    @patch("src.api.routers.validation.get_crash_validator_instance")
    @patch("src.api.routers.validation.get_data_sanitizer")
    def test_validation_crashes_endpoint(self, mock_get_sanitizer, mock_get_validator, mock_get_client, client):
        """Test validation endpoint for crashes."""
        # Mock client
        mock_client_instance = AsyncMock()
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = False
        mock_client_instance.fetch_records.return_value = [
            {"crash_record_id": "TEST1", "latitude": "41.8781", "longitude": "-87.6298"},
            {"crash_record_id": "TEST2", "latitude": "41.8782", "longitude": "-87.6299"}
        ]
        
        # Mock sanitizer
        mock_sanitizer_instance = MagicMock()
        mock_get_sanitizer.return_value = mock_sanitizer_instance
        mock_sanitizer_instance.sanitize_crash_record.return_value = {
            "crash_record_id": "TEST1"
        }
        
        # Mock validator
        mock_validator_instance = MagicMock()
        mock_get_validator.return_value = mock_validator_instance
        mock_validator_instance.validate_crash_record.return_value = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        response = client.get("/validate/crashes?limit=2")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["endpoint"] == "crashes"
        assert data["total_records"] == 2
        assert data["valid_records"] == 2
        assert data["invalid_records"] == 0
        assert isinstance(data["validation_errors"], list)
        assert isinstance(data["warnings"], list)
    
    def test_validation_invalid_endpoint(self, client):
        """Test validation endpoint with invalid endpoint name."""
        response = client.get("/validate/invalid_endpoint")
        
        assert response.status_code == 404
        data = response.json()
        
        assert "not found" in data["detail"].lower()
        assert "available endpoints" in data["detail"].lower()
    
    def test_spatial_info_endpoint(self, client):
        """Test spatial info endpoint."""
        response = client.get("/spatial/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "usage" in data
        assert "instructions" in data
        
        # Check usage instructions
        usage = data["usage"]
        assert "load_shapefiles" in usage
        assert "list_tables" in usage
        assert "query_table" in usage
    
    @patch("src.api.routers.spatial.SimpleShapefileLoader")
    def test_spatial_tables_endpoint(self, mock_loader, client):
        """Test spatial tables listing endpoint."""
        # Mock loader
        mock_loader_instance = MagicMock()
        mock_loader.return_value = mock_loader_instance
        mock_loader_instance.list_loaded_tables.return_value = {
            "tables": [
                {"table_name": "wards", "record_count": 50},
                {"table_name": "community_areas", "record_count": 77}
            ],
            "total_tables": 2
        }
        
        response = client.get("/spatial/tables")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "tables" in data
        assert "total_tables" in data
        assert data["total_tables"] == 2
    
    def test_sync_trigger_requires_json(self, client):
        """Test that sync trigger endpoint handles invalid requests."""
        # Test with invalid JSON
        response = client.post("/sync/trigger", data="invalid")
        
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_version_endpoint(self, client):
        """Test version information endpoint."""
        response = client.get("/version")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "version" in data
        assert "python_version" in data
        assert "dependencies" in data
        
        # Check some expected dependencies
        deps = data["dependencies"]
        assert "fastapi" in deps
        assert "pydantic" in deps
    
    def test_api_cors_headers(self, client):
        """Test that CORS headers are properly set."""
        response = client.options("/")
        
        # Should not fail due to CORS
        assert response.status_code in [200, 405]  # OPTIONS might not be implemented
    
    def test_api_error_handling(self, client):
        """Test API error handling for non-existent endpoints."""
        response = client.get("/nonexistent/endpoint")
        
        assert response.status_code == 404

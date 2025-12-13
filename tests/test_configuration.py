"""Tests for configuration management."""

from utils.config import (APISettings, DatabaseSettings, ValidationSettings,
                          settings)


class TestConfiguration:
    """Test configuration loading and validation."""

    def test_database_settings_defaults(self):
        """Test database settings have correct defaults."""
        db_settings = DatabaseSettings()

        assert db_settings.host == "localhost"
        assert db_settings.port == 5432
        assert db_settings.database == "chicago_crashes"
        assert db_settings.username == "postgres"
        assert db_settings.pool_size == 10
        assert db_settings.use_copy is True

    def test_database_url_construction(self):
        """Test database URL is constructed correctly."""
        db_settings = DatabaseSettings()
        db_settings.username = "testuser"
        db_settings.password = "testpass"
        db_settings.host = "testhost"
        db_settings.port = 5433
        db_settings.database = "testdb"

        expected_url = "postgresql://testuser:testpass@testhost:5433/testdb"
        assert db_settings.url == expected_url

    def test_api_settings(self):
        """Test API settings are loaded correctly."""
        api_settings = APISettings()

        assert "crashes" in api_settings.endpoints
        assert "people" in api_settings.endpoints
        assert "vehicles" in api_settings.endpoints
        assert "fatalities" in api_settings.endpoints

        assert api_settings.rate_limit == 1000
        assert api_settings.batch_size == 50000
        assert api_settings.max_concurrent == 5

    def test_validation_settings(self):
        """Test validation settings for Chicago bounds."""
        validation_settings = ValidationSettings()

        # Chicago latitude bounds
        assert 41.0 < validation_settings.min_latitude < 42.0
        assert 42.0 < validation_settings.max_latitude < 43.0

        # Chicago longitude bounds (negative values)
        assert -88.0 < validation_settings.min_longitude < -87.0
        assert -88.0 < validation_settings.max_longitude < -87.0

        # Age bounds
        assert validation_settings.min_age == 0
        assert validation_settings.max_age == 120

        # Vehicle year bounds
        assert validation_settings.min_vehicle_year >= 1900
        assert validation_settings.max_vehicle_year >= 2024

    def test_required_fields(self):
        """Test required fields are defined for all dataset types."""
        validation_settings = ValidationSettings()

        assert "crashes" in validation_settings.required_fields
        assert "people" in validation_settings.required_fields
        assert "vehicles" in validation_settings.required_fields
        assert "fatalities" in validation_settings.required_fields

        # Crashes should require record ID and date
        crashes_fields = validation_settings.required_fields["crashes"]
        assert "crash_record_id" in crashes_fields
        assert "crash_date" in crashes_fields

    def test_global_settings_loading(self):
        """Test global settings instance is loaded correctly."""
        assert settings is not None
        assert hasattr(settings, "database")
        assert hasattr(settings, "api")
        assert hasattr(settings, "validation")
        assert hasattr(settings, "spatial")
        assert hasattr(settings, "logging")

    def test_chicago_api_endpoints(self):
        """Test Chicago Open Data Portal endpoints are correct."""
        endpoints = settings.api.endpoints

        # All endpoints should point to Chicago data portal
        for name, url in endpoints.items():
            assert url.startswith("https://data.cityofchicago.org")
            assert url.endswith(".json")

        # Specific endpoint checks
        assert "85ca-t3if" in endpoints["crashes"]  # Crashes dataset ID
        assert "u6pd-qa9d" in endpoints["people"]  # People dataset ID
        assert "68nd-jvt3" in endpoints["vehicles"]  # Vehicles dataset ID
        assert "gzaz-isa6" in endpoints["fatalities"]  # Fatalities dataset ID

"""Configuration management for the Chicago crash data pipeline."""
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    host: str = "localhost"
    port: int = 5432
    database: str = "chicago_crashes"
    username: str = "postgres"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    bulk_insert_size: int = 1000
    use_copy: bool = True

    model_config = {"env_prefix": "DB_"}

    @property
    def url(self) -> str:
        """Get SQLAlchemy database URL."""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


class APISettings(BaseSettings):
    """API configuration settings."""

    endpoints: Dict[str, str] = {
        "crashes": "https://data.cityofchicago.org/resource/85ca-t3if.json",
        "people": "https://data.cityofchicago.org/resource/u6pd-qa9d.json",
        "vehicles": "https://data.cityofchicago.org/resource/68nd-jvt3.json",
        "fatalities": "https://data.cityofchicago.org/resource/gzaz-isa6.json",
    }
    rate_limit: int = 1000
    timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 2.0
    batch_size: int = 50000
    max_concurrent: int = 5
    token: Optional[str] = None

    model_config = {
        "env_prefix": "CHICAGO_API_"
    }  # Maps token field to CHICAGO_API_TOKEN env var


class SyncSettings(BaseSettings):
    """Sync configuration settings."""

    default_start_date: str = "2017-09-01"
    sync_interval: int = 6  # hours
    chunk_size: int = 50000
    progress_bar: bool = True
    log_retention_days: int = 30


class ValidationSettings(BaseSettings):
    """Data validation settings."""

    min_latitude: float = 41.6
    max_latitude: float = 42.1
    min_longitude: float = -87.95
    max_longitude: float = -87.5
    min_age: int = 0
    max_age: int = 120
    min_vehicle_year: int = 1900
    max_vehicle_year: int = 2025

    required_fields: Dict[str, list] = {
        "crashes": ["crash_record_id", "crash_date"],
        "people": ["crash_record_id", "person_id"],
        "vehicles": ["crash_record_id", "unit_no"],
        "fatalities": ["person_id"],
    }


class SpatialSettings(BaseSettings):
    """Spatial data settings."""

    shapefiles: Dict[str, str] = {
        "wards": "data/shapefiles/chicago_wards.shp",
        "community_areas": "data/shapefiles/community_areas.shp",
        "census_tracts": "data/shapefiles/census_tracts.shp",
        "police_beats": "data/shapefiles/police_beats.shp",
        "house_districts": "data/shapefiles/house_districts.shp",
        "senate_districts": "data/shapefiles/senate_districts.shp",
    }
    srid: int = 4326  # WGS84


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    level: str = "INFO"
    format: str = "json"
    files: Dict[str, str] = {
        "app": "logs/app.log",
        "etl": "logs/etl.log",
        "api": "logs/api.log",
    }
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5

    model_config = {"env_prefix": "LOG_"}  # Maps level field to LOG_LEVEL env var


class Settings(BaseSettings):
    """Main application settings."""

    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Sub-settings
    database: DatabaseSettings = DatabaseSettings()
    api: APISettings = APISettings()
    sync: SyncSettings = SyncSettings()
    validation: ValidationSettings = ValidationSettings()
    spatial: SpatialSettings = SpatialSettings()
    logging: LoggingSettings = LoggingSettings()

    model_config = {"env_file": ".env", "extra": "ignore"}


def _resolve_template_strings(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ${ENV_VAR:default} template strings in configuration.

    Args:
        config_dict: Configuration dictionary with potential template strings

    Returns:
        Configuration dictionary with resolved template strings
    """

    def resolve_value(value):
        if isinstance(value, str):
            # Pattern matches ${ENV_VAR:default_value} or ${ENV_VAR}
            pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

            def replace_match(match):
                env_var = match.group(1)
                default_value = match.group(2) if match.group(2) is not None else ""
                return os.getenv(env_var, default_value)

            return re.sub(pattern, replace_match, value)
        elif isinstance(value, dict):
            return {k: resolve_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [resolve_value(item) for item in value]
        else:
            return value

    return resolve_value(config_dict)


def load_config(config_path: Optional[Path] = None) -> Settings:
    """Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to YAML config file. Defaults to config/config.yaml

    Returns:
        Settings object with loaded configuration
    """
    if config_path is None:
        config_path = Path("config/config.yaml")

    settings = Settings()

    # Load YAML config if it exists
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)

        # Resolve template strings
        if yaml_config:
            yaml_config = _resolve_template_strings(yaml_config)
            _update_settings_from_dict(settings, yaml_config)

    return settings


def _update_settings_from_dict(settings: Settings, config_dict: Dict[str, Any]) -> None:
    """Update settings object with values from dictionary.

    Args:
        settings: Settings object to update
        config_dict: Dictionary with configuration values
    """
    for key, value in config_dict.items():
        if hasattr(settings, key):
            attr = getattr(settings, key)
            if isinstance(attr, BaseSettings):
                # Recursively update nested settings
                if isinstance(value, dict):
                    for nested_key, nested_value in value.items():
                        if hasattr(attr, nested_key):
                            setattr(attr, nested_key, nested_value)
            else:
                setattr(settings, key, value)


def validate_configuration(settings: Settings) -> None:
    """Validate configuration and warn about insecure settings.

    Args:
        settings: Settings object to validate

    Raises:
        ValueError: If critical security issues detected in production
    """
    import warnings

    # Check for default passwords
    if settings.database.password in ["postgres", "password", "", "your_password_here"]:
        if settings.environment == "production":
            raise ValueError(
                "SECURITY ERROR: Default database password detected in production. "
                "Set a strong password in DB_PASSWORD environment variable. "
                "Generate one with: openssl rand -base64 32"
            )
        else:
            warnings.warn(
                "Using default database password. This is OK for development, "
                "but NEVER use default passwords in production.",
                UserWarning,
            )

    # Check for wildcard CORS (this would be set in environment, not in settings)
    cors_origins = os.getenv("CORS_ORIGINS", "")
    if "*" in cors_origins:
        if settings.environment == "production":
            raise ValueError(
                "SECURITY ERROR: Wildcard CORS origin (*) detected in production. "
                "This is a critical security vulnerability when allow_credentials=True. "
                "Set specific allowed origins in CORS_ORIGINS environment variable."
            )
        else:
            warnings.warn(
                "Wildcard CORS origin detected. This is a security risk. "
                "Set specific origins in CORS_ORIGINS environment variable.",
                UserWarning,
            )

    # Validate API token for production
    if settings.environment == "production":
        if not settings.api.token:
            warnings.warn(
                "No Chicago Data Portal API token configured for production. "
                "Request rate will be limited to 1000 requests/hour. "
                "Get a token at: https://data.cityofchicago.org/profile/app_tokens",
                UserWarning,
            )

    # Check database password strength (basic check)
    if settings.database.password and len(settings.database.password) < 12:
        if settings.environment == "production":
            warnings.warn(
                "Database password is shorter than 12 characters. "
                "Use a strong password (32+ characters recommended). "
                "Generate with: openssl rand -base64 32",
                UserWarning,
            )


# Global settings instance
settings = load_config()

# Validate configuration on load
validate_configuration(settings)

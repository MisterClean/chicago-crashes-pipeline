"""Configuration management for the Chicago crash data pipeline."""
import os
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
        "fatalities": "https://data.cityofchicago.org/resource/gzaz-isa6.json"
    }
    rate_limit: int = 1000
    timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 2.0
    batch_size: int = 50000
    max_concurrent: int = 5
    token: Optional[str] = Field(default=None, env="CHICAGO_API_TOKEN")


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
        "fatalities": ["person_id"]
    }


class SpatialSettings(BaseSettings):
    """Spatial data settings."""
    
    shapefiles: Dict[str, str] = {
        "wards": "data/shapefiles/chicago_wards.shp",
        "community_areas": "data/shapefiles/community_areas.shp", 
        "census_tracts": "data/shapefiles/census_tracts.shp",
        "police_beats": "data/shapefiles/police_beats.shp",
        "house_districts": "data/shapefiles/house_districts.shp",
        "senate_districts": "data/shapefiles/senate_districts.shp"
    }
    srid: int = 4326  # WGS84


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""
    
    level: str = Field(default="INFO", env="LOG_LEVEL")
    format: str = "json"
    files: Dict[str, str] = {
        "app": "logs/app.log",
        "etl": "logs/etl.log", 
        "api": "logs/api.log"
    }
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5


class Settings(BaseSettings):
    """Main application settings."""
    
    environment: str = Field(default="development", env="ENVIRONMENT")
    api_host: str = Field(default="0.0.0.0", env="API_HOST") 
    api_port: int = Field(default=8000, env="API_PORT")
    
    # Sub-settings
    database: DatabaseSettings = DatabaseSettings()
    api: APISettings = APISettings()
    sync: SyncSettings = SyncSettings()
    validation: ValidationSettings = ValidationSettings()
    spatial: SpatialSettings = SpatialSettings()
    logging: LoggingSettings = LoggingSettings()
    
    model_config = {"env_file": ".env", "extra": "ignore"}


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
            
        # Update settings with YAML values
        if yaml_config:
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


# Global settings instance
settings = load_config()
"""FastAPI dependencies for the Chicago crash data pipeline API."""
import sys
from pathlib import Path
from typing import Generator

sys.path.append(str(Path(__file__).parent.parent))
from etl.soda_client import SODAClient
from validators.data_sanitizer import DataSanitizer
from validators.crash_validator import CrashValidator
from utils.logging import get_logger

logger = get_logger(__name__)


def get_soda_client() -> Generator[SODAClient, None, None]:
    """Dependency to provide SODA client instance."""
    client = SODAClient()
    try:
        yield client
    finally:
        # Client cleanup would go here if needed
        pass


def get_data_sanitizer() -> DataSanitizer:
    """Dependency to provide data sanitizer instance."""
    return DataSanitizer()


def get_crash_validator() -> CrashValidator:
    """Dependency to provide crash validator instance."""
    return CrashValidator()


# Global sync state - in production, this would be stored in Redis or database
sync_state = {
    "status": "idle",  # idle, running, testing, error
    "last_sync": None,
    "current_operation": None,
    "stats": {
        "total_syncs": 0,
        "successful_syncs": 0,
        "failed_syncs": 0,
        "last_error": None,
        "total_records_processed": 0,
        "last_sync_duration": None
    }
}


def get_sync_state() -> dict:
    """Dependency to provide sync state."""
    return sync_state
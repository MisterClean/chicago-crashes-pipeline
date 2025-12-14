---
title: Testing & Quality
sidebar_position: 2
description: Testing strategy, fixtures, and coverage expectations.
---

## Testing Strategy

The project uses [pytest](https://docs.pytest.org/) for unit and integration tests with SQLAlchemy-backed fixtures.

| Layer | Examples | Notes |
| --- | --- | --- |
| Pure functions | Validators, utilities | Aim for deterministic, side-effect free tests |
| Service layer | `SyncService`, `JobService` | Mock external dependencies (SODA API, Redis) using pytest fixtures |
| API routers | FastAPI `TestClient` assertions | Validate status codes, schemas, and background task behaviour |

## Fixtures

Key fixtures live in `tests/conftest.py`:

- `session` / `db_engine` – create isolated in-memory or temporary PostgreSQL databases.
- `test_client` – FastAPI client with dependency overrides for external services.
- `soda_responses` – stubbed SODA API payloads for deterministic sync tests.

Reuse these fixtures to avoid brittle setup code in individual tests.

## Coverage Targets

- Maintain **80%+** line coverage for critical modules (`src/services`, `src/api/routers`, `src/validators`).
- Ensure each new feature includes corresponding tests. For regressions, add tests that fail without the fix.

## Running Tests

```bash
# All tests
make test
# Or: pytest tests -v

# With coverage report
pytest tests --cov=src --cov-report=term-missing
pytest tests --cov=src --cov-report=html  # HTML report at htmlcov/index.html

# Run specific test file
pytest tests/test_soda_client.py -v

# Run specific test function
pytest tests/test_soda_client.py::test_fetch_records -v

# Run tests matching pattern
pytest -v -k test_sync

# Run with verbose output and print statements
pytest -v -s

# Run failed tests from last run
pytest --lf

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## Test Data

Large fixtures (crash samples, people, vehicles) reside in `tests/fixtures/`. Keep them small and anonymised. For new datasets, prefer synthesised JSON snippets rather than copying full records.

## Writing New Tests

### Test Structure

Follow the Arrange-Act-Assert pattern:

```python
def test_sanitize_coordinates():
    """Test coordinate sanitization for Chicago bounds."""
    # Arrange
    sanitizer = DataSanitizer()
    crash_data = {
        "crash_record_id": "TEST123",
        "latitude": "41.8781",  # Valid Chicago latitude
        "longitude": "-87.6298"  # Valid Chicago longitude
    }

    # Act
    result = sanitizer.sanitize_crash_record(crash_data)

    # Assert
    assert result["latitude"] == 41.8781
    assert result["longitude"] == -87.6298
    assert result["crash_record_id"] == "TEST123"
```

### Testing Service Layer

Example service test with mocked dependencies:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.sync_service import SyncService

@pytest.mark.asyncio
async def test_sync_crashes_success():
    """Test successful crash sync."""
    # Arrange
    mock_soda_client = AsyncMock()
    mock_soda_client.fetch_records.return_value = [
        {"crash_record_id": "1", "crash_date": "2023-01-01"},
        {"crash_record_id": "2", "crash_date": "2023-01-02"}
    ]

    service = SyncService(soda_client=mock_soda_client)

    # Act
    result = await service.sync_crashes(start_date="2023-01-01")

    # Assert
    assert result.success is True
    assert result.records_processed == 2
    mock_soda_client.fetch_records.assert_called_once()
```

### Testing API Endpoints

Use FastAPI's TestClient for route testing:

```python
from fastapi.testclient import TestClient
from src.api.main import app

def test_health_endpoint():
    """Test health check endpoint."""
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

### Testing with Database

Use pytest fixtures for database tests:

```python
def test_create_job(db_session):
    """Test job creation in database."""
    from src.models.jobs import Job

    # Create job
    job = Job(
        name="Test Sync",
        job_type="sync",
        config={"endpoint": "crashes"}
    )
    db_session.add(job)
    db_session.commit()

    # Verify
    retrieved = db_session.query(Job).filter_by(name="Test Sync").first()
    assert retrieved is not None
    assert retrieved.job_type == "sync"
```

## Mocking Patterns

### Mocking External APIs

Mock SODA API responses using pytest fixtures:

```python
# tests/conftest.py
@pytest.fixture
def mock_soda_response():
    """Mock SODA API response."""
    return [
        {
            "crash_record_id": "123",
            "crash_date": "2023-01-01T10:00:00",
            "latitude": "41.8781",
            "longitude": "-87.6298"
        }
    ]

@pytest.fixture
def mock_soda_client(mock_soda_response):
    """Mock SODA client."""
    client = AsyncMock()
    client.fetch_records.return_value = mock_soda_response
    return client
```

Usage in tests:

```python
async def test_with_mocked_api(mock_soda_client):
    service = SyncService(soda_client=mock_soda_client)
    result = await service.sync_crashes()
    assert result.records_processed > 0
```

### Mocking Database Operations

Mock database queries without hitting the actual database:

```python
from unittest.mock import MagicMock, patch

def test_database_operation():
    with patch('src.services.database_service.Session') as mock_session:
        mock_db = MagicMock()
        mock_session.return_value = mock_db

        # Test your service
        service = DatabaseService()
        result = service.get_crashes(limit=10)

        # Verify database was called correctly
        mock_db.query.assert_called_once()
```

### Mocking Time-Dependent Code

Use `freezegun` for time-based tests:

```python
from freezegun import freeze_time
from datetime import datetime

@freeze_time("2023-01-15 12:00:00")
def test_date_filtering():
    """Test with frozen time."""
    service = SyncService()
    # Code that uses datetime.now() will always see 2023-01-15 12:00:00
    assert datetime.now().day == 15
```

## Integration Tests

### Database Integration Tests

Test full database workflow:

```python
@pytest.mark.integration
def test_full_sync_workflow(db_session):
    """Test complete sync from API to database."""
    # This test hits the real database (slower, more comprehensive)
    service = SyncService()

    # Run sync
    result = service.sync_crashes(start_date="2023-01-01", end_date="2023-01-02")

    # Verify data in database
    from src.models.crashes import Crash
    crashes = db_session.query(Crash).filter(
        Crash.crash_date >= "2023-01-01"
    ).all()

    assert len(crashes) > 0
    assert all(c.crash_record_id for c in crashes)
```

### Running Integration Tests

```bash
# Run only integration tests
pytest -m integration

# Skip integration tests (faster for CI)
pytest -m "not integration"

# Run integration tests with verbose output
pytest -m integration -v -s
```

Configure in `pytest.ini`:

```ini
[pytest]
markers =
    integration: marks tests as integration tests (slower, hits database)
    unit: marks tests as unit tests (fast, mocked dependencies)
```

## Linting & Type Checking

```bash
ruff check src tests
mypy src/utils src/etl src/validators --ignore-missing-imports
```

CI should fail on lint violations or type errors. When type stubs are missing for third-party libraries, annotate `# type: ignore[import]` and leave a TODO to replace with proper typing later.

## Testing the Admin Portal

- Use Playwright or Cypress for end-to-end smoke tests if UI coverage is required.
- For quick manual tests, run `npm install && npm run start` inside the docs site to preview documentation changes alongside the API.

Document notable edge cases uncovered during testing so they can be promoted to automated coverage.

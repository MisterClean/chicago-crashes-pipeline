# Chicago Traffic Crash Data Pipeline - Claude AI Assistant Guide

This document provides comprehensive information about the Chicago Traffic Crash Data Pipeline project to help Claude AI produce high-quality code that follows project conventions and patterns.

# Search and Rewrite Code at Large Scale using AST Pattern

## ast-grep Usage Guide

You run in an environment where ast-grep (`sg`) is available. Use `sg run --lang <language> --pattern '<pattern>' <paths>` for syntax-aware structural matching instead of text-only tools like `rg` or `grep` when searching for code patterns.

### Key ast-grep Languages for Chicago Crashes Pipeline
- `python` - For all Python modules (API, ETL, models, validators, services, utils)
- `yaml` - For configuration files (config.yaml, docker-compose.yml)
- `sql` - For Alembic migration scripts and raw SQL queries
- `json` - For JSON configuration files and API response data
- `bash` - For shell scripts and Docker configurations

### Common Chicago Crashes Pipeline Search Patterns

**Find SQLAlchemy model definitions:**
```bash
sg run -l python -p 'class $_($Base): $$$' src/models/
sg run -l python -p 'class $_($_Mixin): $$$' src/models/
```

**Find FastAPI route definitions:**
```bash
sg run -l python -p '@router.$_("$_")' src/api/routers/
sg run -l python -p '@app.$_("$_")' src/api/
```

**Find Pydantic model fields:**
```bash
sg run -l python -p '$_: $_' src/api/models.py
sg run -l python -p 'class $_BaseModel): $$$' src/api/
```

**Find database relationship definitions:**
```bash
sg run -l python -p 'relationship("$_")' src/models/
sg run -l python -p 'ForeignKey("$_")' src/models/
```

**Find data sanitization methods:**
```bash
sg run -l python -p 'def sanitize_$_record(self, $_): $$$' src/validators/
sg run -l python -p 'def _clean_$_(self, $_): $$$' src/validators/
```

**Find async function definitions:**
```bash
sg run -l python -p 'async def $_($_): $$$' src/
```

**Find configuration settings usage:**
```bash
sg run -l python -p 'settings.$_' src/
sg run -l python -p 'from utils.config import $_' src/
```

**Find logging statements:**
```bash
sg run -l python -p 'logger.$_($_)' src/
sg run -l python -p 'get_logger($_)' src/
```

**Find test fixtures and functions:**
```bash
sg run -l python -p '@pytest.fixture' tests/
sg run -l python -p 'def test_$_($_): $$$' tests/
```

**Find database column definitions:**
```bash
sg run -l python -p 'Column($_)' src/models/
sg run -l python -p 'Index($_)' src/models/
```

**Find API dependency functions:**
```bash
sg run -l python -p 'def get_$_(): $$$' src/api/dependencies.py
sg run -l python -p 'Depends($_)' src/api/routers/
```

**Find job management patterns:**
```bash
sg run -l python -p 'JobStatus.$_' src/
sg run -l python -p 'class $_Job($_): $$$' src/models/jobs.py
```

**Find configuration in YAML files:**
```bash
sg run -l yaml -p 'endpoints: $_' config/
sg run -l yaml -p 'database: $_' config/
sg run -l yaml -p 'validation: $_' config/
```

**Find API endpoint paths:**
```bash
sg run -l python -p '"/$_"' src/api/routers/
```

**Get detailed JSON output for programmatic processing:**
```bash
sg run -l python -p 'class $_($_): $$$' src/models/ --json | jq '.[] | {file: .file, line: .range.start.line, class_name: .text}'
```

### Chicago Pipeline Specific Patterns

**Find SODA API client usage:**
```bash
sg run -l python -p 'SODAClient()' src/
sg run -l python -p 'fetch_$_records($_)' src/etl/
```

**Find data validation patterns:**
```bash
sg run -l python -p 'self.validation_settings.$_' src/validators/
sg run -l python -p 'chicago_bounds' src/
```

**Find spatial/geographic operations:**
```bash
sg run -l python -p 'geometry = $_' src/models/
sg run -l python -p 'Geometry($_)' src/models/
```

**Find job execution patterns:**
```bash
sg run -l python -p 'background_tasks.add_task($_)' src/api/
sg run -l python -p 'JobExecution($_)' src/
```

### When to Use ast-grep vs Text Search for Chicago Pipeline

**Use ast-grep (`sg`) for:**
- Finding Python class definitions, methods, and decorators
- Searching for FastAPI route patterns and dependencies
- Finding SQLAlchemy model relationships and column definitions
- Locating pytest fixtures and test patterns
- Complex nested patterns in configuration YAML
- Refactoring operations that need to understand Python syntax

**Use text search (`rg`/`grep`) for:**
- Simple string matching in comments or docstrings
- Searching for Chicago-specific terms like "crash_record_id"
- Pattern matching in log messages or error strings
- Quick searches where Python syntax doesn't matter
- Searching across multiple file types simultaneously

### Advanced ast-grep Features for Chicago Pipeline

**Context lines around matches:**
```bash
sg run -l python -p 'class Crash($_): $$$' src/models/ -C 5  # Show 5 lines before/after
```

**Search specific file patterns:**
```bash
sg run -l python -p 'router = $_' --globs 'src/api/routers/*.py'
```

**Interactive rewriting (use with extreme caution):**
```bash
sg run -l python -p 'old_pattern' -r 'new_pattern' --interactive
```

**Find all async methods in a specific service:**
```bash
sg run -l python -p 'async def $_($_): $$$' src/services/
```

This provides more accurate results than text-only searches by understanding the actual structure and syntax of Python classes, FastAPI routes, SQLAlchemy models, and configuration files specific to the Chicago Traffic Crash Data Pipeline.

## Project Overview

The Chicago Traffic Crash Data Pipeline is a comprehensive Python application that builds a robust data pipeline for Chicago's traffic crash data. It fetches, validates, and serves data from multiple Chicago Open Data SODA APIs with a focus on reliability, data quality, and operational monitoring.

### Key Features
- **Admin Portal**: Complete web-based management interface for job orchestration
- **Automated ETL Pipeline**: Initial load and incremental sync with scheduling
- **Job Scheduler**: Cron-like scheduling for automated data refreshes
- **PostGIS Database**: Spatial data storage with geographic indexing
- **Data Validation**: Comprehensive sanitization and quality checks
- **FastAPI Service**: REST API for data access and monitoring

## Technology Stack

### Core Framework
- **Python**: 3.11+
- **FastAPI**: 0.116.1 - Web API framework
- **Uvicorn**: ASGI server with standard extras

### Database
- **PostgreSQL**: Primary database with PostGIS extension
- **SQLAlchemy**: 2.0.43 - ORM with declarative models
- **Alembic**: 1.12.1 - Database migrations
- **GeoAlchemy2**: 0.18.0 - Spatial database integration
- **psycopg2-binary**: 2.9.10 - PostgreSQL adapter

### Data Processing
- **HTTPX**: 0.28.1 - Async HTTP client for API calls
- **Pydantic**: 2.11.7 - Data validation and settings management
- **structlog**: 25.4.0 - Structured logging

### Development Tools
- **pytest**: 8.4.1 - Testing framework with asyncio support
- **black**: 23.11.0 - Code formatting
- **isort**: 5.12.0 - Import sorting
- **flake8**: 6.1.0 - Linting
- **mypy**: 1.7.1 - Type checking

## Project Structure

```
chicago-crashes-pipeline/
├── src/
│   ├── api/             # FastAPI application
│   │   ├── main.py      # Application entry point
│   │   ├── models.py    # Pydantic models for API
│   │   ├── dependencies.py # Dependency injection
│   │   └── routers/     # API route modules
│   │       ├── sync.py      # Data synchronization endpoints
│   │       ├── health.py    # Health check endpoints
│   │       ├── jobs.py      # Job management endpoints
│   │       └── validation.py # Data validation endpoints
│   ├── models/          # SQLAlchemy ORM models
│   │   ├── base.py      # Base model configuration
│   │   ├── crashes.py   # Crash data models
│   │   ├── jobs.py      # Job management models
│   │   └── spatial.py   # Spatial data models
│   ├── etl/             # ETL pipeline modules
│   │   └── soda_client.py   # SODA API client
│   ├── validators/      # Data validation and sanitization
│   │   └── data_sanitizer.py # Data cleaning utilities
│   ├── services/        # Business logic services
│   │   ├── database_service.py # Database operations
│   │   ├── job_service.py      # Job management
│   │   └── job_scheduler.py    # Job scheduling
│   ├── spatial/         # Spatial data handling
│   │   └── simple_loader.py    # Shapefile loader
│   └── utils/           # Common utilities
│       ├── config.py    # Configuration management
│       └── logging.py   # Logging setup
├── migrations/          # Alembic database migrations
├── tests/              # Test suite
├── config/             # Configuration files
│   └── config.yaml     # Main configuration
├── docker/             # Docker configuration
└── docs/               # Documentation
```

## Database Schema

### Core Models (models/crashes.py)

#### Crash Model
- **Primary Key**: `crash_record_id` (String)
- **Key Fields**: `crash_date`, `latitude`, `longitude`, `geometry` (PostGIS Point)
- **Relationships**: One-to-many with `CrashPerson` and `CrashVehicle`
- **Indexes**: Spatial indexes, date/location composite indexes

#### CrashPerson Model
- **Primary Key**: Composite (`crash_record_id`, `person_id`)
- **Key Fields**: `person_type`, `age`, `injury_classification`
- **Validation**: Age range 0-120, geographic bounds for Chicago

#### CrashVehicle Model
- **Primary Key**: `crash_unit_id` (unique identifier)
- **Foreign Key**: `crash_record_id`
- **Key Fields**: `vehicle_year`, `make`, `model`, `vehicle_type`
- **Validation**: Vehicle year range 1900-2025

#### VisionZeroFatality Model
- **Primary Key**: `person_id`
- **Key Fields**: `crash_date`, `victim`, `crash_location`
- **Spatial**: PostGIS geometry for location data

### Job Management Models (models/jobs.py)

#### ScheduledJob Model
- **Purpose**: Configure recurring data synchronization jobs
- **Key Fields**: `name`, `job_type`, `enabled`, `config`, `next_run`
- **Recurrence**: Daily, weekly, monthly, or custom cron expressions
- **Default Jobs**: Pre-configured jobs for common sync patterns

#### JobExecution Model
- **Purpose**: Track individual job execution instances
- **Key Fields**: `execution_id`, `status`, `started_at`, `completed_at`
- **Metrics**: Records processed, inserted, updated, skipped
- **Error Handling**: Detailed error messages and retry tracking

### Base Configuration (models/base.py)
- **Engine**: SQLAlchemy with connection pooling
- **Sessions**: Auto-commit disabled, auto-flush disabled
- **Naming Convention**: Standardized constraint naming
- **TimestampMixin**: Automatic `created_at`/`updated_at` timestamps

## Configuration System

### Hierarchical Configuration (utils/config.py)
- **config.yaml**: Main configuration file
- **.env**: Environment variables (database credentials, API tokens)
- **Pydantic Settings**: Type-safe configuration with validation

### Key Configuration Sections

#### API Settings
```yaml
api:
  endpoints:
    crashes: "https://data.cityofchicago.org/resource/85ca-t3if.json"
    people: "https://data.cityofchicago.org/resource/u6pd-qa9d.json"
    vehicles: "https://data.cityofchicago.org/resource/68nd-jvt3.json"
    fatalities: "https://data.cityofchicago.org/resource/gzaz-isa6.json"
  rate_limit: 1000
  batch_size: 50000
```

#### Database Settings
```yaml
database:
  host: ${DB_HOST:localhost}
  port: ${DB_PORT:5432}
  database: ${DB_NAME:chicago_crashes}
  pool_size: 10
  use_copy: true
```

#### Validation Settings
```yaml
validation:
  bounds:
    min_latitude: 41.6    # Chicago geographic bounds
    max_latitude: 42.1
    min_longitude: -87.95
    max_longitude: -87.5
  age_range:
    min: 0
    max: 120
  vehicle_year_range:
    min: 1900
    max: 2025
```

## Data Processing Patterns

### Data Sanitization (validators/data_sanitizer.py)
- **Coordinate Validation**: Ensures lat/lon within Chicago bounds
- **Date Parsing**: Handles multiple datetime formats from SODA API
- **Type Conversion**: Robust string-to-int/float conversion
- **Text Cleaning**: Unicode handling, null value normalization
- **Duplicate Removal**: Key-based deduplication within batches

### Common Sanitization Methods
```python
def _clean_string(self, value: Any, max_length: Optional[int] = None) -> Optional[str]
def _clean_integer(self, value: Any) -> Optional[int]
def _clean_coordinate(self, value: Any, coord_type: str) -> Optional[float]
def _parse_datetime(self, value: Any) -> Optional[datetime]
def _clean_age(self, value: Any) -> Optional[int]
def _clean_vehicle_year(self, value: Any) -> Optional[int]
```

## API Patterns

### FastAPI Application Structure (api/main.py)
- **Lifespan Manager**: Handles startup/shutdown tasks
- **Dependency Injection**: Database sessions, client instances
- **CORS**: Configured for web admin portal
- **Static Files**: Serves admin portal HTML/CSS/JS
- **Router Organization**: Modular endpoint organization

### Common API Patterns
- **Background Tasks**: Long-running sync operations
- **Dependency Providers**: `get_soda_client()`, `get_data_sanitizer()`, `get_db()`
- **Error Handling**: Structured HTTP exceptions with detail messages
- **Response Models**: Pydantic models for consistent API responses

### Sync Router (api/routers/sync.py)
- **GET /sync/status**: Current sync status and statistics
- **POST /sync/trigger**: Manual sync with date range filtering
- **POST /sync/test**: Test sync with small dataset
- **GET /sync/endpoints**: Available data endpoints info
- **GET /sync/counts**: Database record counts

## Testing Patterns

### Test Structure (tests/)
- **conftest.py**: Shared fixtures and configuration
- **pytest**: Async test support with event loop management
- **Mocking**: HTTP client mocking for external API calls

### Common Test Fixtures
```python
@pytest.fixture
def sample_crash_record()   # Valid crash record for testing
@pytest.fixture  
def sample_person_record()  # Valid person record for testing
@pytest.fixture
def invalid_crash_record()  # Invalid data for validation testing
@pytest.fixture
def chicago_bounds()        # Geographic bounds for validation
```

### Test Categories
- **Configuration Tests**: Settings loading and validation
- **Data Sanitization Tests**: Input cleaning and transformation
- **Data Validation Tests**: Geographic and range validation
- **SODA Client Tests**: API pagination and error handling
- **API Endpoint Tests**: FastAPI route testing with mocks

## Common Development Patterns

### Import Path Management
All modules use absolute imports from src root:
```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from utils.config import settings
```

### Logging Pattern
Structured logging with contextual information:
```python
from utils.logging import get_logger
logger = get_logger(__name__)

logger.info("Operation completed", 
           records=len(records), 
           duration=duration)
```

### Async/Await Patterns
- **SODA Client**: Async HTTP requests with HTTPX
- **Database Operations**: Sync SQLAlchemy (async patterns available)
- **Background Tasks**: FastAPI BackgroundTasks for long operations

### Error Handling
- **Circuit Breaker Pattern**: Prevents API overload
- **Exponential Backoff**: Handles rate limiting gracefully
- **Structured Errors**: Detailed error context in logs and responses

### Database Operations
- **Bulk Operations**: Use COPY for large inserts
- **Connection Pooling**: Configured pool size and overflow
- **Transaction Management**: Explicit session management

## Job Management System

### Job Types
- **FULL_REFRESH**: Complete data refresh (disabled by default)
- **LAST_30_DAYS_CRASHES**: Daily refresh of recent crash data
- **LAST_30_DAYS_PEOPLE**: Daily refresh of recent people data
- **LAST_6_MONTHS_FATALITIES**: Weekly fatality data refresh
- **CUSTOM**: User-defined job configurations

### Job Scheduling
- **Recurrence Types**: ONCE, DAILY, WEEKLY, MONTHLY, CUSTOM_CRON
- **Next Run Calculation**: Automatic scheduling based on recurrence
- **Job Execution Tracking**: Complete audit trail of job runs

## Code Style Guidelines

### Python Style
- **Black**: Code formatting (line length: 88 characters)
- **isort**: Import organization with profile compatibility
- **flake8**: Linting with configuration for Black compatibility
- **mypy**: Type checking for critical modules

### Database Conventions
- **Naming**: Snake_case for table and column names
- **Indexes**: Descriptive names with purpose prefix (ix_, fk_, etc.)
- **Foreign Keys**: Explicit relationship definitions
- **Constraints**: Named constraints for better error messages

### API Conventions
- **Route Organization**: Group related endpoints in routers
- **Response Models**: Pydantic models for consistent responses
- **Error Handling**: HTTP exceptions with structured detail
- **Documentation**: Comprehensive docstrings and OpenAPI integration

## Admin Portal Integration

The application includes a web-based admin portal served at `/admin`:
- **Static Files**: HTML/CSS/JS served via FastAPI StaticFiles
- **Job Management**: Create, edit, and monitor scheduled jobs
- **Data Management**: View database statistics and manage data
- **Real-time Monitoring**: Job execution progress and system health

## Performance Considerations

### Database Performance
- **Spatial Indexes**: PostGIS GIST indexes for geographic queries
- **Composite Indexes**: Multi-column indexes for common query patterns
- **Connection Pooling**: Tuned pool size and overflow settings
- **Bulk Operations**: COPY for large data imports

### API Performance
- **Batch Processing**: 50K records per SODA API call
- **Rate Limiting**: Respects Chicago Open Data API limits
- **Async Operations**: Non-blocking HTTP requests
- **Pagination**: Efficient handling of large datasets

## Environment Setup

### Development Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Database Setup
```bash
cd docker && docker-compose up -d postgres
# Database tables are created automatically on startup
```

### Running the Application
```bash
cd src && uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests
```bash
python -m pytest tests/ -v
```

## Key Commands for Development

### Linting and Formatting
```bash
black src/ tests/           # Format code
isort src/ tests/           # Sort imports  
flake8 src/ tests/          # Lint code
mypy src/                   # Type checking
```

### Database Operations
```bash
alembic upgrade head        # Run migrations
alembic revision --autogenerate -m "description"  # Create migration
```

### Testing
```bash
pytest tests/ -v           # Run all tests
pytest tests/test_data_sanitization.py -v  # Run specific test file
pytest -k "test_sanitize" -v  # Run tests matching pattern
```

When working on this project, always:

1. **Follow the established patterns** for imports, logging, and error handling
2. **Use the existing configuration system** rather than hardcoding values
3. **Implement comprehensive data validation** following the sanitizer patterns
4. **Write tests** with appropriate fixtures and async support
5. **Use structured logging** with contextual information
6. **Handle database operations** with proper session management
7. **Follow the job management patterns** for long-running operations
8. **Maintain API consistency** with existing response models and error handling

The codebase emphasizes data quality, operational reliability, and maintainable patterns. All new code should follow these established conventions to maintain consistency and quality.
# Chicago Traffic Crash Data Pipeline

A comprehensive Python application that builds a robust data pipeline for Chicago's traffic crash data, fetching, validating, and serving data from multiple Chicago Open Data SODA APIs.

## Overview

This pipeline handles four interconnected datasets from the Chicago Open Data Portal:

1. **Traffic Crashes - Crashes** (Main table) - ~1M+ records
2. **Traffic Crashes - People** - Person-level injury data
3. **Traffic Crashes - Vehicles** - Vehicle/unit information
4. **Traffic Crashes - Vision Zero Fatalities** - Curated fatality dataset

## Architecture

The pipeline follows a modern, microservices-inspired architecture with clear separation of concerns:

```mermaid
graph TB
    subgraph "External Data Sources"
        CDA[Chicago Data Portal<br/>SODA API Endpoints]
        SHP[Shapefiles<br/>Geographic Boundaries]
    end
    
    subgraph "Web Interface"
        ADMIN[Admin Portal<br/>HTML/CSS/JS]
        API_DOCS[API Documentation<br/>Swagger/OpenAPI]
    end
    
    subgraph "API Layer"
        FASTAPI[FastAPI Application<br/>Python 3.11+]
        ROUTERS{API Routers}
        FASTAPI --> ROUTERS
        ROUTERS --> SYNC_R[/sync - Data Sync]
        ROUTERS --> JOBS_R[/jobs - Job Management] 
        ROUTERS --> HEALTH_R[/health - Health Checks]
        ROUTERS --> SPATIAL_R[/spatial - Geographic Data]
    end
    
    subgraph "Business Logic Layer"
        ETL[ETL Service<br/>SODA Client]
        VALIDATOR[Data Validator<br/>Sanitization & Cleaning]
        JOB_SVC[Job Service<br/>Execution & Management]
        SCHEDULER[Job Scheduler<br/>Cron-like Scheduling]
        DB_SVC[Database Service<br/>CRUD Operations]
        SPATIAL_SVC[Spatial Service<br/>Shapefile Processing]
    end
    
    subgraph "Data Processing"
        SANITIZER[Data Sanitizer<br/>• Coordinate Validation<br/>• Date Parsing<br/>• Type Conversion<br/>• Duplicate Removal]
        RATE_LIMITER[Rate Limiter<br/>API Throttling]
    end
    
    subgraph "Data Storage"
        PG[(PostgreSQL 15<br/>with PostGIS)]
        PG_TABLES{Database Tables}
        PG --> PG_TABLES
        PG_TABLES --> CRASHES[(crashes<br/>~1M+ records)]
        PG_TABLES --> PEOPLE[(crash_people<br/>Person data)]
        PG_TABLES --> VEHICLES[(crash_vehicles<br/>Vehicle data)]
        PG_TABLES --> FATALITIES[(vision_zero_fatalities<br/>Fatality data)]
        PG_TABLES --> JOBS[(scheduled_jobs<br/>Job configs)]
        PG_TABLES --> EXECUTIONS[(job_executions<br/>Execution history)]
        PG_TABLES --> SPATIAL_TABLES[(Spatial Tables<br/>wards, districts, etc.)]
    end
    
    subgraph "Infrastructure"
        DOCKER[Docker Container<br/>PostgreSQL + PostGIS]
        VENV[Python Virtual Environment<br/>Dependencies]
    end

    %% Data Flow Connections
    ADMIN --> FASTAPI
    API_DOCS --> FASTAPI
    
    SYNC_R --> ETL
    JOBS_R --> JOB_SVC
    SPATIAL_R --> SPATIAL_SVC
    
    ETL --> CDA
    ETL --> RATE_LIMITER
    ETL --> VALIDATOR
    VALIDATOR --> SANITIZER
    
    JOB_SVC --> SCHEDULER
    JOB_SVC --> DB_SVC
    SCHEDULER --> ETL
    
    SPATIAL_SVC --> SHP
    SPATIAL_SVC --> DB_SVC
    
    DB_SVC --> PG
    
    PG -.-> DOCKER
    FASTAPI -.-> VENV

    %% Styling
    classDef external fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
    classDef web fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef api fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef service fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef data fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    classDef storage fill:#e0f2f1,stroke:#00695c,stroke-width:2px
    classDef infra fill:#f1f8e9,stroke:#33691e,stroke-width:2px
    
    class CDA,SHP external
    class ADMIN,API_DOCS web
    class FASTAPI,ROUTERS,SYNC_R,JOBS_R,HEALTH_R,SPATIAL_R api
    class ETL,VALIDATOR,JOB_SVC,SCHEDULER,DB_SVC,SPATIAL_SVC service
    class SANITIZER,RATE_LIMITER data
    class PG,PG_TABLES,CRASHES,PEOPLE,VEHICLES,FATALITIES,JOBS,EXECUTIONS,SPATIAL_TABLES storage
    class DOCKER,VENV infra
```

**Key Components:**

- **Admin Portal**: Web-based interface for job management and system monitoring
- **FastAPI**: RESTful API with automatic OpenAPI documentation
- **ETL Pipeline**: Async data fetching with rate limiting and validation
- **Job System**: Cron-like scheduling with execution tracking and retry logic
- **PostGIS Database**: Spatial-enabled PostgreSQL for geographic analysis
- **Data Validation**: Multi-stage sanitization ensuring data quality
- **Docker Integration**: Containerized PostgreSQL with PostGIS extension

## Features

- 🎛️ **Admin Portal** - Complete web-based management interface for job orchestration
- 🔄 **Automated ETL Pipeline** - Initial load and incremental sync capabilities with scheduling
- 📅 **Job Scheduler** - Cron-like scheduling for automated data refreshes
- 🗄️ **PostGIS Database** - Spatial data storage with geographic indexing
- 🚦 **Rate Limiting** - Respects Chicago Open Data API limits
- ✅ **Data Validation** - Comprehensive sanitization and quality checks
- 📊 **Spatial Support** - Handles shapefiles for districts and boundaries
- 🐳 **Docker Ready** - Complete containerized deployment
- 📈 **Progress Tracking** - Visual progress bars and execution monitoring
- 🔧 **FastAPI Service** - REST API for data access and monitoring
- 🗑️ **Data Management** - Safe data deletion with confirmation prompts

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose

### Fast Setup (3 minutes)

1. **Clone and setup:**
```bash
git clone https://github.com/MisterClean/chicago-crashes-pipeline.git
cd chicago-crashes-pipeline

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

2. **Start database:**
```bash
cd docker && docker-compose up -d postgres
cd .. # Return to project root
```

3. **Configure environment:**
```bash
# Create .env file with database settings
echo "DB_HOST=localhost
DB_PORT=5432
DB_NAME=chicago_crashes
DB_USER=postgres
DB_PASSWORD=postgres" > .env
```

4. **Start the application:**
```bash
source venv/bin/activate
cd src && uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**That's it!** The application will automatically:
- Create all database tables on startup
- Initialize default scheduled jobs for data refreshes
- Be ready to fetch data from Chicago's Open Data Portal
- Serve the API at http://localhost:8000
- Launch the Admin Portal at http://localhost:8000/admin

### Load Chicago Crash Data

#### Option 1: Use the Admin Portal (Recommended)

1. **Open the Admin Portal**: http://localhost:8000/admin
2. **Dashboard**: View job statistics and system status
3. **Quick Actions**: Execute pre-configured jobs instantly:
   - **Full Data Refresh**: Loads all available crash data (disabled by default)
   - **Last 30 Days - Crashes**: Daily refresh of recent crash data
   - **Last 30 Days - People**: Daily refresh of recent people data
   - **Last 6 Months - Fatalities**: Weekly refresh of Vision Zero fatality data
4. **Scheduled Jobs**: Create custom jobs with specific date ranges and schedules
5. **Data Management**: View database statistics and safely delete data

#### Option 2: Use the API directly

```bash
# Load recent crashes (fast - for testing)
curl -X POST http://localhost:8000/sync/trigger \
  -H "Content-Type: application/json" \
  -d '{"endpoint": "crashes", "start_date": "2024-08-01", "end_date": "2024-08-28"}'

# Load full 2024 data (takes a few minutes)
curl -X POST http://localhost:8000/sync/trigger \
  -H "Content-Type: application/json" \
  -d '{"endpoint": "crashes", "start_date": "2024-01-01"}'

# Monitor sync progress
curl http://localhost:8000/sync/status

# Test data fetching
curl -X POST http://localhost:8000/sync/test
```

### What You Get

- **Admin Portal**: http://localhost:8000/admin - Complete web-based management interface
- **Interactive API Documentation**: http://localhost:8000/docs - Full API reference
- **Real Chicago Crash Data**: From the official Chicago Open Data Portal
- **Automated Job Scheduling**: Set up recurring data refreshes
- **Spatial Analysis Ready**: PostGIS database with geographic indexing
- **Multiple Data Tables**: crashes, people, vehicles, fatalities
- **RESTful API**: Query and analyze data via HTTP endpoints
- **Real-time Monitoring**: Track job progress and system health

## Testing the Pipeline

You can test the core pipeline components without setting up a database:

```bash
# Activate virtual environment
source venv/bin/activate

# Test configuration and data processing
python3 -c "
import sys
sys.path.append('src')
import asyncio

async def test():
    from etl.soda_client import SODAClient
    from validators.data_sanitizer import DataSanitizer
    from utils.config import settings
    
    client = SODAClient()
    sanitizer = DataSanitizer()
    
    # Fetch a few test records
    records = await client.fetch_records(
        endpoint=settings.api.endpoints['crashes'], 
        limit=3
    )
    
    print(f'✓ Fetched {len(records)} crash records')
    
    # Test data sanitization
    for record in records[:1]:
        clean = sanitizer.sanitize_crash_record(record)
        print(f'✓ Processed crash {clean.get(\"crash_record_id\", \"N/A\")[:10]}...')

asyncio.run(test())
"
```

## Admin Portal

The Chicago Crashes Pipeline includes a comprehensive web-based admin portal for managing data synchronization jobs and monitoring the system.

### Features

#### 🎛️ Dashboard
- **System Overview**: Real-time statistics on total jobs, active jobs, running jobs, and failed jobs in the last 24 hours
- **Quick Actions**: One-click execution of common data refresh operations
- **Recent Activity**: Live feed of recent job executions with status indicators

#### 📅 Scheduled Jobs Management
- **Pre-configured Jobs**: Four default jobs ready for deployment:
  - Full Data Refresh (all endpoints, disabled by default)
  - Last 30 Days - Crash Data (daily refresh)
  - Last 30 Days - People Data (daily refresh) 
  - Last 6 Months - Vision Zero Fatalities (weekly refresh)
- **Custom Jobs**: Create, edit, and delete custom synchronization jobs
- **Job Configuration**: Set endpoints, date ranges, schedules, timeouts, and retry policies
- **Enable/Disable**: Toggle jobs on/off without deletion

#### 📊 Execution Monitoring
- **Real-time Tracking**: Monitor job progress and status
- **Execution History**: Complete log of all job runs with detailed metrics
- **Performance Metrics**: Records processed, inserted, updated, and execution duration
- **Error Handling**: Detailed error messages and retry tracking

#### 🗑️ Data Management
- **Database Statistics**: View record counts for all tables
- **Safe Deletion**: Delete data from specific tables with confirmation prompts
- **Date Range Filtering**: Delete data within specific date ranges
- **Backup Options**: Track backup locations for recovery

### Accessing the Admin Portal

1. **Start the application**: `uvicorn api.main:app --reload --host 0.0.0.0 --port 8000`
2. **Open in browser**: http://localhost:8000/admin
3. **Navigate tabs**:
   - **Dashboard**: System overview and quick actions
   - **Scheduled Jobs**: Job management interface
   - **Execution History**: Monitor job runs
   - **Data Management**: Database administration

### Default Job Schedule

The portal initializes with four pre-configured jobs:

| Job | Schedule | Enabled | Description |
|-----|----------|---------|-------------|
| Full Data Refresh | Manual | ❌ Disabled | Fetches all available data from all endpoints |
| Last 30 Days - Crashes | Daily | ✅ Enabled | Daily refresh of recent crash data |
| Last 30 Days - People | Daily | ✅ Enabled | Daily refresh of recent people data |
| Last 6 Months - Fatalities | Weekly | ✅ Enabled | Weekly refresh of Vision Zero fatality data |

> **Note**: The Full Data Refresh job is disabled by default as requested, since it fetches large amounts of data.

## Configuration

The pipeline uses a hierarchical configuration system:

- `config/config.yaml` - Main configuration
- `.env` - Environment variables (database, API tokens)
- Command-line arguments override config values

### Key Configuration Sections

```yaml
api:
  endpoints:
    crashes: "https://data.cityofchicago.org/resource/85ca-t3if.json"
    # ... other endpoints
  rate_limit: 1000  # requests/hour
  batch_size: 50000

database:
  host: localhost
  database: chicago_crashes
  # Uses environment variables for credentials

validation:
  bounds:
    min_latitude: 41.6
    max_latitude: 42.1
    # Chicago area bounds for coordinate validation
```

## Usage

### Initial Data Load

Load all data from a specific start date:
```bash
python -m src.etl.initial_load --start-date "2019-01-01"
```

### Incremental Sync

Fetch only new/updated records:
```bash
python -m src.etl.sync --force
```

### Load Spatial Data

Import shapefiles for geographic boundaries:
```bash
python -m src.spatial.loader --file data/shapefiles/chicago_wards.shp
```

### Run Tests

Run the comprehensive test suite:
```bash
source venv/bin/activate
python -m pytest tests/ -v
```

The test suite includes 53+ tests covering:
- Configuration management and validation
- Data sanitization and cleaning operations  
- Data validation with Chicago geographic bounds
- SODA API client functionality (pagination, error handling, rate limiting)
- FastAPI endpoint testing with dependency mocking
- Async operations and concurrent request handling

### Start API Server

Launch the FastAPI service:
```bash
make serve
# or
uvicorn src.api.main:app --reload
```

## Database Schema

The pipeline creates a normalized PostgreSQL schema with PostGIS support:

### Core Tables

- **crashes** - Main crash records with spatial geometry
- **crash_people** - Person-level data (linked by crash_record_id)  
- **crash_vehicles** - Vehicle/unit data (linked by crash_record_id)
- **vision_zero_fatalities** - Curated fatality records

### Spatial Tables

- **wards** - Chicago ward boundaries
- **community_areas** - Community area boundaries
- **census_tracts** - Census tract boundaries
- **police_beats** - Police beat boundaries
- **house_districts** - Illinois House district boundaries
- **senate_districts** - Illinois Senate district boundaries

### Key Indexes

The schema includes optimized indexes for:
- Spatial queries (PostGIS GIST indexes)
- Date range queries
- Crash severity filtering
- Geographic boundary lookups

## Data Processing

### Validation & Sanitization

The pipeline includes comprehensive data cleaning:

- **Geographic Bounds** - Validates coordinates within Chicago area
- **Date Parsing** - Handles multiple datetime formats
- **Age Validation** - Ensures reasonable age ranges (0-120)
- **Vehicle Years** - Validates years (1900-current+1)
- **Duplicate Removal** - Removes duplicates within batches
- **Text Cleaning** - Handles Unicode, null values, whitespace

### Error Handling

- **Circuit Breaker** - Prevents API overload
- **Exponential Backoff** - Handles rate limiting gracefully  
- **Partial Recovery** - Continues processing on non-fatal errors
- **Structured Logging** - Comprehensive error tracking

## API Endpoints

The FastAPI service provides:

- `GET /sync/status` - Current sync status and last run time
- `POST /sync/trigger` - Manual sync trigger with optional date range  
- `GET /health` - Service health check

## Development

### Common Commands

```bash
make install         # Install dependencies
make test           # Run test suite
make lint           # Run linting
make format         # Format code
make docker-build   # Build containers
make migrate        # Run database migrations
```

### Project Structure

```
chicago-crash-pipeline/
├── src/
│   ├── api/          # FastAPI service
│   ├── etl/          # ETL pipeline modules  
│   ├── models/       # SQLAlchemy models
│   ├── validators/   # Data validation rules
│   ├── spatial/      # Spatial data handlers
│   └── utils/        # Common utilities
├── migrations/       # Alembic migrations
├── tests/           
├── config/          
├── docker/          
└── docs/            
```

## Documentation

- **[API Reference](docs/API_REFERENCE.md)** - Complete API documentation with examples
- **[Development Guide](docs/DEVELOPMENT_GUIDE.md)** - Setup, coding standards, and contribution guidelines  
- **[Deployment Guide](docs/DEPLOYMENT_GUIDE.md)** - Production deployment on Docker, Kubernetes, and cloud platforms
- **[Troubleshooting Guide](docs/TROUBLESHOOTING.md)** - Common issues and debugging procedures

## Data Sources

All data comes from the [Chicago Data Portal](https://data.cityofchicago.org):

- [Traffic Crashes - Crashes](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Crashes/85ca-t3if)
- [Traffic Crashes - People](https://data.cityofchicago.org/Transportation/Traffic-Crashes-People/u6pd-qa9d)  
- [Traffic Crashes - Vehicles](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Vehicles/68nd-jvt3)
- [Vision Zero Fatalities](https://data.cityofchicago.org/Transportation/Traffic-Crashes-Vision-Zero-Chicago-Traffic-Fatali/gzaz-isa6)

## Performance

The pipeline is optimized for large-scale data processing:

- **Batch Processing** - 50,000 records per API call
- **Connection Pooling** - Efficient database connections
- **Bulk Inserts** - Uses PostgreSQL COPY for initial loads  
- **Async Operations** - Non-blocking API calls
- **Progress Tracking** - Real-time progress indicators

## Troubleshooting

### Common Issues

**Import Errors with Relative Imports**
- The pipeline modules use absolute imports when run as scripts
- Always run Python commands from the project root directory
- Ensure `sys.path.append('src')` when testing individual modules

**Database Connection Issues**
- Check your `.env` file contains correct database credentials
- Ensure PostgreSQL is running and accessible
- Verify PostGIS extension is installed: `CREATE EXTENSION IF NOT EXISTS postgis;`

**API Rate Limits**
- The Chicago Open Data Portal has rate limits
- Default configuration respects these limits (1000 requests/hour)
- Consider getting an API token from the Chicago Data Portal for higher limits

**Memory Issues with Large Datasets**
- Initial loads process millions of records
- Use the batch_size setting in config.yaml to tune memory usage
- Docker containers may need increased memory limits for large imports

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run linting and formatting
5. Submit a pull request

## License

MIT License - see LICENSE file for details.
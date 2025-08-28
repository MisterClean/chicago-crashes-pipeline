# Chicago Traffic Crash Data Pipeline

A comprehensive Python application that builds a robust data pipeline for Chicago's traffic crash data, fetching, validating, and serving data from multiple Chicago Open Data SODA APIs.

## Overview

This pipeline handles four interconnected datasets from the Chicago Open Data Portal:

1. **Traffic Crashes - Crashes** (Main table) - ~1M+ records
2. **Traffic Crashes - People** - Person-level injury data
3. **Traffic Crashes - Vehicles** - Vehicle/unit information
4. **Traffic Crashes - Vision Zero Fatalities** - Curated fatality dataset

## Features

- 🔄 **Automated ETL Pipeline** - Initial load and incremental sync capabilities
- 🗄️ **PostGIS Database** - Spatial data storage with geographic indexing
- 🚦 **Rate Limiting** - Respects Chicago Open Data API limits
- ✅ **Data Validation** - Comprehensive sanitization and quality checks
- 📊 **Spatial Support** - Handles shapefiles for districts and boundaries
- 🐳 **Docker Ready** - Complete containerized deployment
- 📈 **Progress Tracking** - Visual progress bars for long-running operations
- 🔧 **FastAPI Service** - REST API for data access and monitoring

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ with PostGIS
- Docker & Docker Compose (optional)

### Installation

1. **Clone and setup:**
```bash
git clone https://github.com/MisterClean/lakeview-crashes.git
cd lakeview-crashes
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your database credentials and API token
```

3. **Start with Docker (recommended):**
```bash
make docker-up
```

Or manually setup PostgreSQL and run:
```bash
make migrate
make initial-load START_DATE=2020-01-01
```

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

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run linting and formatting
5. Submit a pull request

## License

MIT License - see LICENSE file for details.
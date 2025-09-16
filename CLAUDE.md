# Chicago Traffic Crash Data Pipeline - Claude AI Assistant Guide

This document provides essential information for Claude AI to work effectively with the Chicago Traffic Crash Data Pipeline project.

## Quick Start Checklist

Before any work, ensure the environment is ready:

```bash
# 1. Get to project root
cd /Users/mmclean/dev/python/chicago-crashes-pipeline

# 2. Check/start PostgreSQL 
docker ps | grep postgres || (cd docker && docker-compose up -d postgres && sleep 15)

# 3. Activate virtual environment
source venv/bin/activate

# 4. Verify setup
python3 -c "import sys; sys.path.append('src'); from utils.config import settings; print('✓ Ready')"
```

## Common Issues & Quick Fixes

### PostgreSQL Connection Refused
- **Fix**: `cd docker && docker-compose up -d postgres && sleep 15`

### Module Import Errors  
- **Fix**: `cd /Users/mmclean/dev/python/chicago-crashes-pipeline && source venv/bin/activate`
- **For scripts**: Always add `sys.path.append('src')` before project imports

### F-String Syntax Errors in Bash
- **Fix**: Use `.format()` or simple concatenation instead of complex f-strings in bash commands

## Project Structure

```
src/
├── api/                 # FastAPI application & routers
├── models/              # SQLAlchemy ORM models (crashes.py, jobs.py)
├── etl/                 # Data pipeline (soda_client.py)
├── validators/          # Data sanitization (data_sanitizer.py)
├── services/            # Business logic (job_service.py, database_service.py)
└── utils/               # Config & logging
```

## Key Technologies

- **Python 3.11+** with FastAPI, SQLAlchemy 2.0, PostgreSQL+PostGIS
- **Database**: 4 main tables (crashes, crash_people, crash_vehicles, vision_zero_fatalities)
- **API**: REST endpoints at http://localhost:8000, admin portal at /admin
- **Data Sources**: Chicago Open Data Portal SODA APIs

## Essential Patterns

### Database Queries
```python
import sys
sys.path.append('src')
from sqlalchemy import create_engine, text
from utils.config import settings

engine = create_engine(settings.database.url)
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM crashes"))
```

### Data Sanitization
```python
from validators.data_sanitizer import DataSanitizer
sanitizer = DataSanitizer()
clean_data = sanitizer.sanitize_crash_record(raw_record)
```

### Configuration Access
```python
from utils.config import settings
print(settings.database.url)
print(settings.api.endpoints['crashes'])
```

## ast-grep for Code Search

Use `sg` for syntax-aware searches instead of grep:

```bash
# Find models
sg run -l python -p 'class $_($Base): $$$' src/models/

# Find API routes  
sg run -l python -p '@router.$_("$_")' src/api/routers/

# Find async functions
sg run -l python -p 'async def $_($_): $$$' src/

# Find config usage
sg run -l python -p 'settings.$_' src/
```

## Data Analysis Setup

For database analysis tasks:
```bash
cd /Users/mmclean/dev/python/chicago-crashes-pipeline
source venv/bin/activate
docker ps | grep postgres || (cd docker && docker-compose up -d postgres && sleep 15)

python3 -c "
import sys
sys.path.append('src')
from sqlalchemy import create_engine, text
from utils.config import settings
engine = create_engine(settings.database.url)
# Ready for queries
"
```

## API Development

Start the API server:
```bash
cd src && uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Verify it's working:
```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/sync/counts
```

### Spatial Layer Management

- **Purpose**: Upload administrative boundaries (e.g., Senate Districts) and make them queryable in PostGIS for spatial joins with crash data.
- **Upload via API**:
  ```bash
  # GeoJSON FeatureCollection
  curl -F "name=Zip Districts" \
       -F "file=@data/districts.geojson" \
       http://localhost:8000/spatial/layers

  # Zipped ESRI Shapefile (.shp/.shx/.dbf/.prj required)
  curl -F "name=Zip Districts" \
       -F "file=@data/districts.zip" \
       http://localhost:8000/spatial/layers
  ```
- **Validation**: The service rejects archives missing required shapefile components, disallows path traversal, and converts shapefiles to GeoJSON through `ogr2ogr` before inserting features.
- **Admin Portal**: `/admin` now has a **Spatial Layers** tab to upload, review sample attributes, replace data, or delete layers without leaving the UI.
- **Storage**: Layer metadata lives in `spatial_layers`; individual geometries are stored in `spatial_layer_features` with a GiST index for spatial queries.

## Key Database Tables

- **crashes**: Main crash records (`crash_record_id`, `crash_date`, `latitude`, `longitude`)
- **crash_people**: Person-level data (`person_type`, `age`, `injury_classification`) 
- **crash_vehicles**: Vehicle data (`vehicle_year`, `make`, `model`)
- **vision_zero_fatalities**: Curated fatality records

## Nuclear Reset (If Everything Breaks)

```bash
cd /Users/mmclean/dev/python/chicago-crashes-pipeline
pkill -f uvicorn || true
cd docker && docker-compose down && docker-compose up -d postgres && sleep 15
cd .. && source venv/bin/activate
python3 -c "import sys; sys.path.append('src'); from utils.config import settings; print('✓ Reset complete')"
```

## Development Guidelines

1. **Always work from project root**: `/Users/mmclean/dev/python/chicago-crashes-pipeline`
2. **Use virtual environment**: `source venv/bin/activate` 
3. **Add src to path**: `sys.path.append('src')` in Python scripts
4. **Follow existing patterns**: Check similar code before writing new features
5. **Use structured logging**: `from utils.logging import get_logger`
6. **Handle database connections properly**: Use SQLAlchemy sessions correctly

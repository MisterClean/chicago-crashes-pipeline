# Project Dependencies

This document explains the dependency structure for the Chicago Crashes Pipeline project.

## Core Dependencies (requirements.txt)

The main `requirements.txt` file contains only essential packages needed to run the application:

### Framework & API
- **fastapi**: Web framework for building APIs
- **uvicorn**: ASGI server for running FastAPI applications
- **requests**: HTTP library for external API calls
- **httpx**: Async HTTP client for SODA API integration

### Database
- **sqlalchemy**: ORM for database operations
- **psycopg2-binary**: PostgreSQL adapter
- **geoalchemy2**: Spatial extensions for SQLAlchemy
- **alembic**: Database migrations

### Configuration & Utilities
- **pydantic**: Data validation and settings
- **pydantic-settings**: Settings management
- **python-dotenv**: Environment variable loading
- **pyyaml**: YAML configuration support
- **structlog**: Structured logging
- **tqdm**: Progress bars

### Testing
- **pytest**: Testing framework
- **pytest-asyncio**: Async testing support

### Development Tools
- **ruff**: Fast linter and code formatter (replaces black, isort, flake8)
- **mypy**: Type checking

## Optional Dependencies (requirements-dev.txt)

Additional packages for enhanced functionality:

### Advanced Testing
- **pytest-httpx**: HTTP testing utilities

### CLI & Output Enhancement
- **typer**: CLI framework (used for command-line tools)
- **rich**: Enhanced console output and formatting

### Spatial Analysis
- **pandas**: Data analysis and manipulation
- **geopandas**: Geospatial data analysis
- **shapely**: Geometric operations
- **pyproj**: Coordinate system transformations
- **fiona**: Shapefile reading/writing
- **rasterio**: Raster data processing

## Installation Instructions

### Core Installation
```bash
# Install core dependencies only
pip install -r requirements.txt
```

### Development Installation
```bash
# Install core dependencies
pip install -r requirements.txt

# Install optional development dependencies
pip install -r requirements-dev.txt
```

### Spatial Dependencies System Requirements

For spatial analysis features, you may need additional system packages:

#### macOS
```bash
brew install gdal
```

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev
```

#### Windows
- Install OSGeo4W from https://trac.osgeo.org/osgeo4w/
- Or use conda: `conda install gdal`

## Dependency Management Strategy

1. **Core requirements.txt**: Contains only packages essential for basic operation
2. **Optional requirements-dev.txt**: Contains packages for enhanced development experience
3. **System dependencies**: Documented separately as they vary by platform

This approach ensures:
- Fast installation for production deployments
- Flexibility for development environments
- Clear separation between essential and optional features
- Reduced dependency conflicts

## Troubleshooting

### Common Issues

1. **Pandas installation fails**: Usually due to missing numpy or build tools
   - Solution: Install numpy first or use conda
   
2. **Spatial packages fail to install**: Usually missing GDAL system dependencies
   - Solution: Install GDAL system packages first
   
3. **pytest-httpx not found**: Version incompatibility
   - Solution: Use core testing without advanced HTTP testing

### Virtual Environment Recommendation

Always use a virtual environment to avoid dependency conflicts:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```
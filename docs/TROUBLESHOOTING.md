# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the Chicago Crash Data Pipeline.

> **Note:** The examples below assume you are running commands from the project root
> and pointing Docker Compose at `docker/docker-compose.yml`. Replace `docker-compose`
> with `docker compose -f docker/docker-compose.yml` if you are using the v2 CLI.

## Quick Diagnostics

### Health Check Commands

```bash
# Check API health
curl http://localhost:8000/health

# Check database connectivity
docker-compose -f docker/docker-compose.yml exec postgres pg_isready -U postgres

# Check all services status
docker compose -f docker/docker-compose.yml ps

# View recent logs
docker compose -f docker/docker-compose.yml logs --tail=50 -f app
```

## Common Issues

### 1. Database Connection Issues

#### Symptoms
- API returns 500 errors
- "Connection refused" errors
- "Password authentication failed"

#### Diagnosis
```bash
# Check if PostgreSQL is running
docker compose -f docker/docker-compose.yml ps

# Test database connection
docker-compose -f docker/docker-compose.yml exec app psql -h postgres -U postgres -d chicago_crashes -c "SELECT 1;"

# Check database logs
docker compose -f docker/docker-compose.yml logs postgres
```

#### Solutions

**PostgreSQL not running:**
```bash
# Start database service
docker compose -f docker/docker-compose.yml up -d db

# Check if port is available
lsof -i :5432
```

**Authentication issues:**
```bash
# Reset password in docker-compose.yml
POSTGRES_PASSWORD=your_new_password

# Recreate database container
docker compose -f docker/docker-compose.yml down db
docker compose -f docker/docker-compose.yml up -d db
```

**PostGIS extension missing:**
```bash
# Install PostGIS extension
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

### 2. API Server Issues

#### Symptoms
- API not responding on port 8000
- "Module not found" errors
- Import errors

#### Diagnosis
```bash
# Check if API is running
curl -f http://localhost:8000/ || echo "API not responding"

# Check API logs
docker-compose -f docker/docker-compose.yml logs app

# Test from inside container
docker-compose -f docker/docker-compose.yml exec app python -c "import src.api.main"
```

#### Solutions

**Port conflicts:**
```bash
# Check what's using port 8000
lsof -i :8000

# Kill conflicting process
kill -9 <PID>

# Or change port in docker-compose.yml
ports:
  - "8001:8000"  # Map to different host port
```

**Python import issues:**
```bash
# Rebuild container with latest code
docker-compose build --no-cache api
docker compose -f docker/docker-compose.yml up -d api

# Check Python path
docker compose -f docker/docker-compose.yml exec app python -c "import sys; print('\n'.join(sys.path))"
```

**Missing dependencies:**
```bash
# Update requirements
pip freeze > requirements.txt
docker-compose build --no-cache api
```

### 3. Data Synchronization Issues

#### Symptoms
- Sync operations fail
- No new data appearing
- "Rate limit exceeded" errors

#### Diagnosis
```bash
# Check sync status
curl http://localhost:8000/sync/status

# Test SODA API connectivity
curl "https://data.cityofchicago.org/resource/85ca-t3if.json?\$limit=1"

# Check API logs for sync errors
docker compose -f docker/docker-compose.yml logs app | grep -i "error\|sync"
```

#### Solutions

**Rate limiting:**
```bash
# Reduce rate limit in config/settings.yaml
api:
  rate_limit: 500  # Reduce from 1000
  
# Wait before retrying
sleep 300  # Wait 5 minutes
```

**Invalid API token:**
```bash
# Update token in .env file
SODA_API_TOKEN=your_new_token

# Restart API service
docker-compose restart api
```

**Network connectivity:**
```bash
# Test DNS resolution
docker compose -f docker/docker-compose.yml exec app nslookup data.cityofchicago.org

# Test HTTPS connectivity
docker compose -f docker/docker-compose.yml exec app curl -I https://data.cityofchicago.org
```

### 4. Spatial Data Issues

#### Symptoms
- Shapefile loading fails
- PostGIS queries return errors
- Geometry validation issues

#### Diagnosis
```bash
# Check PostGIS extension
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes -c "SELECT PostGIS_version();"

# List spatial tables
curl http://localhost:8000/spatial/tables

# Check shapefile format
file data/shapefiles/*.shp
```

#### Solutions

**Missing PostGIS:**
```bash
# Install PostGIS extension
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes -c "CREATE EXTENSION postgis;"
```

**Invalid shapefile format:**
```bash
# Validate shapefile with GDAL
docker compose -f docker/docker-compose.yml exec app ogrinfo data/shapefiles/your_file.shp

# Convert to valid format
ogr2ogr -f "ESRI Shapefile" output.shp input.shp -t_srs EPSG:4326
```

**Coordinate system issues:**
```bash
# Check coordinate system
docker compose -f docker/docker-compose.yml exec app python -c "
import geopandas as gpd
gdf = gpd.read_file('data/shapefiles/your_file.shp')
print(f'CRS: {gdf.crs}')
"

# Reproject if needed
gdf = gdf.to_crs('EPSG:4326')
```

### 5. Performance Issues

#### Symptoms
- Slow API responses
- High memory usage
- Database queries timeout

#### Diagnosis
```bash
# Check resource usage
docker stats

# Monitor database queries
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes -c "
SELECT query, state, query_start 
FROM pg_stat_activity 
WHERE state != 'idle' 
ORDER BY query_start;
"

# Check slow queries
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -d chicago_crashes -c "
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
"
```

#### Solutions

**Memory issues:**
```bash
# Increase memory limits in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 4G

# Enable memory monitoring
docker compose -f docker/docker-compose.yml exec app python -c "
import psutil
print(f'Memory usage: {psutil.virtual_memory().percent}%')
"
```

**Slow queries:**
```sql
-- Create database indexes
CREATE INDEX CONCURRENTLY idx_crashes_date ON crashes(crash_date);
CREATE INDEX CONCURRENTLY idx_crashes_location ON crashes USING GIST(geometry);

-- Update statistics
ANALYZE crashes;
ANALYZE people;
ANALYZE vehicles;
```

**Connection pool exhaustion:**
```python
# Increase connection pool size in settings
database:
  pool_size: 20
  max_overflow: 0
```

### 6. Testing Issues

#### Symptoms
- Tests failing unexpectedly
- Mock objects not working
- Async tests hanging

#### Diagnosis
```bash
# Run tests with verbose output
python -m pytest tests/ -v -s

# Run specific test
python -m pytest tests/test_soda_client.py::TestSODAClient::test_fetch_records -v

# Check test coverage
python -m pytest tests/ --cov=src --cov-report=html
```

#### Solutions

**Async test issues:**
```bash
# Install required test dependencies
pip install pytest-asyncio pytest-httpx

# Check event loop configuration
python -c "
import asyncio
print(f'Event loop: {asyncio.get_event_loop_policy()}')
"
```

**Mock issues:**
```python
# Ensure proper mocking
with patch.object(client, '_make_request', return_value=mock_response):
    # Your test code here
    pass
```

**Import path issues:**
```bash
# Add project root to Python path
export PYTHONPATH="${PYTHONPATH}:/path/to/lakeview-crashes"

# Or use relative imports in tests
sys.path.append('/path/to/project/src')
```

## Environment-Specific Issues

### Development Environment

#### Virtual Environment Issues
```bash
# Recreate virtual environment
rm -rf venv/
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Python Path Issues
```bash
# Add to .bashrc or .zshrc
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Or create .env file
echo "PYTHONPATH=$(pwd)/src" >> .env
```

### Production Environment

#### Container Issues
```bash
# Check container health
docker inspect <container_id> | grep -A 5 "Health"

# Access container for debugging
docker exec -it <container_id> bash

# View container resource usage
docker stats <container_id>
```

#### Load Balancer Issues
```bash
# Check if load balancer can reach containers
curl -H "Host: yourdomain.com" http://container-ip:8000/health

# Verify nginx configuration
nginx -t

# Reload nginx configuration
nginx -s reload
```

## Debugging Tools

### 1. Interactive Debugging

```python
# Add to any Python file for debugging
import pdb; pdb.set_trace()

# Or use ipdb for better debugging
import ipdb; ipdb.set_trace()

# Remote debugging in containers
import ptvsd
ptvsd.enable_attach(address=('0.0.0.0', 5678))
ptvsd.wait_for_attach()
```

### 2. Logging Configuration

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Or use rich for better output
from rich.logging import RichHandler
logging.basicConfig(
    level=logging.DEBUG,
    format="%(message)s",
    handlers=[RichHandler()]
)
```

### 3. Database Debugging

```sql
-- Enable query logging
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();

-- Monitor current queries
SELECT 
    pid,
    now() - pg_stat_activity.query_start AS duration,
    query,
    state
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC;

-- Check locks
SELECT 
    t.relname,
    l.locktype,
    l.mode,
    l.granted,
    a.query
FROM pg_locks l
JOIN pg_stat_activity a ON l.pid = a.pid
JOIN pg_class t ON l.relation = t.oid
WHERE NOT l.granted;
```

## Data Quality Issues

### 1. Data Validation Failures

```bash
# Check validation status
curl "http://localhost:8000/validate/crashes?limit=100"

# View detailed validation errors
docker compose -f docker/docker-compose.yml logs app | grep -i "validation"
```

### 2. Geographic Data Issues

```python
# Check coordinate bounds
from utils.config import settings
print(f"Latitude bounds: {settings.validation.min_latitude} to {settings.validation.max_latitude}")
print(f"Longitude bounds: {settings.validation.min_longitude} to {settings.validation.max_longitude}")

# Validate specific coordinates
def check_chicago_bounds(lat, lon):
    return (41.6 <= lat <= 42.1) and (-87.9 <= lon <= -87.5)
```

### 3. Data Consistency Issues

```sql
-- Check for duplicate records
SELECT crash_record_id, COUNT(*) 
FROM crashes 
GROUP BY crash_record_id 
HAVING COUNT(*) > 1;

-- Check for missing relationships
SELECT c.crash_record_id 
FROM crashes c 
LEFT JOIN people p ON c.crash_record_id = p.crash_record_id 
WHERE p.crash_record_id IS NULL;
```

## Recovery Procedures

### 1. Database Recovery

```bash
# Restore from backup
docker compose -f docker/docker-compose.yml down
docker volume rm lakeview-crashes_postgres_data
docker compose -f docker/docker-compose.yml up -d db

# Restore data
gunzip -c backup_20240828.sql.gz | docker compose -f docker/docker-compose.yml exec -T postgres psql -U postgres -d chicago_crashes
```

### 2. Application Recovery

```bash
# Reset application state
docker compose -f docker/docker-compose.yml down
docker-compose pull
docker-compose build --no-cache
docker compose -f docker/docker-compose.yml up -d

# Clear cache and temporary data
rm -rf data/temp/
rm -rf logs/*.log
```

### 3. Full System Recovery

```bash
# Complete system reset
docker compose -f docker/docker-compose.yml down -v  # WARNING: This removes all data
docker system prune -af
docker compose -f docker/docker-compose.yml up -d --build

# Restore from backups
# ... restore database backup
# ... restore configuration files
# ... reload spatial data
```

## Prevention Strategies

### 1. Monitoring Setup

```bash
# Add health monitoring
*/5 * * * * curl -f http://localhost:8000/health || echo "API health check failed" | mail -s "Alert" admin@example.com
```

### 2. Automated Backups

```bash
# Add to crontab
0 2 * * * /path/to/backup-script.sh
0 3 * * 0 /path/to/cleanup-old-backups.sh
```

### 3. Log Rotation

```bash
# Configure log rotation
echo '/app/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    copytruncate
}' > /etc/logrotate.d/chicago-crashes
```

## Getting Help

### 1. Check Documentation
- [API Documentation](src/api/README.md)
- [Development Guide](docs/DEVELOPMENT_GUIDE.md)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)

### 2. Debug Information
When reporting issues, include:
- Error messages and stack traces
- System information (`docker compose -f docker/docker-compose.yml ps`, `docker version`)
- Configuration files (with sensitive data removed)
- Steps to reproduce the issue

### 3. Log Collection
```bash
# Collect all relevant logs
mkdir debug-info
docker-compose logs > debug-info/compose-logs.txt
docker compose -f docker/docker-compose.yml exec app python --version > debug-info/python-version.txt
docker compose -f docker/docker-compose.yml exec postgres psql -U postgres -c "SELECT version();" > debug-info/postgres-version.txt
tar -czf debug-info.tar.gz debug-info/
```

This troubleshooting guide should help you quickly identify and resolve most issues you'll encounter with the Chicago Crash Data Pipeline.

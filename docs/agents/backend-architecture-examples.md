# Backend Architecture Agent - Usage Examples

This document provides real-world examples of using the **Backend Architecture Agent** for the Chicago Traffic Crash Data Pipeline project.

---

## Example 1: Design New Data Source Integration (Traffic Signals)

### User Request
> "Can you help me add traffic signals from the Chicago Open Data Portal as a new data source?"

### Agent Workflow

**Complete end-to-end implementation following layered architecture**

#### Step 1: Create SQLAlchemy Model

```python
# src/models/traffic_signals.py
from sqlalchemy import Column, String, Integer, Float, DateTime, Index
from geoalchemy2 import Geometry
from src.models.base import Base, TimestampMixin

class TrafficSignal(Base, TimestampMixin):
    """Traffic signal locations and metadata from Chicago Open Data Portal."""

    __tablename__ = "traffic_signals"

    signal_id = Column(String(128), primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry = Column(Geometry('POINT', srid=4326), nullable=True)
    street_name = Column(String(255))
    cross_street = Column(String(255))
    signal_type = Column(String(100))
    installation_date = Column(DateTime)
    operational_status = Column(String(50))

    __table_args__ = (
        Index('ix_traffic_signals_location', 'latitude', 'longitude'),
        Index('ix_traffic_signals_geometry', 'geometry', postgresql_using='gist'),
        Index('ix_traffic_signals_street', 'street_name'),
    )

    def __repr__(self):
        return f"<TrafficSignal(signal_id={self.signal_id}, street={self.street_name})>"
```

#### Step 2: Add Sanitizer

```python
# src/validators/data_sanitizer.py (add method)
def sanitize_traffic_signal_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize traffic signal record."""
    sanitized = {}

    sanitized['signal_id'] = self._clean_string(record.get('signal_id'))
    sanitized['latitude'] = self._clean_coordinate(record.get('latitude'), 'latitude')
    sanitized['longitude'] = self._clean_coordinate(record.get('longitude'), 'longitude')
    sanitized['street_name'] = self._clean_string(record.get('street_name'))
    sanitized['cross_street'] = self._clean_string(record.get('cross_street'))
    sanitized['signal_type'] = self._clean_string(record.get('signal_type'))
    sanitized['installation_date'] = self._parse_datetime(record.get('installation_date'))
    sanitized['operational_status'] = self._clean_string(record.get('operational_status'))

    # Create PostGIS geometry
    if sanitized['latitude'] and sanitized['longitude']:
        sanitized['geometry'] = f"SRID=4326;POINT({sanitized['longitude']} {sanitized['latitude']})"

    return sanitized
```

#### Step 3: Add Database Service Method

```python
# src/services/database_service.py (add method)
def upsert_traffic_signal_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Upsert traffic signal records."""
    return self._upsert_records(
        model=TrafficSignal,
        records=records,
        prepare=self._prepare_traffic_signal_record
    )

def _prepare_traffic_signal_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Prepare traffic signal record for database insertion."""
    if not record.get('signal_id'):
        return None

    prepared = {
        'signal_id': record['signal_id'],
        'latitude': record.get('latitude'),
        'longitude': record.get('longitude'),
        'street_name': record.get('street_name'),
        'cross_street': record.get('cross_street'),
        'signal_type': record.get('signal_type'),
        'installation_date': record.get('installation_date'),
        'operational_status': record.get('operational_status')
    }

    # Handle PostGIS geometry
    if record.get('geometry'):
        from geoalchemy2.elements import WKTElement
        prepared['geometry'] = WKTElement(record['geometry'])

    return prepared
```

#### Step 4: Update SyncService

```python
# src/services/sync_service.py (update _sync_single_endpoint)
async def _sync_single_endpoint(self, client, endpoint: str, ...) -> EndpointSyncResult:
    """Sync single endpoint with appropriate sanitizer and database method."""

    # Map endpoint to handlers
    endpoint_handlers = {
        'crashes': (self.sanitizer.sanitize_crash_record, self.database_service.upsert_crash_records),
        'people': (self.sanitizer.sanitize_person_record, self.database_service.upsert_person_records),
        'vehicles': (self.sanitizer.sanitize_vehicle_record, self.database_service.upsert_vehicle_records),
        'traffic_signals': (  # NEW
            self.sanitizer.sanitize_traffic_signal_record,
            self.database_service.upsert_traffic_signal_records
        )
    }

    sanitizer_func, database_func = endpoint_handlers.get(endpoint)

    async for batch in client.iter_batches(...):
        # Sanitize batch
        cleaned = [sanitizer_func(record) for record in batch if sanitizer_func(record)]
        # Persist to database
        result = database_func(cleaned)
        # ...
```

#### Step 5: Add API Configuration

```python
# src/utils/config.py (update APISettings)
class APISettings(BaseSettings):
    endpoints: Dict[str, str] = {
        "crashes": "https://data.cityofchicago.org/resource/85ca-t3if.json",
        "people": "https://data.cityofchicago.org/resource/u6pd-qa9d.json",
        "vehicles": "https://data.cityofchicago.org/resource/68nd-jvt3.json",
        "vision_zero": "https://data.cityofchicago.org/resource/gzaz-isa6.json",
        "traffic_signals": "https://data.cityofchicago.org/resource/kfyz-pdh6.json"  # NEW
    }
```

#### Step 6: Create Database Migration

```bash
alembic revision --autogenerate -m "add traffic signals table"

# Review generated migration
# alembic/versions/def456_add_traffic_signals_table.py

def upgrade():
    op.create_table(
        'traffic_signals',
        sa.Column('signal_id', sa.String(128), primary_key=True),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('geometry', geoalchemy2.Geometry('POINT', srid=4326), nullable=True),
        sa.Column('street_name', sa.String(255)),
        sa.Column('cross_street', sa.String(255)),
        sa.Column('signal_type', sa.String(100)),
        sa.Column('installation_date', sa.DateTime()),
        sa.Column('operational_status', sa.String(50)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()')),
    )
    op.create_index('ix_traffic_signals_location', 'traffic_signals', ['latitude', 'longitude'])
    op.create_index('ix_traffic_signals_geometry', 'traffic_signals', ['geometry'], postgresql_using='gist')
    op.create_index('ix_traffic_signals_street', 'traffic_signals', ['street_name'])

# Apply migration
alembic upgrade head
```

#### Step 7: Add Test Coverage

```python
# tests/test_traffic_signals.py
import pytest
from src.validators.data_sanitizer import DataSanitizer
from src.services.database_service import DatabaseService
from src.models.traffic_signals import TrafficSignal

@pytest.fixture
def sample_signal_record():
    return {
        "signal_id": "SIG001",
        "latitude": "41.8781",
        "longitude": "-87.6298",
        "street_name": "MICHIGAN AVE",
        "cross_street": "MADISON ST",
        "signal_type": "TRAFFIC SIGNAL",
        "installation_date": "2020-01-15T00:00:00.000",
        "operational_status": "ACTIVE"
    }

def test_sanitize_traffic_signal_record(sample_signal_record):
    sanitizer = DataSanitizer()
    result = sanitizer.sanitize_traffic_signal_record(sample_signal_record)

    assert result['signal_id'] == "SIG001"
    assert result['latitude'] == 41.8781
    assert result['longitude'] == -87.6298
    assert result['street_name'] == "MICHIGAN AVE"
    assert "POINT(-87.6298 41.8781)" in result['geometry']

def test_upsert_traffic_signal_records(sample_signal_record):
    sanitizer = DataSanitizer()
    db_service = DatabaseService()

    sanitized = sanitizer.sanitize_traffic_signal_record(sample_signal_record)
    result = db_service.upsert_traffic_signal_records([sanitized])

    assert result['inserted'] == 1
    assert result['updated'] == 0
```

#### Step 8: Test the Integration

```bash
# Test sync
curl -X POST http://localhost:8000/sync/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "endpoint": "traffic_signals",
    "force": true
  }'

# Check database
psql -U postgres -d chicago_crashes -c "SELECT COUNT(*) FROM traffic_signals;"
```

### Expected Outcome

**Result**: Complete traffic signals integration with:
- ✅ Database model with PostGIS geometry
- ✅ Data sanitization logic
- ✅ Idempotent upsert operations
- ✅ Integration with sync service
- ✅ Database migration
- ✅ Spatial indexes for performance
- ✅ Test coverage
- ✅ API configuration

---

## Example 2: Optimize Slow Spatial Query (Crashes Near Intersections)

### User Request
> "This query to find crashes within 100 meters of traffic signals is timing out. Can you optimize it?"

### Agent Workflow

#### Step 1: Analyze Current Query

```sql
-- Current query (SLOW)
SELECT c.crash_record_id, c.crash_date, c.street_name
FROM crashes c, traffic_signals ts
WHERE ST_DWithin(
    c.geometry,
    ts.geometry,
    100  -- This is in DEGREES, not meters!
)
LIMIT 1000;

-- EXPLAIN ANALYZE shows:
-- Nested Loop (cost=0.00..250000.00 rows=1000000 width=100) (actual time=45000.123..60000.456 rows=50000 loops=1)
-- -> Seq Scan on crashes (cost=0.00..50000.00 rows=1000000)
-- -> Seq Scan on traffic_signals (cost=0.00..200.00 rows=5000)
-- Planning Time: 1.234 ms
-- Execution Time: 60123.456 ms  ← 60 SECONDS!
```

**Problems Identified**:
1. **Wrong SRID usage**: ST_DWithin with SRID 4326 expects degrees, not meters
2. **No index usage**: Sequential scans on both tables
3. **Cartesian join**: Every crash checked against every signal

#### Step 2: Fix SRID Issue

```sql
-- Option A: Transform to planar projection (State Plane Illinois)
SELECT c.crash_record_id, c.crash_date, c.street_name
FROM crashes c
JOIN traffic_signals ts ON ST_DWithin(
    ST_Transform(c.geometry, 3435),  -- Transform to Illinois State Plane (feet)
    ST_Transform(ts.geometry, 3435),
    328  -- 100 meters = 328 feet
)
LIMIT 1000;

-- Option B: Use geography type (spherical calculations, slower but accurate)
SELECT c.crash_record_id, c.crash_date, c.street_name
FROM crashes c
JOIN traffic_signals ts ON ST_DWithin(
    c.geometry::geography,
    ts.geometry::geography,
    100  -- 100 meters
)
LIMIT 1000;

-- Option C: Pre-filter with bounding box (fastest)
SELECT c.crash_record_id, c.crash_date, c.street_name
FROM crashes c
JOIN traffic_signals ts ON
    ST_DWithin(
        c.geometry,
        ts.geometry,
        0.001  -- ~100m in degrees (approximate)
    )
    AND ST_Distance(
        c.geometry::geography,
        ts.geometry::geography
    ) <= 100  -- Exact distance check
LIMIT 1000;
```

#### Step 3: Add Optimized Indexes

```sql
-- Create GIST indexes if not exist
CREATE INDEX IF NOT EXISTS ix_crashes_geometry ON crashes USING GIST(geometry);
CREATE INDEX IF NOT EXISTS ix_traffic_signals_geometry ON traffic_signals USING GIST(geometry);

-- Add transformed geometry columns for State Plane
ALTER TABLE crashes ADD COLUMN geometry_state_plane GEOMETRY(POINT, 3435);
ALTER TABLE traffic_signals ADD COLUMN geometry_state_plane GEOMETRY(POINT, 3435);

-- Populate transformed geometries
UPDATE crashes SET geometry_state_plane = ST_Transform(geometry, 3435) WHERE geometry IS NOT NULL;
UPDATE traffic_signals SET geometry_state_plane = ST_Transform(geometry, 3435) WHERE geometry IS NOT NULL;

-- Index transformed geometries
CREATE INDEX ix_crashes_geometry_state_plane ON crashes USING GIST(geometry_state_plane);
CREATE INDEX ix_traffic_signals_geometry_state_plane ON traffic_signals USING GIST(geometry_state_plane);
```

#### Step 4: Implement Optimized Service Method

```python
# src/services/crash_service.py
from typing import List, Dict, Any
from sqlalchemy import func
from geoalchemy2.functions import ST_DWithin, ST_Transform, ST_Distance
from src.models.crashes import Crash
from src.models.traffic_signals import TrafficSignal

class CrashService:
    def __init__(self, session):
        self.session = session

    def get_crashes_near_signals(
        self,
        distance_meters: int = 100,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get crashes within specified distance of traffic signals.

        Uses State Plane Illinois (SRID 3435) for accurate distance calculations.

        Args:
            distance_meters: Distance in meters
            limit: Maximum results

        Returns:
            List of crash records with distance to nearest signal
        """
        # Convert meters to feet (State Plane Illinois is in feet)
        distance_feet = distance_meters * 3.28084

        # Use pre-transformed geometry for performance
        query = self.session.query(
            Crash.crash_record_id,
            Crash.crash_date,
            Crash.street_name,
            Crash.latitude,
            Crash.longitude,
            TrafficSignal.signal_id,
            TrafficSignal.street_name.label('signal_street'),
            func.round(
                ST_Distance(
                    Crash.geometry_state_plane,
                    TrafficSignal.geometry_state_plane
                ) / 3.28084,  # Convert feet back to meters
                2
            ).label('distance_meters')
        ).join(
            TrafficSignal,
            ST_DWithin(
                Crash.geometry_state_plane,
                TrafficSignal.geometry_state_plane,
                distance_feet
            )
        ).order_by(
            Crash.crash_date.desc()
        ).limit(limit)

        return [
            {
                'crash_record_id': row.crash_record_id,
                'crash_date': row.crash_date.isoformat(),
                'street_name': row.street_name,
                'latitude': row.latitude,
                'longitude': row.longitude,
                'nearest_signal_id': row.signal_id,
                'signal_street': row.signal_street,
                'distance_meters': float(row.distance_meters)
            }
            for row in query
        ]
```

#### Step 5: Add API Endpoint

```python
# src/api/routers/spatial.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.models.base import get_db
from src.services.crash_service import CrashService

router = APIRouter(prefix="/spatial", tags=["spatial"])

@router.get("/crashes/near-signals")
async def get_crashes_near_signals(
    distance: int = Query(default=100, ge=10, le=1000, description="Distance in meters"),
    limit: int = Query(default=100, ge=1, le=10000, description="Max results"),
    db: Session = Depends(get_db)
):
    """Get crashes within specified distance of traffic signals."""
    service = CrashService(db)
    return service.get_crashes_near_signals(
        distance_meters=distance,
        limit=limit
    )
```

#### Step 6: Create Database Migration

```bash
alembic revision -m "add state plane geometry columns for performance"
```

```python
# alembic/versions/ghi789_add_state_plane_geometry.py
def upgrade():
    # Add transformed geometry columns
    op.add_column('crashes', sa.Column('geometry_state_plane', geoalchemy2.Geometry('POINT', srid=3435)))
    op.add_column('traffic_signals', sa.Column('geometry_state_plane', geoalchemy2.Geometry('POINT', srid=3435)))

    # Populate from existing geometry
    op.execute("""
        UPDATE crashes
        SET geometry_state_plane = ST_Transform(geometry, 3435)
        WHERE geometry IS NOT NULL
    """)

    op.execute("""
        UPDATE traffic_signals
        SET geometry_state_plane = ST_Transform(geometry, 3435)
        WHERE geometry IS NOT NULL
    """)

    # Create GIST indexes
    op.create_index(
        'ix_crashes_geometry_state_plane',
        'crashes',
        ['geometry_state_plane'],
        postgresql_using='gist'
    )

    op.create_index(
        'ix_traffic_signals_geometry_state_plane',
        'traffic_signals',
        ['geometry_state_plane'],
        postgresql_using='gist'
    )

def downgrade():
    op.drop_index('ix_traffic_signals_geometry_state_plane', table_name='traffic_signals')
    op.drop_index('ix_crashes_geometry_state_plane', table_name='crashes')
    op.drop_column('traffic_signals', 'geometry_state_plane')
    op.drop_column('crashes', 'geometry_state_plane')
```

#### Step 7: Verify Performance

```sql
-- Test optimized query
EXPLAIN ANALYZE
SELECT c.crash_record_id, c.crash_date
FROM crashes c
JOIN traffic_signals ts ON ST_DWithin(
    c.geometry_state_plane,
    ts.geometry_state_plane,
    328  -- 100 meters in feet
)
LIMIT 1000;

-- Expected output:
-- Nested Loop (cost=0.42..125.67 rows=1000 width=50) (actual time=0.123..45.678 rows=1000 loops=1)
-- -> Index Scan using ix_traffic_signals_geometry_state_plane on traffic_signals
-- -> Index Scan using ix_crashes_geometry_state_plane on crashes
--    Index Cond: ST_DWithin(geometry_state_plane, ts.geometry_state_plane, 328)
-- Planning Time: 0.456 ms
-- Execution Time: 47.234 ms  ← 99.9% FASTER!
```

### Expected Outcome

**Result**: Optimized spatial query with:
- ✅ 99.9% performance improvement (60s → 47ms)
- ✅ Correct distance calculations (meters, not degrees)
- ✅ Spatial index usage (GIST indexes)
- ✅ State Plane projection for accuracy
- ✅ Clean service layer API
- ✅ RESTful endpoint with validation
- ✅ Database migration for schema changes

**Before/After**:
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Execution time | 60,123ms | 47ms | 99.92% faster |
| Index usage | None (seq scans) | GIST indexes | ✅ |
| Distance accuracy | Wrong (degrees) | Correct (meters) | ✅ |
| Scalability | Poor (cartesian) | Good (indexed join) | ✅ |

---

## Example 3: Implement Rate Limiting Middleware

### User Request
> "We're getting hammered by API requests. Can you add rate limiting to protect the server?"

### Agent Workflow

#### Step 1: Install Dependencies

```bash
pip install slowapi redis
```

#### Step 2: Configure Redis

```python
# src/utils/config.py
class RateLimitSettings(BaseSettings):
    enabled: bool = Field(default=True, env="RATE_LIMIT_ENABLED")
    redis_url: str = Field(default="redis://localhost:6379", env="REDIS_URL")
    default_limit: str = Field(default="100/minute", env="RATE_LIMIT_DEFAULT")
    authenticated_limit: str = Field(default="1000/minute", env="RATE_LIMIT_AUTHENTICATED")

class Settings(BaseSettings):
    # ... existing settings ...
    rate_limit: RateLimitSettings = RateLimitSettings()
```

#### Step 3: Create Rate Limit Middleware

```python
# src/api/middleware/rate_limit.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, HTTPException
from src.utils.config import settings

# Create limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.rate_limit.redis_url,
    enabled=settings.rate_limit.enabled
)

def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key based on authentication status."""
    # Check for API key in header
    api_key = request.headers.get("X-API-Key")
    if api_key and verify_api_key(api_key):
        return f"authenticated:{api_key}"

    # Fall back to IP address
    return get_remote_address(request)

def verify_api_key(api_key: str) -> bool:
    """Verify API key (implement your logic)."""
    # In production, check against database or secrets manager
    return api_key == settings.api_key_secret
```

#### Step 4: Apply Middleware to FastAPI App

```python
# src/api/main.py
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from src.api.middleware.rate_limit import limiter
from src.utils.config import settings

app = FastAPI(...)

# Add rate limiter state
app.state.limiter = limiter

# Add exception handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Custom error response
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return custom error response for rate limit exceeded."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": "Too many requests. Please try again later.",
            "retry_after": exc.retry_after  # Seconds until next allowed request
        },
        headers={
            "Retry-After": str(exc.retry_after),
            "X-RateLimit-Limit": str(exc.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(exc.reset)
        }
    )
```

#### Step 5: Apply Rate Limits to Endpoints

```python
# src/api/routers/sync.py
from src.api.middleware.rate_limit import limiter
from src.utils.config import settings

@router.post("/sync/trigger")
@limiter.limit(settings.rate_limit.default_limit)  # 100 requests/minute
async def trigger_sync(request: Request, sync_request: SyncRequest, ...):
    """Trigger manual sync with rate limiting."""
    # ... existing logic

# Different limits for different endpoints
@router.get("/sync/status")
@limiter.limit("1000/minute")  # Higher limit for read-only
async def get_sync_status(request: Request):
    """Get sync status (higher rate limit for reads)."""
    # ... existing logic

@router.post("/sync/test")
@limiter.limit("10/minute")  # Lower limit for expensive operations
async def test_sync(request: Request, ...):
    """Test sync (lower limit for expensive operation)."""
    # ... existing logic
```

#### Step 6: Add Dependency-Based Rate Limiting

```python
# src/api/dependencies.py
from slowapi import Limiter
from fastapi import Request, Depends, HTTPException
from src.api.middleware.rate_limit import limiter, get_rate_limit_key

def rate_limit_dependency(limit: str):
    """Create a rate limit dependency."""
    async def _rate_limit(request: Request):
        try:
            await limiter.check_rate_limit(request, limit)
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(e.retry_after)}
            )
    return _rate_limit

# Usage in routers
@router.post("/jobs/")
async def create_job(
    job_data: CreateJobRequest,
    _: None = Depends(rate_limit_dependency("50/minute"))
):
    """Create job with custom rate limit."""
    # ... existing logic
```

#### Step 7: Add Monitoring and Metrics

```python
# src/api/middleware/rate_limit.py
import structlog
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# Prometheus metrics
rate_limit_counter = Counter(
    'rate_limit_exceeded_total',
    'Number of rate limit exceeded errors',
    ['endpoint', 'method']
)

rate_limit_latency = Histogram(
    'rate_limit_check_seconds',
    'Time spent checking rate limits',
    ['endpoint']
)

# Middleware to track rate limit hits
@app.middleware("http")
async def track_rate_limits(request: Request, call_next):
    endpoint = request.url.path

    with rate_limit_latency.labels(endpoint=endpoint).time():
        try:
            response = await call_next(request)

            # Add rate limit headers to all responses
            if hasattr(request.state, 'view_rate_limit'):
                response.headers["X-RateLimit-Limit"] = str(request.state.view_rate_limit.limit)
                response.headers["X-RateLimit-Remaining"] = str(request.state.view_rate_limit.remaining)
                response.headers["X-RateLimit-Reset"] = str(request.state.view_rate_limit.reset)

            return response

        except RateLimitExceeded as e:
            rate_limit_counter.labels(
                endpoint=endpoint,
                method=request.method
            ).inc()

            logger.warning(
                "Rate limit exceeded",
                endpoint=endpoint,
                method=request.method,
                client_ip=get_remote_address(request),
                retry_after=e.retry_after
            )

            raise
```

#### Step 8: Test Rate Limiting

```bash
# Test with curl
for i in {1..150}; do
  curl -w "\nStatus: %{http_code}\n" http://localhost:8000/sync/status
  sleep 0.1
done

# Expected: First 100 requests succeed, remaining get 429

# Test with API key (higher limit)
for i in {1..150}; do
  curl -H "X-API-Key: your-api-key" \
       -w "\nStatus: %{http_code}\n" \
       http://localhost:8000/sync/status
  sleep 0.05
done

# Expected: First 1000 requests succeed (authenticated limit)
```

### Expected Outcome

**Result**: Production-ready rate limiting with:
- ✅ Redis-backed rate limit storage (distributed, persistent)
- ✅ Per-endpoint rate limits (flexible configuration)
- ✅ API key-based authentication (higher limits for authenticated users)
- ✅ Custom error responses with retry headers
- ✅ Prometheus metrics for monitoring
- ✅ Structured logging for debugging
- ✅ IP-based rate limiting for anonymous users

**Configuration Examples**:
```env
RATE_LIMIT_ENABLED=true
REDIS_URL=redis://localhost:6379
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_AUTHENTICATED=1000/minute
```

---

## Summary

These examples demonstrate the **Backend Architecture Agent's** capabilities:

1. **New data source integration** - Complete end-to-end implementation (model → service → API → migration → tests)
2. **Spatial query optimization** - 99.9% performance improvement with proper indexing and SRID handling
3. **Rate limiting middleware** - Production-ready protection with Redis, monitoring, and flexible limits

The agent provides:
- ✅ **Complete implementations** following layered architecture
- ✅ **Performance optimization** with EXPLAIN ANALYZE and proper indexing
- ✅ **Production-ready patterns** (error handling, logging, monitoring)
- ✅ **Database migrations** with up/down paths
- ✅ **Comprehensive testing** for all new code
- ✅ **Scalability** through proper architecture decisions

Invoke the Backend Architecture Agent for complex backend features, performance optimization, and architectural decisions.

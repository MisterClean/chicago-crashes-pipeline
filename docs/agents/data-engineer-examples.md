# Data Engineer Agent - Usage Examples

This document provides real-world examples of how to use the Data Engineer Agent for the Chicago Traffic Crash Data Pipeline.

## Overview

The Data Engineer Agent is a specialized assistant that understands the Chicago Crashes Pipeline architecture, patterns, and best practices. It can help with ETL optimization, data quality debugging, schema design, performance tuning, and more.

## Example 1: Optimize ETL Performance

### Scenario
The daily crash sync job is taking 45 minutes to complete, which is too slow for our operational needs.

### Task
**User**: "The crash sync is taking too long. Can you optimize it?"

### Agent Workflow

1. **Reviews Current Performance**
   - Reads [src/services/sync_service.py](../../src/services/sync_service.py:78-120) to understand the sync flow
   - Checks batch size configuration in settings (currently 50K)
   - Reviews SODAClient rate limiting setup

2. **Analyzes Bottlenecks**
   - Examines [src/etl/soda_client.py](../../src/etl/soda_client.py:100-150) for rate limiter configuration
   - Checks database connection pooling (pool_size=10, max_overflow=20)
   - Reviews [src/services/database_service.py](../../src/services/database_service.py:50-100) upsert performance

3. **Checks Database Indexes**
   - Reviews [src/models/crashes.py](../../src/models/crashes.py:80-120) for existing indexes
   - Identifies composite index: `ix_crashes_date_location`
   - Verifies spatial indexes on geometry column

4. **Proposes Optimizations**
   ```python
   # 1. Increase concurrent requests
   settings.api.max_concurrent = 10  # Up from 5

   # 2. Optimize batch size for upserts
   settings.database.bulk_insert_size = 2000  # Up from 1000

   # 3. Add missing index for common queries
   Index('ix_crashes_date_beat', 'crash_date', 'beat_of_occurrence')

   # 4. Use COPY protocol for bulk inserts
   settings.database.use_copy = True
   ```

5. **Performance Expectations**
   - Concurrent requests: 30% improvement (30 minutes)
   - Bulk insert optimization: 15% improvement (25 minutes)
   - Combined: Sync should complete in ~20-25 minutes

### Expected Outcome
- Identified specific bottlenecks in API calls and database upserts
- Provided concrete configuration changes
- Set realistic performance expectations

---

## Example 2: Add New Data Source (Traffic Signals)

### Scenario
The city wants to correlate crash data with nearby traffic signals to analyze whether signal malfunctions contribute to accidents.

### Task
**User**: "Add traffic signals data from SODA endpoint `3aav-uy2v.json`"

### Agent Workflow

1. **Create SQLAlchemy Model**

   Creates `src/models/traffic_signals.py`:
   ```python
   from geoalchemy2 import Geometry
   from sqlalchemy import Column, String, Float, Integer, Index
   from src.models.base import Base, TimestampMixin

   class TrafficSignal(Base, TimestampMixin):
       """Traffic signal locations and metadata."""
       __tablename__ = "traffic_signals"

       signal_id = Column(String, primary_key=True)
       latitude = Column(Float)
       longitude = Column(Float)
       geometry = Column(Geometry('POINT', srid=4326), nullable=True)

       # Signal metadata
       street_address = Column(String)
       signal_type = Column(String)
       num_phases = Column(Integer)
       has_pedestrian_signal = Column(String)
       last_inspection_date = Column(DateTime)

       __table_args__ = (
           Index('ix_traffic_signals_location', 'latitude', 'longitude'),
           Index('ix_traffic_signals_type', 'signal_type'),
       )
   ```

2. **Add Sanitization Method**

   Updates [src/validators/data_sanitizer.py](../../src/validators/data_sanitizer.py):
   ```python
   def sanitize_traffic_signal_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
       """Sanitize a traffic signal record.

       Args:
           record: Raw traffic signal record from API

       Returns:
           Sanitized record
       """
       sanitized = {}

       # Required fields
       sanitized['signal_id'] = self._clean_string(record.get('signal_id'))

       # Coordinates
       sanitized['latitude'] = self._clean_coordinate(
           record.get('latitude'),
           coord_type='latitude'
       )
       sanitized['longitude'] = self._clean_coordinate(
           record.get('longitude'),
           coord_type='longitude'
       )

       # String fields
       sanitized['street_address'] = self._clean_string(record.get('street_address'))
       sanitized['signal_type'] = self._clean_string(record.get('signal_type'))
       sanitized['has_pedestrian_signal'] = self._clean_string(
           record.get('has_pedestrian_signal')
       )

       # Integer fields
       sanitized['num_phases'] = self._clean_integer(record.get('num_phases'))

       # Datetime fields
       sanitized['last_inspection_date'] = self._parse_datetime(
           record.get('last_inspection_date')
       )

       return sanitized
   ```

3. **Implement Upsert Method**

   Updates [src/services/database_service.py](../../src/services/database_service.py):
   ```python
   def upsert_traffic_signal_records(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
       """Upsert traffic signal records using streaming pattern.

       Args:
           records: List of sanitized traffic signal records

       Returns:
           Dict with inserted and updated counts
       """
       from src.models.traffic_signals import TrafficSignal
       return self._upsert_records(
           records=records,
           model_class=TrafficSignal,
           pk_field='signal_id',
           prepare_func=self._prepare_traffic_signal_record
       )

   def _prepare_traffic_signal_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
       """Prepare traffic signal record for database insertion."""
       prepared = {k: v for k, v in record.items() if k in TrafficSignal.__table__.columns}

       # Create geometry from coordinates
       if record.get('latitude') and record.get('longitude'):
           from geoalchemy2.elements import WKTElement
           point_wkt = f"POINT({record['longitude']} {record['latitude']})"
           prepared['geometry'] = WKTElement(point_wkt, srid=4326)

       return prepared
   ```

4. **Update SyncService**

   Updates [src/services/sync_service.py](../../src/services/sync_service.py):
   ```python
   def _sanitize_batch(self, endpoint: str, batch: List[Dict]) -> List[Dict]:
       """Route batch to appropriate sanitizer."""
       if endpoint == "crashes":
           return [self.sanitizer.sanitize_crash_record(r) for r in batch]
       elif endpoint == "people":
           return [self.sanitizer.sanitize_person_record(r) for r in batch]
       elif endpoint == "vehicles":
           return [self.sanitizer.sanitize_vehicle_record(r) for r in batch]
       elif endpoint == "fatalities":
           return [self.sanitizer.sanitize_fatality_record(r) for r in batch]
       elif endpoint == "traffic_signals":  # NEW
           return [self.sanitizer.sanitize_traffic_signal_record(r) for r in batch]
       else:
           return batch

   def _persist_batch(self, endpoint: str, batch: List[Dict]) -> Dict[str, int]:
       """Route batch to appropriate upsert method."""
       if endpoint == "crashes":
           return self.database_service.upsert_crash_records(batch)
       elif endpoint == "people":
           return self.database_service.upsert_person_records(batch)
       elif endpoint == "vehicles":
           return self.database_service.upsert_vehicle_records(batch)
       elif endpoint == "fatalities":
           return self.database_service.upsert_fatality_records(batch)
       elif endpoint == "traffic_signals":  # NEW
           return self.database_service.upsert_traffic_signal_records(batch)
       else:
           return {"inserted": 0, "updated": 0, "skipped": 0}
   ```

5. **Update Configuration**

   Updates `config/config.yaml`:
   ```yaml
   api:
     endpoints:
       crashes: "https://data.cityofchicago.org/resource/85ca-t3if.json"
       people: "https://data.cityofchicago.org/resource/u6pd-qa9d.json"
       vehicles: "https://data.cityofchicago.org/resource/68nd-jvt3.json"
       fatalities: "https://data.cityofchicago.org/resource/gzaz-isa6.json"
       traffic_signals: "https://data.cityofchicago.org/resource/3aav-uy2v.json"  # NEW
   ```

6. **Create Alembic Migration**
   ```bash
   alembic revision --autogenerate -m "Add traffic_signals table"
   alembic upgrade head
   ```

7. **Add Tests**

   Creates `tests/test_traffic_signals.py`:
   ```python
   import pytest
   from src.validators.data_sanitizer import DataSanitizer

   def test_sanitize_traffic_signal_record():
       sanitizer = DataSanitizer()

       raw_record = {
           'signal_id': 'SIG-001',
           'latitude': '41.8781',
           'longitude': '-87.6298',
           'street_address': '123 Main St',
           'signal_type': 'STANDARD',
           'num_phases': '4',
           'has_pedestrian_signal': 'Y'
       }

       sanitized = sanitizer.sanitize_traffic_signal_record(raw_record)

       assert sanitized['signal_id'] == 'SIG-001'
       assert sanitized['latitude'] == 41.8781
       assert sanitized['longitude'] == -87.6298
       assert sanitized['num_phases'] == 4
   ```

### Expected Outcome
- New `traffic_signals` table with PostGIS geometry support
- Sanitization and validation following existing patterns
- Streaming upsert capability
- Full integration with existing ETL pipeline
- Database migration tracked in Alembic

---

## Example 3: Debug Data Quality Issue (Invalid Coordinates)

### Scenario
Data analysts report that some crash records appear on maps in unexpected locations, like the middle of Lake Michigan.

### Task
**User**: "Some crashes have coordinates outside Chicago. Why is this happening?"

### Agent Workflow

1. **Reviews Validation Logic**

   Reads [src/validators/data_sanitizer.py:40-48](../../src/validators/data_sanitizer.py:40-48):
   ```python
   def _clean_coordinate(self, value: Any, coord_type: str) -> Optional[float]:
       """Clean and validate coordinate value."""
       coord = self._clean_float(value)
       if coord is None:
           return None

       # Validate against Chicago bounds
       if coord_type == 'latitude':
           if not (self.validation_settings.min_latitude <= coord <=
                   self.validation_settings.max_latitude):
               logger.debug(f"Latitude {coord} outside valid range")
               return None
       elif coord_type == 'longitude':
           if not (self.validation_settings.min_longitude <= coord <=
                   self.validation_settings.max_longitude):
               logger.debug(f"Longitude {coord} outside valid range")
               return None

       return coord
   ```

2. **Checks Validation Bounds**

   Reviews configuration:
   ```python
   settings.validation.min_latitude = 41.6
   settings.validation.max_latitude = 42.1
   settings.validation.min_longitude = -87.95
   settings.validation.max_longitude = -87.5
   ```

3. **Queries Database for Outliers**

   ```sql
   -- Find records with out-of-bounds coordinates
   SELECT
       crash_record_id,
       crash_date,
       latitude,
       longitude,
       ST_AsText(geometry) as point
   FROM crashes
   WHERE (latitude NOT BETWEEN 41.6 AND 42.1
      OR longitude NOT BETWEEN -87.95 AND -87.5)
     AND latitude IS NOT NULL
   LIMIT 10;

   -- Count total affected records
   SELECT COUNT(*) as out_of_bounds_count
   FROM crashes
   WHERE (latitude NOT BETWEEN 41.6 AND 42.1
      OR longitude NOT BETWEEN -87.95 AND -87.5)
     AND latitude IS NOT NULL;
   ```

4. **Analyzes Results**

   Discovers:
   - 127 records with latitude/longitude outside bounds
   - These records still have latitude/longitude values BUT geometry is NULL
   - Reason: Validation happens AFTER field assignment in sanitize_crash_record()

5. **Identifies Root Cause**

   The issue is in [src/validators/data_sanitizer.py:30-48](../../src/validators/data_sanitizer.py:30-48):
   ```python
   # This returns the invalid coordinate to the sanitized dict
   sanitized['latitude'] = self._clean_coordinate(record.get('latitude'), 'latitude')
   sanitized['longitude'] = self._clean_coordinate(record.get('longitude'), 'longitude')
   ```

   But in [src/services/database_service.py](../../src/services/database_service.py), geometry creation is protected:
   ```python
   if record.get('latitude') and record.get('longitude'):
       # Geometry creation happens here - if coordinates are invalid,
       # they were already set to None by _clean_coordinate()
       point_wkt = f"POINT({record['longitude']} {record['latitude']})"
       prepared['geometry'] = WKTElement(point_wkt, srid=4326)
   ```

6. **Explains Current Behavior**

   **Current system behavior**:
   - Out-of-bounds coordinates return `None` from `_clean_coordinate()`
   - Sanitized record gets `latitude=None, longitude=None`
   - Database record is inserted with NULL lat/lon/geometry
   - These records exist but aren't queryable spatially

   **Why some appear on maps**:
   - If validation bounds are too restrictive, valid Chicago suburbs are rejected
   - If coordinate swap occurs (lat/lon reversed), validation may pass incorrectly

7. **Proposes Solutions**

   **Option A: Strict Validation (Recommended for data integrity)**
   ```python
   # In sync_service.py, filter out records with null coordinates
   def _sanitize_batch(self, endpoint: str, batch: List[Dict]) -> List[Dict]:
       sanitized = [self.sanitizer.sanitize_crash_record(r) for r in batch]
       # Filter out records without valid coordinates
       return [r for r in sanitized if r.get('latitude') and r.get('longitude')]
   ```

   **Option B: Flag for Review (Recommended for analysis)**
   ```python
   # Add migration to add boolean field
   class Crash(Base):
       needs_geocoding = Column(Boolean, default=False)

   # In database_service.py
   def _prepare_crash_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
       prepared = {...}
       prepared['needs_geocoding'] = not (record.get('latitude') and record.get('longitude'))
       return prepared
   ```

   **Option C: Expand Validation Bounds**
   ```python
   # If suburbs are valid crash locations, expand bounds:
   settings.validation.min_latitude = 41.5  # Include more south suburbs
   settings.validation.max_latitude = 42.2  # Include more north suburbs
   ```

### Expected Outcome
- Identified that 127 records have invalid coordinates
- Explained current validation behavior
- Provided 3 options with different trade-offs
- Recommended Option B (flagging) for transparency and future geocoding

---

## Example 4: Analyze Slow Spatial Query

### Scenario
A dashboard query that finds crashes within 500 meters of schools is timing out.

### Task
**User**: "This spatial query is too slow: `SELECT * FROM crashes WHERE ST_DWithin(geometry, $school_point, 500)`"

### Agent Workflow

1. **Checks Spatial Index**

   Verifies GiST index exists on geometry column in [src/models/crashes.py](../../src/models/crashes.py):
   ```python
   geometry = Column(Geometry('POINT', srid=4326), nullable=True, index=True)
   ```

2. **Runs EXPLAIN ANALYZE**

   ```sql
   EXPLAIN ANALYZE
   SELECT crash_record_id, crash_date, ST_AsText(geometry)
   FROM crashes
   WHERE ST_DWithin(
       geometry,
       ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326),
       500
   );
   ```

3. **Identifies Issue**

   EXPLAIN shows:
   - Sequential Scan (not using GiST index)
   - Reason: ST_DWithin with distance in degrees, not meters
   - SRID 4326 uses degrees, but distance is specified in meters

4. **Explains Geographic Coordinate Issue**

   ```
   SRID 4326 (WGS84) uses degrees, not meters:
   - 1 degree latitude ≈ 111 km
   - 1 degree longitude ≈ 85 km at Chicago's latitude
   - 500 meters ≈ 0.0045 degrees
   ```

5. **Proposes Solutions**

   **Option A: Use ST_DWithin with Geography (Recommended)**
   ```sql
   SELECT crash_record_id, crash_date
   FROM crashes
   WHERE ST_DWithin(
       geometry::geography,  -- Cast to geography type
       ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326)::geography,
       500  -- Now in meters
   );
   ```

   **Option B: Use Bounding Box First (Faster for large datasets)**
   ```sql
   -- Create helper function to convert meters to degrees
   WITH bounds AS (
       SELECT 500.0 / 111000.0 AS degree_buffer  -- Approximate
   )
   SELECT crash_record_id, crash_date
   FROM crashes, bounds
   WHERE geometry && ST_Expand(
       ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326),
       degree_buffer
   )
   AND ST_DWithin(
       geometry::geography,
       ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326)::geography,
       500
   );
   ```

   **Option C: Store Geometry in Projected CRS**
   ```python
   # Add projected geometry column in meters (EPSG:3857 - Web Mercator)
   class Crash(Base):
       geometry = Column(Geometry('POINT', srid=4326))
       geometry_projected = Column(Geometry('POINT', srid=3857), index=True)

   # Query with projected coordinates
   SELECT crash_record_id
   FROM crashes
   WHERE ST_DWithin(
       geometry_projected,
       ST_Transform(ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326), 3857),
       500  -- Meters in EPSG:3857
   );
   ```

### Expected Outcome
- Identified SRID/distance unit mismatch
- Explained degree vs meter confusion
- Provided 3 solutions with performance trade-offs
- Recommended Option B for immediate use, Option C for long-term optimization

---

## Example 5: Create Incremental Sync Job

### Scenario
Instead of syncing all crash data daily, we want to sync only records updated in the last 7 days.

### Task
**User**: "Create a job that syncs only crashes from the last 7 days, running daily at 2 AM"

### Agent Workflow

1. **Designs Job Configuration**

   ```python
   from src.models.jobs import JobType, RecurrenceType
   from src.services.job_service import JobService

   job_service = JobService()

   job = job_service.create_job(
       name="Daily Incremental Crash Sync",
       job_type=JobType.CUSTOM,
       recurrence_type=RecurrenceType.DAILY,
       next_run=datetime(2024, 1, 1, 2, 0, 0),  # 2 AM daily
       timeout_seconds=1800,  # 30 minutes
       max_retries=3,
       custom_config={
           "endpoints": ["crashes"],
           "date_range": {
               "type": "relative",
               "days_back": 7
           }
       }
   )
   ```

2. **Explains Date Filtering**

   The SODAClient supports incremental sync using the `:updated_at` system field:
   ```python
   # In soda_client.py
   where_clause = f":updated_at >= '{start_date}T00:00:00'"
   url = f"{base_url}?$where={where_clause}&$limit={batch_size}"
   ```

3. **Creates API Endpoint**

   Adds to [src/api/routers/jobs.py](../../src/api/routers/jobs.py):
   ```python
   @router.post("/jobs", response_model=JobResponse)
   async def create_scheduled_job(
       job_data: JobCreate,
       db: Session = Depends(get_db)
   ):
       """Create a new scheduled job."""
       job_service = JobService(db)
       job = job_service.create_job(
           name=job_data.name,
           job_type=job_data.job_type,
           recurrence_type=job_data.recurrence_type,
           next_run=job_data.next_run,
           timeout_seconds=job_data.timeout_seconds,
           max_retries=job_data.max_retries,
           custom_config=job_data.custom_config
       )
       return job
   ```

4. **Provides curl Example**

   ```bash
   curl -X POST http://localhost:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Daily Incremental Crash Sync",
       "job_type": "CUSTOM",
       "recurrence_type": "DAILY",
       "next_run": "2024-01-15T02:00:00",
       "timeout_seconds": 1800,
       "max_retries": 3,
       "custom_config": {
         "endpoints": ["crashes"],
         "date_range": {
           "type": "relative",
           "days_back": 7
         }
       }
     }'
   ```

5. **Documents Monitoring**

   ```bash
   # Check job status
   curl http://localhost:8000/jobs/summary

   # View execution history
   curl http://localhost:8000/jobs/{job_id}/executions

   # Check specific execution logs
   curl http://localhost:8000/jobs/{job_id}/executions/{execution_id}
   ```

### Expected Outcome
- Created daily job configuration
- Implemented relative date range (last 7 days)
- Scheduled for 2 AM daily execution
- Provided monitoring endpoints
- Set appropriate timeout and retry limits

---

## How to Invoke the Agent

The Data Engineer Agent can be invoked using the Claude Agent SDK or slash commands (specific syntax depends on your setup):

```bash
# Example invocation (syntax may vary)
/agent data-engineer "optimize the crash sync performance"

# Or describe the task in natural language
"Hey data engineer agent, can you help me debug why some crashes have invalid coordinates?"
```

## Best Practices for Working with the Agent

1. **Be specific**: Instead of "fix the database", say "optimize the query that finds crashes near schools"
2. **Provide context**: Include error messages, query patterns, or performance metrics
3. **Ask for options**: The agent can present multiple solutions with trade-offs
4. **Request explanations**: Ask "why" to understand the reasoning behind recommendations
5. **Follow patterns**: The agent knows existing code patterns - trust its guidance on consistency

## Additional Resources

- [Agent Configuration](../../.claude/agents/data-engineer.md) - Full agent definition and capabilities
- [Project Documentation](../../CLAUDE.md) - General project guide
- [Architecture Overview](../architecture/overview.md) - System architecture documentation
- [Service Documentation](../architecture/services.md) - Detailed service descriptions

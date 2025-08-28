# Shapefiles Directory

This directory is for Chicago geographic boundary shapefiles.

## How to Use

1. **Download shapefiles** from Chicago Data Portal or other sources
2. **Extract and place** the shapefile files (.shp, .shx, .dbf, .prj) in this directory
3. **Load into database** using one of these methods:

### Method 1: Command Line
```bash
# From project root
python src/spatial/simple_loader.py

# List loaded tables
python src/spatial/simple_loader.py --list

# Query a specific table
python src/spatial/simple_loader.py --query ward_boundaries
```

### Method 2: API Endpoint
```bash
# Start the API server first
uvicorn src.api.main:app --reload

# Load shapefiles via API
curl -X POST "http://localhost:8000/spatial/load"

# List loaded tables
curl "http://localhost:8000/spatial/tables"

# Query specific table
curl "http://localhost:8000/spatial/tables/ward_boundaries?limit=5"
```

## Recommended Chicago Data Sources

Download these from [Chicago Data Portal](https://data.cityofchicago.org):

- **Boundaries - Wards (2015-)** - Current ward boundaries
- **Boundaries - Community Areas** - 77 community areas
- **Boundaries - Police Beats** - Police beat boundaries  
- **Boundaries - Census Tracts** - Census tract boundaries

## File Requirements

Each shapefile needs these files:
- `.shp` - The shapefile (geometry)
- `.shx` - Shape index file
- `.dbf` - Attribute database file
- `.prj` - Projection file (coordinate system)

## What Happens When You Load

1. **Auto-detect** coordinate system and convert to WGS84 (EPSG:4326)
2. **Clean column names** (lowercase, underscores)
3. **Create PostGIS table** with spatial index
4. **Load all records** with geometry preserved

## Querying Spatial Data

Once loaded, you can query the spatial tables with SQL:

```sql
-- Find all wards
SELECT ward, ward_name FROM wards ORDER BY ward;

-- Find crashes in a specific ward (requires crash data loaded)
SELECT COUNT(*) FROM crashes c, wards w 
WHERE ST_Within(c.geometry, w.geometry) AND w.ward = 1;

-- Find nearest ward to a point
SELECT ward, ward_name, 
       ST_Distance(geometry, ST_Point(-87.6298, 41.8781)) as distance
FROM wards 
ORDER BY distance LIMIT 1;
```

The spatial loader automatically creates PostGIS geometry columns with spatial indexes for efficient querying.
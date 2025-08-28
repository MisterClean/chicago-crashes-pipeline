-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_geometry_gist ON crashes USING GIST (geometry);

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE chicago_crashes TO postgres;
"""Simple shapefile loader - just drop files in data/shapefiles/ and run this."""
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import text

from src.models.base import SessionLocal
from src.utils.logging import get_logger

try:
    import geopandas as gpd
except ImportError:  # pragma: no cover - optional dependency path
    gpd = None

logger = get_logger(__name__)


class SimpleShapefileLoader:
    """Simple loader that processes any shapefiles in the data directory."""
    
    def __init__(self):
        """Initialize with database connection."""
        self.session_factory = SessionLocal
        self.session = self.session_factory()
        self.engine = self.session.get_bind()
        
        # Ensure PostGIS is enabled
        try:
            self.session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            self.session.commit()
            logger.info("PostGIS extension enabled")
        except Exception as e:
            logger.warning("Could not enable PostGIS extension", error=str(e))
    
    def load_all_shapefiles(self, shapefiles_dir: str = "data/shapefiles") -> Dict[str, Any]:
        """Load all shapefiles found in the directory.
        
        Args:
            shapefiles_dir: Directory to scan for shapefiles
            
        Returns:
            Dictionary with results for each shapefile
        """
        shapefiles_path = Path(shapefiles_dir)
        
        if not shapefiles_path.exists():
            logger.error("Shapefiles directory not found", path=str(shapefiles_path))
            return {"error": f"Directory not found: {shapefiles_path}"}
        
        # Find all .shp files
        shapefiles = list(shapefiles_path.glob("**/*.shp"))
        
        if not shapefiles:
            logger.warning("No shapefiles found", path=str(shapefiles_path))
            return {"message": "No shapefiles found", "shapefiles_scanned": str(shapefiles_path)}
        
        results = {}
        
        for shapefile_path in shapefiles:
            filename = shapefile_path.stem  # filename without extension
            logger.info("Processing shapefile", file=filename, path=str(shapefile_path))
            
            try:
                if gpd is None:
                    raise RuntimeError(
                        "geopandas is required to load shapefiles. Install optional spatial dependencies."
                    )
                result = self._load_single_shapefile(shapefile_path, filename)
                results[filename] = result
            except Exception as e:
                logger.error("Failed to load shapefile", file=filename, error=str(e))
                results[filename] = {"error": str(e), "success": False}
        
        return results
    
    def _load_single_shapefile(self, shapefile_path: Path, table_name: str) -> Dict[str, Any]:
        """Load a single shapefile into PostGIS.
        
        Args:
            shapefile_path: Path to the shapefile
            table_name: Name for the database table
            
        Returns:
            Loading results
        """
        logger.info("Reading shapefile", file=str(shapefile_path))
        
        # Read shapefile with geopandas
        if gpd is None:
            raise RuntimeError(
                "geopandas is required to load shapefiles. Install optional spatial dependencies."
            )
        gdf = gpd.read_file(shapefile_path)
        
        # Convert to WGS84 if needed
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            logger.info("Converting CRS", from_crs=str(gdf.crs), to_crs="EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")
        
        # Clean column names (PostGIS/SQL friendly)
        gdf.columns = [col.lower().replace(' ', '_').replace('-', '_') for col in gdf.columns]
        
        # Load into PostGIS
        # if_exists='replace' will drop and recreate the table
        gdf.to_postgis(
            name=table_name,
            con=self.engine,
            if_exists='replace',
            index=False,
            chunksize=1000
        )
        
        logger.info("Shapefile loaded successfully", 
                   table=table_name, 
                   records=len(gdf), 
                   columns=list(gdf.columns))
        
        return {
            "success": True,
            "table_name": table_name,
            "records_loaded": len(gdf),
            "columns": list(gdf.columns),
            "geometry_type": str(gdf.geometry.geom_type.iloc[0]) if not gdf.empty else "Unknown",
            "crs": "EPSG:4326"
        }
    
    def list_loaded_tables(self) -> Dict[str, Any]:
        """List all spatial tables in the database."""
        try:
            # Query for tables with geometry columns
            query = text("""
                SELECT f_table_name, f_geometry_column, coord_dimension, srid, type
                FROM geometry_columns
                ORDER BY f_table_name
            """)
            
            result = self.session.execute(query)
            tables = []
            
            for row in result:
                # Get row count
                count_query = text(f"SELECT COUNT(*) FROM {row[0]}")
                count_result = self.session.execute(count_query)
                row_count = count_result.scalar()
                
                tables.append({
                    "table_name": row[0],
                    "geometry_column": row[1],
                    "dimensions": row[2],
                    "srid": row[3],
                    "geometry_type": row[4],
                    "record_count": row_count
                })
            
            return {"tables": tables, "total_tables": len(tables)}
            
        except Exception as e:
            logger.error("Error listing spatial tables", error=str(e))
            return {"error": str(e)}
    
    def query_table(self, table_name: str, limit: int = 10) -> Dict[str, Any]:
        """Query a spatial table to see sample data.
        
        Args:
            table_name: Name of the table to query
            limit: Number of records to return
            
        Returns:
            Sample records from the table
        """
        try:
            # Get sample data (excluding geometry for readability)
            query = text(f"""
                SELECT * FROM {table_name} 
                LIMIT {limit}
            """)
            
            result = self.session.execute(query)
            columns = list(result.keys())
            rows = []
            
            for row in result:
                row_dict = {}
                for i, value in enumerate(row):
                    column_name = columns[i]
                    # Skip geometry column or convert to text summary
                    if column_name.lower() in ['geometry', 'geom', 'the_geom']:
                        row_dict[column_name] = f"<geometry: {str(value)[:50]}...>" if value else None
                    else:
                        row_dict[column_name] = value
                rows.append(row_dict)
            
            return {
                "table_name": table_name,
                "columns": columns,
                "sample_data": rows,
                "record_count": len(rows)
            }
            
        except Exception as e:
            logger.error("Error querying table", table=table_name, error=str(e))
            return {"error": str(e)}
    
    def close(self):
        """Close database connection."""
        if self.session:
            self.session.close()


def main():
    """Main function for command line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Load shapefiles into PostGIS")
    parser.add_argument("--dir", default="data/shapefiles", help="Directory containing shapefiles")
    parser.add_argument("--list", action="store_true", help="List loaded spatial tables")
    parser.add_argument("--query", help="Query a specific table")
    parser.add_argument("--limit", type=int, default=10, help="Limit for query results")
    
    args = parser.parse_args()
    
    loader = SimpleShapefileLoader()
    
    try:
        if args.list:
            # List existing tables
            result = loader.list_loaded_tables()
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\\nFound {result['total_tables']} spatial tables:")
                print("-" * 60)
                for table in result["tables"]:
                    print(f"Table: {table['table_name']}")
                    print(f"  Records: {table['record_count']}")
                    print(f"  Geometry: {table['geometry_type']} (SRID: {table['srid']})")
                    print()
        
        elif args.query:
            # Query specific table
            result = loader.query_table(args.query, args.limit)
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\\nSample data from {result['table_name']}:")
                print("-" * 60)
                for row in result["sample_data"]:
                    print(row)
                    print()
        
        else:
            # Load shapefiles
            print(f"Scanning for shapefiles in: {args.dir}")
            results = loader.load_all_shapefiles(args.dir)
            
            print("\\nLoading Results:")
            print("=" * 50)
            
            success_count = 0
            for filename, result in results.items():
                if result.get("success"):
                    print(f"✓ {filename}")
                    print(f"  Table: {result['table_name']}")
                    print(f"  Records: {result['records_loaded']}")
                    print(f"  Geometry: {result['geometry_type']}")
                    success_count += 1
                else:
                    print(f"✗ {filename}: {result.get('error', 'Unknown error')}")
                print()
            
            print(f"Successfully loaded {success_count}/{len(results)} shapefiles")
    
    finally:
        loader.close()


if __name__ == "__main__":
    main()

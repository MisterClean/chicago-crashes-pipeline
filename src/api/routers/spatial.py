"""Spatial data endpoints."""
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
try:
    from spatial.simple_loader import SimpleShapefileLoader
except ModuleNotFoundError:  # pragma: no cover - optional dependency path
    SimpleShapefileLoader = None
from utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/spatial", tags=["spatial"])


@router.get("/tables")
async def list_spatial_tables():
    """List all loaded spatial tables."""
    if SimpleShapefileLoader is None:
        raise HTTPException(status_code=500, detail="Spatial loader dependencies are not installed")

    loader = SimpleShapefileLoader()
    try:
        result = loader.list_loaded_tables()
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    finally:
        loader.close()


@router.get("/tables/{table_name}")
async def get_table_info(
    table_name: str,
    limit: int = Query(10, description="Number of sample records to return", ge=1, le=100)
):
    """Get information about a specific spatial table."""
    if SimpleShapefileLoader is None:
        raise HTTPException(status_code=500, detail="Spatial loader dependencies are not installed")

    loader = SimpleShapefileLoader()
    try:
        result = loader.query_table(table_name, limit)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    finally:
        loader.close()


@router.post("/load")
async def load_shapefiles(
    directory: str = Query("data/shapefiles", description="Directory containing shapefiles")
):
    """Load all shapefiles from the specified directory."""
    if SimpleShapefileLoader is None:
        raise HTTPException(status_code=500, detail="Spatial loader dependencies are not installed")

    loader = SimpleShapefileLoader()
    try:
        result = loader.load_all_shapefiles(directory)
        
        # Count successes
        success_count = sum(1 for r in result.values() if isinstance(r, dict) and r.get("success"))
        total_count = len(result)
        
        return {
            "message": f"Processed {total_count} shapefiles, {success_count} successful",
            "results": result,
            "summary": {
                "total_files": total_count,
                "successful": success_count,
                "failed": total_count - success_count
            }
        }
    finally:
        loader.close()


@router.get("/")
async def spatial_info():
    """Get information about spatial capabilities."""
    return {
        "message": "Spatial data management endpoints",
        "usage": {
            "load_shapefiles": "POST /spatial/load?directory=data/shapefiles",
            "list_tables": "GET /spatial/tables",
            "query_table": "GET /spatial/tables/{table_name}?limit=10"
        },
        "instructions": [
            "1. Put your .shp files (with .shx, .dbf, .prj) in data/shapefiles/",
            "2. Call POST /spatial/load to load them into PostGIS",
            "3. Use GET /spatial/tables to see what was loaded",
            "4. Query specific tables with GET /spatial/tables/{table_name}"
        ]
    }

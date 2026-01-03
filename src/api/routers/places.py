"""API endpoints for place types and geographic boundaries."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.api.models import (
    PlaceGeometryResponse,
    PlaceItemResponse,
    PlaceTypeResponse,
)
from src.models.base import get_db
from src.models.spatial import (
    CommunityArea,
    HouseDistrict,
    PoliceBeat,
    SenateDistrict,
    SpatialLayer,
    SpatialLayerFeature,
    Ward,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/places", tags=["places"])


def _extract_feature_name(props: dict, feature_id: int) -> str:
    """Extract a human-readable name from feature properties.

    Tries common property name patterns used in GeoJSON files.
    """
    # Common name fields (case-insensitive search)
    name_fields = [
        "name", "NAME", "Name",
        "title", "TITLE", "Title",
        "label", "LABEL", "Label",
        "display_name", "DISPLAY_NAME",
    ]
    for field in name_fields:
        if field in props and props[field]:
            return str(props[field])

    # Common ID/number fields that can be used to construct a name
    # These are often used for political districts, wards, etc.
    id_patterns = [
        ("ward", "Ward {}"),
        ("WARD", "Ward {}"),
        ("district", "District {}"),
        ("DISTRICT", "District {}"),
        ("dist_num", "District {}"),
        ("DIST_NUM", "District {}"),
        ("beat_num", "Beat {}"),
        ("BEAT_NUM", "Beat {}"),
        ("community", "{}"),
        ("COMMUNITY", "{}"),
        ("area_numbe", "Area {}"),
        ("AREA_NUMBE", "Area {}"),
        ("objectid", "Feature {}"),
    ]
    for field, template in id_patterns:
        if field in props and props[field]:
            val = props[field]
            # Convert floats to ints if they're whole numbers
            if isinstance(val, float) and val.is_integer():
                val = int(val)
            return template.format(val)

    return f"Feature {feature_id}"


# Native place type configuration
# Maps type ID to (model class, pk column name, display format function)
NATIVE_PLACE_TYPES: dict[str, dict[str, Any]] = {
    "wards": {
        "model": Ward,
        "pk_column": "ward",
        "name": "Wards",
        "display_fn": lambda row: f"Ward {row.ward} - {row.alderman or 'Unknown'}"
        if row.alderman
        else f"Ward {row.ward}",
        "name_fn": lambda row: f"Ward {row.ward}",
    },
    "community_areas": {
        "model": CommunityArea,
        "pk_column": "area_numbe",
        "name": "Community Areas",
        "display_fn": lambda row: row.community or f"Area {row.area_numbe}",
        "name_fn": lambda row: row.community or f"Area {row.area_numbe}",
    },
    "house_districts": {
        "model": HouseDistrict,
        "pk_column": "district",
        "name": "IL House Districts",
        "display_fn": lambda row: f"District {row.district} - {row.rep_name}"
        if row.rep_name
        else f"District {row.district}",
        "name_fn": lambda row: f"District {row.district}",
    },
    "senate_districts": {
        "model": SenateDistrict,
        "pk_column": "district",
        "name": "IL Senate Districts",
        "display_fn": lambda row: f"District {row.district} - {row.senator_name}"
        if row.senator_name
        else f"District {row.district}",
        "name_fn": lambda row: f"District {row.district}",
    },
    "police_beats": {
        "model": PoliceBeat,
        "pk_column": "beat_num",
        "name": "Police Beats",
        "display_fn": lambda row: f"Beat {row.beat_num}",
        "name_fn": lambda row: f"Beat {row.beat_num}",
    },
}


@router.get("/types", response_model=list[PlaceTypeResponse])
async def list_place_types(db: Session = Depends(get_db)) -> list[PlaceTypeResponse]:
    """List all available place types (native boundaries and uploaded layers)."""
    place_types: list[PlaceTypeResponse] = []

    # Add native place types
    for type_id, config in NATIVE_PLACE_TYPES.items():
        model = config["model"]
        try:
            count = db.query(func.count()).select_from(model).scalar() or 0
            if count > 0:  # Only include types that have data
                place_types.append(
                    PlaceTypeResponse(
                        id=type_id,
                        name=config["name"],
                        source="native",
                        feature_count=count,
                    )
                )
        except Exception as e:
            logger.warning(f"Error counting {type_id}: {e}")
            # Table might not exist, skip it

    # Add user-uploaded spatial layers
    try:
        layers = db.query(SpatialLayer).filter(SpatialLayer.is_active == True).all()
        for layer in layers:
            place_types.append(
                PlaceTypeResponse(
                    id=f"layer:{layer.id}",
                    name=layer.name,
                    source="uploaded",
                    feature_count=layer.feature_count,
                )
            )
    except Exception as e:
        logger.warning(f"Error fetching spatial layers: {e}")

    return place_types


@router.get("/types/{place_type}/items", response_model=list[PlaceItemResponse])
async def list_place_items(
    place_type: str, db: Session = Depends(get_db)
) -> list[PlaceItemResponse]:
    """List all places within a place type."""
    items: list[PlaceItemResponse] = []

    # Check if it's a user-uploaded layer
    if place_type.startswith("layer:"):
        layer_id = int(place_type.split(":")[1])

        # Verify layer exists and is active before exposing features
        layer = (
            db.query(SpatialLayer)
            .filter(SpatialLayer.id == layer_id, SpatialLayer.is_active == True)
            .first()
        )
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Layer not found or inactive: {layer_id}",
            )

        features = (
            db.query(SpatialLayerFeature)
            .filter(SpatialLayerFeature.layer_id == layer_id)
            .all()
        )

        for feature in features:
            props = feature.properties or {}

            # Use configured label_field if available, otherwise fall back to heuristics
            if layer.label_field and layer.label_field in props:
                name = str(props[layer.label_field])
            else:
                name = _extract_feature_name(props, feature.id)

            items.append(
                PlaceItemResponse(
                    id=str(feature.id),
                    name=name,
                    display_name=name,
                )
            )
        return items

    # Handle native place types
    if place_type not in NATIVE_PLACE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown place type: {place_type}",
        )

    config = NATIVE_PLACE_TYPES[place_type]
    model = config["model"]
    pk_column = config["pk_column"]

    try:
        rows = db.query(model).order_by(getattr(model, pk_column)).all()
        for row in rows:
            pk_value = str(getattr(row, pk_column))
            items.append(
                PlaceItemResponse(
                    id=pk_value,
                    name=config["name_fn"](row),
                    display_name=config["display_fn"](row),
                )
            )
    except Exception as e:
        logger.error(f"Error fetching items for {place_type}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching places: {str(e)}",
        )

    return items


@router.get(
    "/types/{place_type}/items/{place_id}/geometry",
    response_model=PlaceGeometryResponse,
)
async def get_place_geometry(
    place_type: str, place_id: str, db: Session = Depends(get_db)
) -> PlaceGeometryResponse:
    """Get the GeoJSON geometry for a specific place."""

    # Check if it's a user-uploaded layer
    if place_type.startswith("layer:"):
        layer_id = int(place_type.split(":")[1])
        feature_id = int(place_id)

        # Verify layer exists and is active before exposing geometry
        layer = (
            db.query(SpatialLayer)
            .filter(SpatialLayer.id == layer_id, SpatialLayer.is_active == True)
            .first()
        )
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Layer not found or inactive: {layer_id}",
            )

        result = db.execute(
            text(
                """
                SELECT
                    slf.id,
                    slf.properties,
                    ST_AsGeoJSON(slf.geometry)::json as geometry
                FROM spatial_layer_features slf
                WHERE slf.layer_id = :layer_id AND slf.id = :feature_id
                """
            ),
            {"layer_id": layer_id, "feature_id": feature_id},
        ).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feature {place_id} not found in layer {layer_id}",
            )

        props = result.properties or {}

        # Use configured label_field if available, otherwise fall back to heuristics
        if layer.label_field and layer.label_field in props:
            name = str(props[layer.label_field])
        else:
            name = _extract_feature_name(props, result.id)

        return PlaceGeometryResponse(
            place_type=place_type,
            place_id=place_id,
            name=name,
            geometry=result.geometry,
        )

    # Handle native place types
    if place_type not in NATIVE_PLACE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown place type: {place_type}",
        )

    config = NATIVE_PLACE_TYPES[place_type]
    model = config["model"]
    pk_column = config["pk_column"]
    table_name = model.__tablename__

    # Query the geometry as GeoJSON
    result = db.execute(
        text(
            f"""
            SELECT
                {pk_column},
                ST_AsGeoJSON(geometry)::json as geometry
            FROM {table_name}
            WHERE {pk_column}::text = :place_id
            """
        ),
        {"place_id": place_id},
    ).fetchone()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Place {place_id} not found in {place_type}",
        )

    # Get the full row for display name
    row = (
        db.query(model)
        .filter(getattr(model, pk_column) == (int(place_id) if pk_column in ["ward", "area_numbe"] else place_id))
        .first()
    )

    name = config["name_fn"](row) if row else f"Place {place_id}"

    return PlaceGeometryResponse(
        place_type=place_type,
        place_id=place_id,
        name=name,
        geometry=result.geometry,
    )

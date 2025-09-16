"""API endpoints for managing GeoJSON spatial layers."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.models import (
    SpatialLayerDetailResponse,
    SpatialLayerResponse,
    SpatialLayerUpdateRequest,
)
from services.spatial_layer_service import SpatialLayerService

router = APIRouter(prefix="/spatial", tags=["spatial"])


def get_service() -> SpatialLayerService:
    return SpatialLayerService()


@router.get("/layers", response_model=List[SpatialLayerResponse])
async def list_layers(service: SpatialLayerService = Depends(get_service)):
    return service.list_layers()


@router.get("/layers/{layer_id}", response_model=SpatialLayerDetailResponse)
async def get_layer(layer_id: int, service: SpatialLayerService = Depends(get_service)):
    layer = service.get_layer(layer_id)
    if not layer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    return layer


@router.post("/layers", response_model=SpatialLayerResponse, status_code=status.HTTP_201_CREATED)
async def upload_layer(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    srid: int = Form(4326),
    service: SpatialLayerService = Depends(get_service),
):
    try:
        payload = await file.read()
        layer = service.create_layer_from_upload(
            name=name,
            upload_payload=payload,
            filename=file.filename,
            description=description,
            srid=srid,
        )
        return layer
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected errors returned as 500
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.patch("/layers/{layer_id}", response_model=SpatialLayerResponse)
async def update_layer(
    layer_id: int,
    payload: SpatialLayerUpdateRequest,
    service: SpatialLayerService = Depends(get_service),
):
    layer = service.update_layer(
        layer_id=layer_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    if not layer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    return layer


@router.post("/layers/{layer_id}/replace", response_model=SpatialLayerResponse)
async def replace_layer(
    layer_id: int,
    file: UploadFile = File(...),
    srid: Optional[int] = Form(None),
    service: SpatialLayerService = Depends(get_service),
):
    try:
        payload = await file.read()
        layer = service.replace_layer_from_upload(
            layer_id=layer_id,
            upload_payload=payload,
            filename=file.filename,
            srid=srid,
        )
        if not layer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
        return layer
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.delete("/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(layer_id: int, service: SpatialLayerService = Depends(get_service)):
    if not service.delete_layer(layer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    return None

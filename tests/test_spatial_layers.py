"""Tests for spatial layer management endpoints."""

import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from models.base import SessionLocal
from models.spatial import SpatialLayer, SpatialLayerFeature


@pytest.fixture
def client():
    """Provide a FastAPI test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_spatial_tables():
    """Ensure spatial layer tables are empty before and after each test."""
    session = SessionLocal()
    try:
        session.query(SpatialLayerFeature).delete()
        session.query(SpatialLayer).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = SessionLocal()
    try:
        session.query(SpatialLayerFeature).delete()
        session.query(SpatialLayer).delete()
        session.commit()
    finally:
        session.close()


def _count_layers() -> int:
    session = SessionLocal()
    try:
        return session.query(SpatialLayer).count()
    finally:
        session.close()


def _get_layer_by_name(name: str) -> SpatialLayer | None:
    session = SessionLocal()
    try:
        return session.query(SpatialLayer).filter(SpatialLayer.name == name).first()
    finally:
        session.close()


def _create_geojson_bytes() -> bytes:
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"district": "Test"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-87.7, 41.8],
                            [-87.6, 41.8],
                            [-87.6, 41.9],
                            [-87.7, 41.9],
                            [-87.7, 41.8],
                        ]
                    ],
                },
            }
        ],
    }
    return json.dumps(feature_collection).encode("utf-8")


def _build_shapefile_zip(tmpdir: Path) -> Path:
    geojson_path = tmpdir / "input.geojson"
    geojson_path.write_bytes(_create_geojson_bytes())

    shapefile_dir = tmpdir / "shp"
    shapefile_dir.mkdir()

    ogr_executable = shutil.which("ogr2ogr")
    if not ogr_executable:
        pytest.skip("ogr2ogr is required to build shapefile fixtures")

    command = [
        ogr_executable,
        "-f",
        "ESRI Shapefile",
        str(shapefile_dir / "layer.shp"),
        str(geojson_path),
    ]
    subprocess.run(command, check=True, capture_output=True)

    zip_path = tmpdir / "layer.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for component in shapefile_dir.glob("layer.*"):
            archive.write(component, arcname=component.name)

    return zip_path


def test_upload_geojson_layer(client):
    """GeoJSON upload should create a spatial layer and persist features."""
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {
        "name": "GeoJSON Layer",
        "description": "Uploaded via test",
        "srid": "4326",
    }

    response = client.post("/spatial/layers", files=files, data=data)

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "GeoJSON Layer"
    assert payload["feature_count"] == 1

    layer = _get_layer_by_name("GeoJSON Layer")
    assert layer is not None
    assert layer.feature_count == 1
    assert layer.original_filename == "layer.geojson"

    session = SessionLocal()
    try:
        feature_total = (
            session.query(SpatialLayerFeature)
            .filter(SpatialLayerFeature.layer_id == layer.id)
            .count()
        )
    finally:
        session.close()

    assert feature_total == 1


def test_upload_zipped_shapefile(client):
    """Uploading a zipped shapefile should convert and persist the features."""
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = _build_shapefile_zip(Path(temp_dir))
        with zip_path.open("rb") as fh:
            files = {
                "file": ("layer.zip", fh.read(), "application/zip"),
            }

        data = {
            "name": "Shapefile Layer",
            "description": "Converted from shapefile",
            "srid": "4326",
        }

        response = client.post("/spatial/layers", files=files, data=data)

    if response.status_code == 500 and "ogr2ogr" in response.text:
        pytest.skip("ogr2ogr is not available inside the test runtime")

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["name"] == "Shapefile Layer"
    assert payload["feature_count"] == 1
    assert payload["original_filename"] == "layer.zip"

    layer = _get_layer_by_name("Shapefile Layer")
    assert layer is not None
    assert layer.feature_count == 1

    session = SessionLocal()
    try:
        feature_total = (
            session.query(SpatialLayerFeature)
            .filter(SpatialLayerFeature.layer_id == layer.id)
            .count()
        )
    finally:
        session.close()

    assert feature_total == 1


def test_upload_invalid_file_returns_error(client):
    """Invalid uploads should surface a helpful validation error."""
    files = {
        "file": ("bad.geojson", b"not-json", "application/geo+json"),
    }
    data = {
        "name": "Broken Layer",
        "srid": "4326",
    }

    response = client.post("/spatial/layers", files=files, data=data)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid GeoJSON" in detail
    assert _count_layers() == 0

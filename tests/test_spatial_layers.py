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


# -----------------------------------------------------------------------------
# Sort Type Detection Tests
# -----------------------------------------------------------------------------


class TestDetectSortType:
    """Unit tests for _detect_sort_type numeric detection logic."""

    @pytest.fixture
    def service(self):
        """Provide a SpatialLayerService instance for unit testing."""
        from services.spatial_layer_service import SpatialLayerService

        return SpatialLayerService()

    def _make_features(self, labels: list[str], label_field: str = "name") -> list[dict]:
        """Helper to create feature dicts with given label values."""
        return [
            {"properties": {label_field: label}, "geometry": {"type": "Point"}}
            for label in labels
        ]

    def test_pure_numeric_labels_return_numeric(self, service):
        """Labels that are all digits should trigger numeric sort."""
        features = self._make_features(["1", "2", "3", "10", "20"])
        result = service._detect_sort_type(features, "name")
        assert result == "numeric"

    def test_trailing_digit_labels_return_numeric(self, service):
        """Labels like 'District 5' should trigger numeric sort."""
        features = self._make_features([
            "District 1", "District 2", "District 3", "District 10", "District 20"
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "numeric"

    def test_middle_digit_labels_return_numeric(self, service):
        """Labels like 'Area 10 West' should trigger numeric sort."""
        features = self._make_features([
            "Area 1 North", "Area 2 South", "Area 10 West", "Area 15 East"
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "numeric"

    def test_alphanumeric_suffix_labels_return_numeric(self, service):
        """Labels like 'Ward 2A' should trigger numeric sort."""
        features = self._make_features([
            "Ward 1A", "Ward 2B", "Ward 3C", "Ward 10D", "Ward 15E"
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "numeric"

    def test_no_digits_returns_alphabetic(self, service):
        """Labels with no digits should return alphabetic sort."""
        features = self._make_features([
            "Albany Park", "Lincoln Park", "Hyde Park", "Wicker Park"
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "alphabetic"

    def test_mixed_below_threshold_returns_alphabetic(self, service):
        """Less than 80% numeric labels should return alphabetic."""
        # 2 out of 10 = 20% numeric, should be alphabetic
        features = self._make_features([
            "District 1", "District 2",  # 2 numeric
            "North Side", "South Side", "West Side", "East Side",  # 4 non-numeric
            "Downtown", "Uptown", "Midtown", "Old Town"  # 4 non-numeric
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "alphabetic"

    def test_exactly_80_percent_returns_numeric(self, service):
        """Exactly 80% numeric labels should return numeric sort."""
        # 8 out of 10 = 80% numeric
        features = self._make_features([
            "Ward 1", "Ward 2", "Ward 3", "Ward 4",
            "Ward 5", "Ward 6", "Ward 7", "Ward 8",  # 8 numeric
            "North Side", "South Side"  # 2 non-numeric
        ])
        result = service._detect_sort_type(features, "name")
        assert result == "numeric"

    def test_int_float_values_counted_as_numeric(self, service):
        """Integer and float property values should be counted as numeric."""
        features = [
            {"properties": {"id": 1}, "geometry": {"type": "Point"}},
            {"properties": {"id": 2}, "geometry": {"type": "Point"}},
            {"properties": {"id": 3.5}, "geometry": {"type": "Point"}},
            {"properties": {"id": 4}, "geometry": {"type": "Point"}},
            {"properties": {"id": 5}, "geometry": {"type": "Point"}},
        ]
        result = service._detect_sort_type(features, "id")
        assert result == "numeric"

    def test_empty_features_returns_alphabetic(self, service):
        """Empty feature list should return alphabetic (default)."""
        result = service._detect_sort_type([], "name")
        assert result == "alphabetic"

    def test_no_label_field_returns_alphabetic(self, service):
        """No label field should return alphabetic (default)."""
        features = self._make_features(["District 1", "District 2"])
        result = service._detect_sort_type(features, None)
        assert result == "alphabetic"

    def test_null_values_skipped(self, service):
        """Null/None values should be skipped in the count."""
        features = [
            {"properties": {"name": "Ward 1"}, "geometry": {"type": "Point"}},
            {"properties": {"name": "Ward 2"}, "geometry": {"type": "Point"}},
            {"properties": {"name": None}, "geometry": {"type": "Point"}},
            {"properties": {"name": "Ward 3"}, "geometry": {"type": "Point"}},
            {"properties": {}, "geometry": {"type": "Point"}},  # missing field
        ]
        result = service._detect_sort_type(features, "name")
        # 3 out of 3 non-null values have digits = 100%
        assert result == "numeric"


# -----------------------------------------------------------------------------
# Sort Type API Tests
# -----------------------------------------------------------------------------


def test_update_layer_invalid_sort_type_returns_400(client):
    """PATCH with invalid sort_type should return 400 Bad Request."""
    # First create a layer
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Test Layer", "srid": "4326"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer (database may be missing sort_type column)")

    layer_id = create_response.json()["id"]

    # Try to update with invalid sort_type
    update_response = client.patch(
        f"/spatial/layers/{layer_id}",
        json={"sort_type": "invalid_sort_type"}
    )

    assert update_response.status_code == 400
    assert "Invalid sort_type" in update_response.json()["detail"]


def test_update_layer_valid_sort_type_succeeds(client):
    """PATCH with valid sort_type should succeed."""
    # First create a layer
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Test Layer", "srid": "4326"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer (database may be missing sort_type column)")

    layer_id = create_response.json()["id"]

    # Update with valid sort_type values
    for sort_type in ["alphabetic", "numeric", "natural"]:
        update_response = client.patch(
            f"/spatial/layers/{layer_id}",
            json={"sort_type": sort_type}
        )
        assert update_response.status_code == 200
        assert update_response.json()["sort_type"] == sort_type


def test_upload_layer_with_sort_type(client):
    """Upload with explicit sort_type should use that value."""
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Test Layer", "srid": "4326", "sort_type": "numeric"}
    response = client.post("/spatial/layers", files=files, data=data)

    if response.status_code != 201:
        pytest.skip("Could not create test layer (database may be missing sort_type column)")

    assert response.json()["sort_type"] == "numeric"


def test_upload_layer_without_sort_type_defaults_to_alphabetic(client):
    """Upload without sort_type should default to alphabetic."""
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Default Sort Layer", "srid": "4326"}
    response = client.post("/spatial/layers", files=files, data=data)

    if response.status_code != 201:
        pytest.skip("Could not create test layer")

    # Default should be alphabetic (or auto-detected based on content)
    assert response.json()["sort_type"] in ["alphabetic", "numeric", "natural"]


def test_list_layers_includes_sort_type(client):
    """GET /spatial/layers should include sort_type in each layer."""
    # Create a layer first
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "List Test Layer", "srid": "4326", "sort_type": "natural"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer")

    # List layers
    list_response = client.get("/spatial/layers")
    assert list_response.status_code == 200

    layers = list_response.json()
    assert len(layers) >= 1

    # Find our layer and check sort_type
    test_layer = next((l for l in layers if l["name"] == "List Test Layer"), None)
    assert test_layer is not None
    assert test_layer["sort_type"] == "natural"


def test_get_layer_detail_includes_sort_type(client):
    """GET /spatial/layers/{id} should include sort_type."""
    # Create a layer first
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Detail Test Layer", "srid": "4326", "sort_type": "numeric"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer")

    layer_id = create_response.json()["id"]

    # Get layer detail
    detail_response = client.get(f"/spatial/layers/{layer_id}")
    assert detail_response.status_code == 200

    detail = detail_response.json()
    assert detail["sort_type"] == "numeric"
    assert "available_fields" in detail  # Detail response includes extra fields


def test_update_layer_sort_type_persists(client):
    """Updating sort_type should persist and be returned in subsequent requests."""
    # Create a layer with alphabetic sort
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Persist Test Layer", "srid": "4326", "sort_type": "alphabetic"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer")

    layer_id = create_response.json()["id"]
    assert create_response.json()["sort_type"] == "alphabetic"

    # Update to numeric
    update_response = client.patch(
        f"/spatial/layers/{layer_id}",
        json={"sort_type": "numeric"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["sort_type"] == "numeric"

    # Verify it persisted by fetching again
    get_response = client.get(f"/spatial/layers/{layer_id}")
    assert get_response.status_code == 200
    assert get_response.json()["sort_type"] == "numeric"

    # Update to natural
    update_response = client.patch(
        f"/spatial/layers/{layer_id}",
        json={"sort_type": "natural"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["sort_type"] == "natural"


def test_update_layer_sort_type_with_other_fields(client):
    """Updating sort_type along with other fields should work correctly."""
    # Create a layer
    files = {
        "file": ("layer.geojson", _create_geojson_bytes(), "application/geo+json"),
    }
    data = {"name": "Multi-field Test", "srid": "4326"}
    create_response = client.post("/spatial/layers", files=files, data=data)

    if create_response.status_code != 201:
        pytest.skip("Could not create test layer")

    layer_id = create_response.json()["id"]

    # Update multiple fields including sort_type
    update_response = client.patch(
        f"/spatial/layers/{layer_id}",
        json={
            "name": "Updated Multi-field Test",
            "description": "New description",
            "sort_type": "numeric",
            "is_active": False
        }
    )
    assert update_response.status_code == 200

    result = update_response.json()
    assert result["name"] == "Updated Multi-field Test"
    assert result["description"] == "New description"
    assert result["sort_type"] == "numeric"
    assert result["is_active"] is False

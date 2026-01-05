"""Service for managing user-uploaded spatial layers."""

import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.base import SessionLocal
from src.models.spatial import SpatialLayer, SpatialLayerFeature
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _slugify(value: str) -> str:
    """Convert a string into a URL-safe slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-") or "layer"


class SpatialLayerService:
    """Business logic for CRUD operations on GeoJSON spatial layers."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_layers(self) -> list[dict[str, Any]]:
        """Return metadata for all spatial layers."""
        session = self.session_factory()
        try:
            layers = session.execute(select(SpatialLayer)).scalars().all()
            return [self._serialize_layer(layer) for layer in layers]
        finally:
            session.close()

    def get_layer(self, layer_id: int, sample_size: int = 10) -> dict[str, Any] | None:
        """Fetch a spatial layer with optional feature samples."""
        session = self.session_factory()
        try:
            layer = session.get(SpatialLayer, layer_id)
            if not layer:
                return None

            sample_query = (
                select(SpatialLayerFeature)
                .where(SpatialLayerFeature.layer_id == layer_id)
                .limit(sample_size)
            )
            samples = session.execute(sample_query).scalars().all()
            feature_samples = [
                {
                    "id": feature.id,
                    "properties": feature.properties,
                }
                for feature in samples
            ]

            # Extract all unique field names from sampled features
            available_fields: set[str] = set()
            for sample in samples:
                if sample.properties:
                    available_fields.update(sample.properties.keys())

            data = self._serialize_layer(layer)
            data["feature_samples"] = feature_samples
            data["available_fields"] = sorted(available_fields)
            return data
        finally:
            session.close()

    def create_layer(
        self,
        name: str,
        geojson_payload: bytes,
        description: str | None = None,
        srid: int = 4326,
        original_filename: str | None = None,
        label_field: str | None = None,
        sort_type: str | None = None,
    ) -> dict[str, Any]:
        """Store a new GeoJSON layer and its features."""
        session = self.session_factory()
        try:
            geojson = self._parse_geojson(geojson_payload)
            features, geometry_type = self._extract_features(geojson)

            slug = self._ensure_unique_slug(session, _slugify(name))

            # Auto-detect sort_type if not provided
            if sort_type is None:
                sort_type = self._detect_sort_type(features, label_field)

            layer = SpatialLayer(
                name=name,
                slug=slug,
                description=description,
                geometry_type=geometry_type,
                srid=srid,
                original_filename=original_filename,
                feature_count=0,
                label_field=label_field,
                sort_type=sort_type,
            )
            session.add(layer)
            session.flush()  # assign ID

            self._persist_features(session, layer.id, features, srid)

            layer.feature_count = len(features)
            session.commit()
            logger.info(
                "Created spatial layer",
                layer_id=layer.id,
                name=name,
                feature_count=layer.feature_count,
                sort_type=sort_type,
            )
            return self._serialize_layer(layer)
        except Exception as exc:
            session.rollback()
            logger.error("Failed to create spatial layer", error=str(exc))
            raise
        finally:
            session.close()

    def create_layer_from_upload(
        self,
        name: str,
        upload_payload: bytes,
        filename: str | None,
        description: str | None = None,
        srid: int = 4326,
        label_field: str | None = None,
        sort_type: str | None = None,
    ) -> dict[str, Any]:
        """Create a spatial layer from an uploaded file, detecting the format."""
        try:
            (
                processed_payload,
                target_srid,
                original_label,
            ) = self._prepare_upload_payload(
                upload_payload,
                filename,
                srid,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error("Failed to prepare uploaded layer", error=str(exc))
            raise

        return self.create_layer(
            name=name,
            geojson_payload=processed_payload,
            description=description,
            srid=target_srid,
            original_filename=original_label,
            label_field=label_field,
            sort_type=sort_type,
        )

    def preview_fields(
        self,
        upload_payload: bytes,
        filename: str | None,
        srid: int = 4326,
    ) -> dict[str, Any]:
        """Preview available property fields from an uploaded spatial file.

        Returns field names with sample values to help admin choose the label field.
        """
        try:
            (
                processed_payload,
                _target_srid,
                _original_label,
            ) = self._prepare_upload_payload(
                upload_payload,
                filename,
                srid,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error("Failed to prepare upload for preview", error=str(exc))
            raise

        geojson = self._parse_geojson(processed_payload)
        features = geojson.get("features", [])

        # Collect all unique field names and sample values across features
        all_fields: dict[str, list[Any]] = {}
        for feature in features[:100]:  # Sample first 100 features
            props = feature.get("properties", {})
            for key, value in props.items():
                if key not in all_fields:
                    all_fields[key] = []
                if len(all_fields[key]) < 3 and value is not None:
                    # Only add unique sample values
                    if value not in all_fields[key]:
                        all_fields[key].append(value)

        # Determine suggested field using heuristics
        suggested_field = self._detect_label_field(list(all_fields.keys()))

        return {
            "fields": [
                {
                    "name": name,
                    "sample_values": samples,
                    "suggested": name == suggested_field,
                }
                for name, samples in all_fields.items()
            ],
            "recommended_field": suggested_field,
        }

    def _detect_label_field(self, field_names: list[str]) -> str | None:
        """Apply heuristics to find the most likely label field."""
        if not field_names:
            return None

        # Priority 1: Exact matches for common name fields
        name_fields = ["name", "NAME", "Name", "title", "TITLE", "label", "LABEL"]
        for field in name_fields:
            if field in field_names:
                return field

        # Priority 2: Fields containing "name" or "nm" (case-insensitive)
        for field in field_names:
            lower = field.lower()
            if "name" in lower or "_nm" in lower or lower.endswith("nm"):
                return field

        # Priority 3: Description fields
        for field in field_names:
            if "desc" in field.lower():
                return field

        # Priority 4: District/ward identifiers
        for field in field_names:
            lower = field.lower()
            if any(kw in lower for kw in ["district", "ward", "community"]):
                return field

        return None

    def _detect_sort_type(self, features: list[dict[str, Any]], label_field: str | None) -> str:
        """Auto-detect appropriate sort type based on label field values.

        Returns:
            'numeric' if label field contains primarily numeric values
            'alphabetic' otherwise (default)
        """
        if not label_field or not features:
            return 'alphabetic'

        # Sample up to 100 features to determine sort type
        sample_size = min(100, len(features))
        numeric_count = 0
        total_count = 0

        for feature in features[:sample_size]:
            props = feature.get("properties", {})
            value = props.get(label_field)

            if value is None:
                continue

            total_count += 1

            # Check if the value is numeric or can be parsed as numeric
            try:
                # Try to convert to float (handles both int and float)
                if isinstance(value, (int, float)):
                    numeric_count += 1
                elif isinstance(value, str):
                    # Strip whitespace and try parsing
                    stripped = value.strip()
                    # Handle cases like "District 5" by extracting numbers
                    if stripped.isdigit():
                        numeric_count += 1
                    else:
                        # Try extracting trailing number (e.g., "District 5" -> "5")
                        import re
                        match = re.search(r'\d+$', stripped)
                        if match:
                            numeric_count += 1
            except (ValueError, TypeError):
                pass

        # If 80% or more of sampled values are numeric, use numeric sorting
        if total_count > 0 and (numeric_count / total_count) >= 0.8:
            return 'numeric'

        return 'alphabetic'

    def update_layer(
        self,
        layer_id: int,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        label_field: str | None = None,
        sort_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Update spatial layer metadata."""
        session = self.session_factory()
        try:
            layer = session.get(SpatialLayer, layer_id)
            if not layer:
                return None

            if name and name != layer.name:
                layer.name = name
                layer.slug = self._ensure_unique_slug(session, _slugify(name), layer_id)
            if description is not None:
                layer.description = description
            if is_active is not None:
                layer.is_active = is_active
            if label_field is not None:
                # Allow setting to empty string to clear, or to a field name
                layer.label_field = label_field if label_field else None
            if sort_type is not None:
                # Validate sort_type
                if sort_type not in ['alphabetic', 'numeric', 'natural']:
                    raise ValueError(f"Invalid sort_type: {sort_type}. Must be 'alphabetic', 'numeric', or 'natural'")
                layer.sort_type = sort_type

            session.commit()
            return self._serialize_layer(layer)
        except Exception as exc:
            session.rollback()
            logger.error(
                "Failed to update spatial layer", layer_id=layer_id, error=str(exc)
            )
            raise
        finally:
            session.close()

    def replace_layer_data(
        self,
        layer_id: int,
        geojson_payload: bytes,
        srid: int | None = None,
        original_filename: str | None = None,
    ) -> dict[str, Any] | None:
        """Replace the features for an existing layer."""
        session = self.session_factory()
        try:
            layer = session.get(SpatialLayer, layer_id)
            if not layer:
                return None

            geojson = self._parse_geojson(geojson_payload)
            features, geometry_type = self._extract_features(geojson)

            target_srid = srid or layer.srid

            # Clear existing features
            session.query(SpatialLayerFeature).filter_by(layer_id=layer_id).delete(
                synchronize_session=False
            )

            self._persist_features(session, layer_id, features, target_srid)

            layer.feature_count = len(features)
            layer.geometry_type = geometry_type
            layer.srid = target_srid
            if original_filename:
                layer.original_filename = original_filename

            session.commit()
            return self._serialize_layer(layer)
        except Exception as exc:
            session.rollback()
            logger.error(
                "Failed to replace layer data", layer_id=layer_id, error=str(exc)
            )
            raise
        finally:
            session.close()

    def replace_layer_from_upload(
        self,
        layer_id: int,
        upload_payload: bytes,
        filename: str | None,
        srid: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            (
                processed_payload,
                target_srid,
                original_label,
            ) = self._prepare_upload_payload(
                upload_payload,
                filename,
                srid or 4326,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to prepare uploaded layer for replace",
                layer_id=layer_id,
                error=str(exc),
            )
            raise

        return self.replace_layer_data(
            layer_id=layer_id,
            geojson_payload=processed_payload,
            srid=target_srid,
            original_filename=original_label,
        )

    def delete_layer(self, layer_id: int) -> bool:
        """Remove a layer and its features."""
        session = self.session_factory()
        try:
            layer = session.get(SpatialLayer, layer_id)
            if not layer:
                return False
            session.delete(layer)
            session.commit()
            logger.info("Deleted spatial layer", layer_id=layer_id)
            return True
        except Exception as exc:
            session.rollback()
            logger.error(
                "Failed to delete spatial layer", layer_id=layer_id, error=str(exc)
            )
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _parse_geojson(self, payload: bytes) -> dict[str, Any]:
        try:
            parsed = (
                json.loads(payload.decode("utf-8"))
                if isinstance(payload, (bytes, bytearray))
                else json.loads(payload)
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid GeoJSON payload: {exc}") from exc

        if parsed.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON file must be a FeatureCollection")
        return parsed

    def _extract_features(
        self, geojson: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        features = geojson.get("features") or []
        if not features:
            raise ValueError("GeoJSON FeatureCollection contains no features")

        geometry_type = "Geometry"
        cleaned: list[dict[str, Any]] = []
        for feature in features:
            geometry = feature.get("geometry")
            if not geometry:
                continue
            if geometry_type == "Geometry":
                geometry_type = (geometry.get("type") or "Geometry").upper()
            cleaned.append(
                {
                    "geometry": geometry,
                    "properties": feature.get("properties") or {},
                }
            )

        if not cleaned:
            raise ValueError("No valid features with geometry found in GeoJSON file")

        return cleaned, geometry_type

    def _persist_features(
        self, session: Session, layer_id: int, features: list[dict[str, Any]], srid: int
    ) -> None:
        inserted = 0
        for feature in features:
            geom_json = json.dumps(feature["geometry"])
            db_feature = SpatialLayerFeature(
                layer_id=layer_id,
                properties=feature["properties"],
            )
            db_feature.geometry = func.ST_SetSRID(
                func.ST_GeomFromGeoJSON(geom_json), srid
            )
            session.add(db_feature)
            inserted += 1

            if inserted % 500 == 0:
                session.flush()

        logger.info(
            "Persisted spatial features", layer_id=layer_id, feature_count=inserted
        )

    def _ensure_unique_slug(
        self, session: Session, base_slug: str, current_layer_id: int | None = None
    ) -> str:
        slug = base_slug
        counter = 1
        while True:
            query = select(SpatialLayer).where(SpatialLayer.slug == slug)
            if current_layer_id:
                query = query.where(SpatialLayer.id != current_layer_id)
            exists = session.execute(query).scalar_one_or_none()
            if not exists:
                return slug
            counter += 1
            slug = f"{base_slug}-{counter}"

    def _serialize_layer(self, layer: SpatialLayer) -> dict[str, Any]:
        return {
            "id": layer.id,
            "name": layer.name,
            "slug": layer.slug,
            "description": layer.description,
            "geometry_type": layer.geometry_type,
            "srid": layer.srid,
            "feature_count": layer.feature_count,
            "original_filename": layer.original_filename,
            "is_active": layer.is_active,
            "label_field": layer.label_field,
            "sort_type": layer.sort_type,
            "created_at": layer.created_at,
            "updated_at": layer.updated_at,
        }

    def _prepare_upload_payload(
        self,
        upload_payload: bytes,
        filename: str | None,
        srid: int,
    ) -> tuple[bytes, int, str | None]:
        """Normalize uploaded spatial data to GeoJSON bytes and target SRID."""
        if not upload_payload:
            raise ValueError("Uploaded file is empty")

        safe_name = filename or "upload"
        extension = Path(safe_name).suffix.lower()

        logger.debug(
            "Preparing spatial upload",
            filename=safe_name,
            extension=extension,
            srid=srid,
            srid_type=type(srid).__name__,
        )

        if extension in {".geojson", ".json"}:
            return upload_payload, srid, safe_name

        if extension == ".zip" or zipfile.is_zipfile(io.BytesIO(upload_payload)):
            geojson_payload = self._convert_shapefile_zip(upload_payload, srid)
            logger.debug(
                "Converted shapefile zip to GeoJSON",
                filename=safe_name,
                srid=srid,
                size=len(geojson_payload),
            )
            return geojson_payload, srid, safe_name

        raise ValueError(
            "Unsupported file type. Provide GeoJSON or a zipped ESRI Shapefile (.zip)."
        )

    def _convert_shapefile_zip(self, payload: bytes, srid: int) -> bytes:
        """Convert a zipped ESRI Shapefile into GeoJSON bytes using ogr2ogr."""
        if shutil.which("ogr2ogr") is None:
            raise ValueError(
                "ogr2ogr command is required to process shapefiles but "
                "was not found in PATH"
            )

        if not zipfile.is_zipfile(io.BytesIO(payload)):
            raise ValueError("Uploaded file is not a valid ZIP archive")

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "upload.zip"
            with open(zip_path, "wb") as tmp_zip:
                tmp_zip.write(payload)

            with zipfile.ZipFile(zip_path) as archive:
                shapefile_members = [
                    name for name in archive.namelist() if name.lower().endswith(".shp")
                ]
                if not shapefile_members:
                    raise ValueError("ZIP archive does not contain a .shp file")
                if len(shapefile_members) > 1:
                    raise ValueError("ZIP archive must contain exactly one shapefile")

                shapefile_name = shapefile_members[0]
                base_stem = Path(shapefile_name).stem
                required_exts = [".shp", ".shx", ".dbf", ".prj"]

                for ext in required_exts:
                    required_member = next(
                        (
                            name
                            for name in archive.namelist()
                            if Path(name).stem == base_stem
                            and name.lower().endswith(ext)
                        ),
                        None,
                    )
                    if not required_member:
                        raise ValueError(
                            f"Shapefile archive is missing required component: {ext}"
                        )

                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ValueError("ZIP archive contains unsafe paths")
                    target_path = Path(temp_dir) / member_path
                    if member.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            shapefile_path = Path(temp_dir) / shapefile_name
            geojson_path = Path(temp_dir) / "converted.geojson"

            command = [
                "ogr2ogr",
                "-t_srs",
                f"EPSG:{srid}",
                "-f",
                "GeoJSON",
                str(geojson_path),
                str(shapefile_path),
            ]

            try:
                subprocess.run(command, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                stderr = (
                    exc.stderr.decode("utf-8", errors="ignore")
                    if exc.stderr
                    else "Unknown error"
                )
                raise ValueError(
                    f"Failed to convert shapefile to GeoJSON: {stderr.strip()}"
                ) from exc

            if not geojson_path.exists():
                raise ValueError("Failed to generate GeoJSON from shapefile archive")

            return geojson_path.read_bytes()

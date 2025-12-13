"""Service for managing user-uploaded spatial layers."""
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    def list_layers(self) -> List[Dict[str, Any]]:
        """Return metadata for all spatial layers."""
        session = self.session_factory()
        try:
            layers = session.execute(select(SpatialLayer)).scalars().all()
            return [self._serialize_layer(layer) for layer in layers]
        finally:
            session.close()

    def get_layer(
        self, layer_id: int, sample_size: int = 10
    ) -> Optional[Dict[str, Any]]:
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
            data = self._serialize_layer(layer)
            data["feature_samples"] = feature_samples
            return data
        finally:
            session.close()

    def create_layer(
        self,
        name: str,
        geojson_payload: bytes,
        description: Optional[str] = None,
        srid: int = 4326,
        original_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a new GeoJSON layer and its features."""
        session = self.session_factory()
        try:
            geojson = self._parse_geojson(geojson_payload)
            features, geometry_type = self._extract_features(geojson)

            slug = self._ensure_unique_slug(session, _slugify(name))

            layer = SpatialLayer(
                name=name,
                slug=slug,
                description=description,
                geometry_type=geometry_type,
                srid=srid,
                original_filename=original_filename,
                feature_count=0,
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
        filename: Optional[str],
        description: Optional[str] = None,
        srid: int = 4326,
    ) -> Dict[str, Any]:
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
        )

    def update_layer(
        self,
        layer_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
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
        srid: Optional[int] = None,
        original_filename: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
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
        filename: Optional[str],
        srid: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
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
    def _parse_geojson(self, payload: bytes) -> Dict[str, Any]:
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
        self, geojson: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], str]:
        features = geojson.get("features") or []
        if not features:
            raise ValueError("GeoJSON FeatureCollection contains no features")

        geometry_type = "Geometry"
        cleaned: List[Dict[str, Any]] = []
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
        self, session: Session, layer_id: int, features: List[Dict[str, Any]], srid: int
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
        self, session: Session, base_slug: str, current_layer_id: Optional[int] = None
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

    def _serialize_layer(self, layer: SpatialLayer) -> Dict[str, Any]:
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
            "created_at": layer.created_at,
            "updated_at": layer.updated_at,
        }

    def _prepare_upload_payload(
        self,
        upload_payload: bytes,
        filename: Optional[str],
        srid: int,
    ) -> Tuple[bytes, int, Optional[str]]:
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

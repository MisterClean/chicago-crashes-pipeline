"""Database service for streaming upserts into the pipeline datastore."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional, Sequence

from geoalchemy2.elements import WKTElement
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from src.models.base import SessionLocal, get_db
from src.models.crashes import (Crash, CrashPerson, CrashVehicle,
                                VisionZeroFatality)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Provide high-level helpers for persisting sanitized records."""

    def __init__(self) -> None:
        self.session_factory = SessionLocal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def upsert_crash_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
        return self._upsert_records(Crash, records, self._prepare_crash_record)

    def upsert_person_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self._upsert_records(CrashPerson, records, self._prepare_person_record)

    def upsert_vehicle_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self._upsert_records(CrashVehicle, records, self._prepare_vehicle_record)

    def upsert_fatality_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self._upsert_records(
            VisionZeroFatality, records, self._prepare_fatality_record
        )

    def get_record_counts(self) -> Dict[str, int]:
        """Return simple table counts for status endpoints."""
        session = self.session_factory()
        try:
            return {
                "crashes": session.query(Crash).count(),
                "crash_people": session.query(CrashPerson).count(),
                "crash_vehicles": session.query(CrashVehicle).count(),
                "vision_zero_fatalities": session.query(VisionZeroFatality).count(),
            }
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.error("Failed to collect record counts", error=str(exc))
            return {}
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Core upsert implementation
    # ------------------------------------------------------------------
    def _upsert_records(
        self,
        model: type,
        records: Sequence[Dict[str, Any]],
        prepare: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> Dict[str, int]:
        inserted = updated = skipped = 0
        session = self.session_factory()

        try:
            for raw_record in records:
                prepared = prepare(raw_record)
                if not prepared:
                    skipped += 1
                    continue

                pk = self._extract_primary_key(model, prepared)
                if pk is None:
                    skipped += 1
                    continue

                existing = session.get(model, pk)
                if existing:
                    self._assign_columns(existing, prepared)
                    updated += 1
                else:
                    session.add(model(**prepared))
                    inserted += 1

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover - error path
            session.rollback()
            logger.error(
                "Database upsert failed",
                model=model.__tablename__,
                error=str(exc),
            )
            raise
        finally:
            session.close()

        logger.info(
            "Upsert batch complete",
            table=model.__tablename__,
            inserted=inserted,
            updated=updated,
            skipped=skipped,
        )

        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    # ------------------------------------------------------------------
    # Record preparation helpers
    # ------------------------------------------------------------------
    def _prepare_crash_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        filtered = self._filter_columns(Crash, record)
        crash_id = filtered.get("crash_record_id")
        crash_date = filtered.get("crash_date")
        if not crash_id or crash_date is None:
            return None

        latitude = filtered.get("latitude")
        longitude = filtered.get("longitude")
        if latitude is not None and longitude is not None:
            geometry = self._create_geometry(latitude, longitude)
        else:
            geometry = None

        filtered["geometry"] = geometry
        return filtered

    def _prepare_person_record(
        self, record: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        filtered = self._filter_columns(CrashPerson, record)
        if not filtered.get("crash_record_id") or not filtered.get("person_id"):
            return None
        return filtered

    def _prepare_vehicle_record(
        self, record: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        filtered = self._filter_columns(CrashVehicle, record)
        if not filtered.get("crash_unit_id"):
            return None
        return filtered

    def _prepare_fatality_record(
        self, record: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        filtered = self._filter_columns(VisionZeroFatality, record)
        if not filtered.get("person_id"):
            return None

        latitude = filtered.get("latitude")
        longitude = filtered.get("longitude")
        if latitude is not None and longitude is not None:
            filtered["geometry"] = self._create_geometry(latitude, longitude)
        else:
            filtered["geometry"] = None

        return filtered

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _filter_columns(self, model: type, data: Dict[str, Any]) -> Dict[str, Any]:
        column_names = {column.name for column in model.__table__.columns}
        return {name: data.get(name) for name in column_names if name in data}

    def _extract_primary_key(self, model: type, data: Dict[str, Any]) -> Optional[Any]:
        mapper = inspect(model)
        key_components: list[Any] = []
        for column in mapper.primary_key:
            value = data.get(column.name)
            if value is None:
                return None
            key_components.append(value)

        if not key_components:
            return None
        if len(key_components) == 1:
            return key_components[0]
        return tuple(key_components)

    @staticmethod
    def _assign_columns(instance: Any, values: Dict[str, Any]) -> None:
        for key, value in values.items():
            setattr(instance, key, value)

    @staticmethod
    def _create_geometry(latitude: Any, longitude: Any) -> Optional[WKTElement]:
        lat = DatabaseService._parse_float(latitude)
        lon = DatabaseService._parse_float(longitude)
        if lat is None or lon is None:
            return None
        return WKTElement(f"POINT({lon} {lat})", srid=4326)

    # ------------------------------------------------------------------
    # Legacy parsing helpers (retained for compatibility)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", ""))
            except ValueError:
                pass
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None or value == "":
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Backwards-compatibility shims (legacy method names used in tests)
    # ------------------------------------------------------------------
    def insert_crash_records(
        self, records: Sequence[Dict[str, Any]], batch_size: int = 1000
    ) -> Dict[str, int]:
        del batch_size  # preserved for signature compatibility
        return self.upsert_crash_records(records)

    def insert_person_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self.upsert_person_records(records)

    def insert_vehicle_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self.upsert_vehicle_records(records)

    def insert_fatality_records(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        return self.upsert_fatality_records(records)


__all__ = ["DatabaseService", "get_db"]

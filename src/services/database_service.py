"""Database service for streaming upserts into the pipeline datastore."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from src.models.base import SessionLocal, get_db
from src.models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Provide high-level helpers for persisting sanitized records."""

    def __init__(self) -> None:
        self.session_factory = SessionLocal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def upsert_crash_records(self, records: Sequence[dict[str, Any]]) -> dict[str, int]:
        return self._upsert_records(Crash, records, self._prepare_crash_record)

    def upsert_person_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self._upsert_records(
            CrashPerson,
            records,
            self._prepare_person_record,
            parent_key="crash_record_id",
        )

    def upsert_vehicle_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self._upsert_records(
            CrashVehicle,
            records,
            self._prepare_vehicle_record,
            parent_key="crash_record_id",
        )

    def upsert_fatality_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self._upsert_records(
            VisionZeroFatality, records, self._prepare_fatality_record
        )

    def get_record_counts(self) -> dict[str, int]:
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

    def backfill_person_crash_dates(
        self, batch_size: int = 50000, max_batches: int | None = None
    ) -> dict[str, int]:
        """Backfill missing crash_people.crash_date values from parent crashes."""
        session = self.session_factory()
        total_updated = 0
        batches = 0

        try:
            initial_missing = session.execute(
                text("SELECT COUNT(*) FROM crash_people WHERE crash_date IS NULL")
            ).scalar_one()

            while True:
                if max_batches is not None and batches >= max_batches:
                    break

                updated = len(
                    session.execute(
                        text(
                            """
                            WITH batch AS (
                                SELECT cp.ctid, c.crash_date
                                FROM crash_people cp
                                JOIN crashes c ON c.crash_record_id = cp.crash_record_id
                                WHERE cp.crash_date IS NULL
                                LIMIT :batch_size
                            )
                            UPDATE crash_people cp
                            SET crash_date = batch.crash_date
                            FROM batch
                            WHERE cp.ctid = batch.ctid
                            RETURNING 1
                            """
                        ),
                        {"batch_size": batch_size},
                    ).fetchall()
                )
                session.commit()

                if updated == 0:
                    break

                batches += 1
                total_updated += updated
                logger.info(
                    "Backfilled crash_people.crash_date batch",
                    updated=updated,
                    total_updated=total_updated,
                    batch_number=batches,
                )

            remaining_missing = session.execute(
                text("SELECT COUNT(*) FROM crash_people WHERE crash_date IS NULL")
            ).scalar_one()

            logger.info(
                "Completed crash_people.crash_date backfill",
                initial_missing=initial_missing,
                updated=total_updated,
                remaining_missing=remaining_missing,
                batches=batches,
            )
            return {
                "initial_missing": initial_missing,
                "updated": total_updated,
                "remaining_missing": remaining_missing,
                "batches": batches,
            }
        except SQLAlchemyError as exc:  # pragma: no cover - error path
            session.rollback()
            logger.error("Failed to backfill crash_people.crash_date", error=str(exc))
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Core upsert implementation
    # ------------------------------------------------------------------
    def _upsert_records(
        self,
        model: type,
        records: Sequence[dict[str, Any]],
        prepare: Callable[[dict[str, Any]], dict[str, Any] | None],
        parent_key: str | None = None,
    ) -> dict[str, int]:
        inserted = updated = skipped = 0
        session = self.session_factory()

        try:
            prepared_records: list[tuple[dict[str, Any], Any]] = []
            for raw_record in records:
                prepared = prepare(raw_record)
                if not prepared:
                    skipped += 1
                    continue

                pk = self._extract_primary_key(model, prepared)
                if pk is None:
                    skipped += 1
                    continue

                prepared_records.append((prepared, pk))

            if parent_key:
                prepared_records, orphaned = self._filter_orphaned_child_records(
                    session,
                    model,
                    prepared_records,
                    parent_key,
                )
                skipped += orphaned

            for prepared, pk in prepared_records:
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

    @staticmethod
    def _filter_orphaned_child_records(
        session: Any,
        model: type,
        prepared_records: list[tuple[dict[str, Any], Any]],
        parent_key: str,
    ) -> tuple[list[tuple[dict[str, Any], Any]], int]:
        """Exclude child records whose referenced crash is not stored locally."""
        parent_ids = {
            prepared[parent_key]
            for prepared, _ in prepared_records
            if prepared.get(parent_key)
        }
        if not parent_ids:
            return prepared_records, 0

        existing_parent_ids = set(
            session.scalars(
                select(Crash.crash_record_id).where(
                    Crash.crash_record_id.in_(parent_ids)
                )
            ).all()
        )
        orphaned_parent_ids = parent_ids - existing_parent_ids
        if not orphaned_parent_ids:
            return prepared_records, 0

        valid_records = [
            (prepared, pk)
            for prepared, pk in prepared_records
            if prepared.get(parent_key) in existing_parent_ids
        ]
        orphaned_count = len(prepared_records) - len(valid_records)

        logger.warning(
            "Skipped child records with missing crash parents",
            model=model.__tablename__,
            orphaned_records=orphaned_count,
            orphaned_crash_ids=len(orphaned_parent_ids),
            sample_crash_ids=sorted(orphaned_parent_ids)[:10],
        )
        return valid_records, orphaned_count

    # ------------------------------------------------------------------
    # Record preparation helpers
    # ------------------------------------------------------------------
    def _prepare_crash_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
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

    def _prepare_person_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        filtered = self._filter_columns(CrashPerson, record)
        if not filtered.get("crash_record_id") or not filtered.get("person_id"):
            return None
        return filtered

    def _prepare_vehicle_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        filtered = self._filter_columns(CrashVehicle, record)
        if not filtered.get("crash_unit_id"):
            return None
        return filtered

    def _prepare_fatality_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
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
    def _filter_columns(self, model: type, data: dict[str, Any]) -> dict[str, Any]:
        column_names = {column.name for column in model.__table__.columns}
        return {name: data.get(name) for name in column_names if name in data}

    def _extract_primary_key(self, model: type, data: dict[str, Any]) -> Any | None:
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
    def _assign_columns(instance: Any, values: dict[str, Any]) -> None:
        for key, value in values.items():
            setattr(instance, key, value)

    @staticmethod
    def _create_geometry(latitude: Any, longitude: Any) -> WKTElement | None:
        lat = DatabaseService._parse_float(latitude)
        lon = DatabaseService._parse_float(longitude)
        if lat is None or lon is None:
            return None
        return WKTElement(f"POINT({lon} {lat})", srid=4326)

    # ------------------------------------------------------------------
    # Legacy parsing helpers (retained for compatibility)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
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
    def _parse_int(value: Any, default: int | None = None) -> int | None:
        if value is None or value == "":
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_float(value: Any) -> float | None:
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
        self, records: Sequence[dict[str, Any]], batch_size: int = 1000
    ) -> dict[str, int]:
        del batch_size  # preserved for signature compatibility
        return self.upsert_crash_records(records)

    def insert_person_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self.upsert_person_records(records)

    def insert_vehicle_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self.upsert_vehicle_records(records)

    def insert_fatality_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self.upsert_fatality_records(records)


__all__ = ["DatabaseService", "get_db"]

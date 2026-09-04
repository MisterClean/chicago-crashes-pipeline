"""Database service for streaming upserts into the pipeline datastore."""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from time import perf_counter
from typing import Any
from uuid import uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from src.models.base import SessionLocal, get_db
from src.models.crashes import (Crash, CrashPerson, CrashVehicle,
                                VisionZeroFatality)
from src.models.ingestion import IngestionCheckpoint
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
        return self._upsert_records(CrashPerson, records, self._prepare_person_record)

    def upsert_vehicle_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, int]:
        return self._upsert_records(CrashVehicle, records, self._prepare_vehicle_record)

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
    ) -> dict[str, int]:
        inserted = updated = skipped = 0
        session = self.session_factory()

        try:
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                loader = StagedPublication(session)
                loader.stage(model, records, prepare)
                result = loader.publish()[model.__tablename__]
                session.commit()
                return {key: result[key] for key in ("inserted", "updated", "skipped")}
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

    @contextmanager
    def publication(self):
        """Serialize ingestion across workers and publish all endpoints atomically.

        A failed download, schema check, COPY, or merge rolls everything back.
        The advisory lock is transaction-scoped and automatically released after
        a crash or rollback. Callers retry a busy publisher as a job, not in-web.
        """
        session = self.session_factory()
        try:
            acquired = session.execute(
                text("SELECT pg_try_advisory_xact_lock(784203615)")
            ).scalar_one()
            if not acquired:
                raise RuntimeError(
                    "Another ingestion publication is running; retry this job"
                )
            yield StagedPublication(session)
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

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


class StagedPublication:
    """COPY bounded batches, then perform set-based, changed-only merges."""

    def __init__(self, session) -> None:
        self.session = session
        self.tables: dict[str, dict[str, Any]] = {}

    def checkpoint(self, endpoint: str) -> datetime | None:
        checkpoint = self.session.get(IngestionCheckpoint, endpoint)
        return checkpoint.source_updated_before if checkpoint is not None else None

    def set_checkpoint(self, endpoint: str, upper_bound: datetime) -> None:
        checkpoint = self.session.get(IngestionCheckpoint, endpoint)
        if checkpoint is None:
            self.session.add(
                IngestionCheckpoint(
                    endpoint=endpoint, source_updated_before=upper_bound
                )
            )
        else:
            checkpoint.source_updated_before = upper_bound

    def stage_endpoint(
        self, endpoint: str, records: Sequence[dict[str, Any]], service: DatabaseService
    ) -> None:
        models = {
            "crashes": (Crash, service._prepare_crash_record),
            "people": (CrashPerson, service._prepare_person_record),
            "vehicles": (CrashVehicle, service._prepare_vehicle_record),
            "fatalities": (VisionZeroFatality, service._prepare_fatality_record),
        }
        model, prepare = models[endpoint]
        self.stage(model, records, prepare)

    def stage(
        self, model: type, records: Sequence[dict[str, Any]], prepare: Callable
    ) -> None:
        if not records:
            return
        quote = self.session.bind.dialect.identifier_preparer.quote
        prepared = [prepare(record) for record in records]
        if any(record is None for record in prepared):
            raise ValueError(
                f"Invalid required fields in {model.__tablename__}; snapshot not published"
            )
        columns = sorted(prepared[0])
        if any(sorted(record) != columns for record in prepared):
            raise ValueError("Inconsistent canonical fields in ingestion batch")
        target = model.__tablename__
        if target not in self.tables:
            stage = "ingest_" + uuid4().hex
            selection = ", ".join(map(quote, columns))
            self.session.execute(
                text(
                    f"CREATE TEMP TABLE {quote(stage)} ON COMMIT DROP AS "
                    f"SELECT {selection} FROM {quote(target)} WITH NO DATA"
                )
            )
            self.tables[target] = {
                "stage": stage,
                "model": model,
                "columns": columns,
                "rows": 0,
            }
        info = self.tables[target]
        if info["columns"] != columns:
            raise ValueError("Canonical schema changed between ingestion batches")
        buffer = StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        for record in prepared:
            values = []
            for column in columns:
                value = record[column]
                if isinstance(value, WKTElement):
                    value = f"SRID={value.srid};{value.data}"
                if value == "\\N":
                    raise ValueError("Reserved COPY null marker in source data")
                values.append("\\N" if value is None else value)
            writer.writerow(values)
        buffer.seek(0)
        column_sql = ", ".join(map(quote, columns))
        sql = f"COPY {quote(info['stage'])} ({column_sql}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
        connection = self.session.connection().connection.driver_connection
        with connection.cursor() as cursor:
            cursor.copy_expert(sql, buffer)
        info["rows"] += len(prepared)

    def publish(self) -> dict[str, dict[str, Any]]:
        """Validate unique source keys before changing any destination rows."""
        quote = self.session.bind.dialect.identifier_preparer.quote
        for info in self.tables.values():
            keys = [column.name for column in info["model"].__table__.primary_key]
            key_sql = ", ".join(map(quote, keys))
            self.session.execute(
                text(f"CREATE UNIQUE INDEX ON {quote(info['stage'])} ({key_sql})")
            )
        results = {}
        # Parent crashes must merge before related people and vehicles regardless
        # of caller selection order; foreign keys stay enabled throughout.
        order = {
            "crashes": 0,
            "crash_people": 1,
            "crash_vehicles": 2,
            "vision_zero_fatalities": 3,
        }
        for target, info in sorted(
            self.tables.items(), key=lambda item: order[item[0]]
        ):
            merge_started = perf_counter()
            stage = quote(info["stage"])
            destination = quote(target)
            keys = [column.name for column in info["model"].__table__.primary_key]
            columns = info["columns"]
            join = " AND ".join(f"d.{quote(key)} = s.{quote(key)}" for key in keys)
            existing = self.session.execute(
                text(f"SELECT count(*) FROM {stage} s JOIN {destination} d ON {join}")
            ).scalar_one()
            mutable = [column for column in columns if column not in keys]
            changed = " OR ".join(
                f"d.{quote(column)} IS DISTINCT FROM EXCLUDED.{quote(column)}"
                for column in mutable
            )
            updates = ", ".join(
                f"{quote(column)} = EXCLUDED.{quote(column)}" for column in mutable
            )
            if "updated_at" in info["model"].__table__.columns:
                updates += ", updated_at = CURRENT_TIMESTAMP"
            names = ", ".join(map(quote, columns))
            selection = names
            for timestamp_column in ("created_at", "updated_at"):
                if (
                    timestamp_column in info["model"].__table__.columns
                    and timestamp_column not in columns
                ):
                    names += ", " + quote(timestamp_column)
                    selection += ", CURRENT_TIMESTAMP"
            conflict = ", ".join(map(quote, keys))
            result = self.session.execute(
                text(
                    f"INSERT INTO {destination} AS d ({names}) SELECT {selection} FROM {stage} "
                    f"ON CONFLICT ({conflict}) DO UPDATE SET {updates} WHERE {changed}"
                )
            )
            inserted = info["rows"] - existing
            updated = result.rowcount - inserted
            results[target] = {
                "inserted": inserted,
                "updated": updated,
                "skipped": existing - updated,
                "unchanged": existing - updated,
                "rejected": 0,
                "merge_seconds": perf_counter() - merge_started,
            }
        return results


__all__ = ["DatabaseService", "get_db"]

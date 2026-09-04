"""Database service for streaming upserts into the pipeline datastore."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from uuid import uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from src.models.base import SessionLocal, get_db
from src.models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
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
        if not records:
            return {"inserted": 0, "updated": 0, "skipped": 0}
        inserted = updated = skipped = 0
        session = self.session_factory()
        loader = None

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
            if loader is not None:
                loader.close()
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
        loader = None
        try:
            acquired = session.execute(
                text("SELECT pg_try_advisory_xact_lock(784203615)")
            ).scalar_one()
            if not acquired:
                raise RuntimeError(
                    "Another ingestion publication is running; retry this job"
                )
            loader = StagedPublication(session)
            yield loader
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            if loader is not None:
                loader.close()
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
    """Validate on worker disk, then merge bounded PostgreSQL batches atomically.

    Only the rebuildable SQLite spool contains the complete incoming snapshot.
    PostgreSQL temporary tables are created during publication and reused for at
    most ``batch_size`` rows. Destination writes still share the caller's single
    transaction; this bounds staging, not destination MVCC/WAL disk requirements.
    """

    def __init__(self, session, batch_size: int = 5000) -> None:
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("Publication batch size must be between 1 and 5000")
        self.session = session
        self.batch_size = batch_size
        configured_limit = os.getenv("INGESTION_MAX_CHANGED_ROWS")
        self.max_changed_rows = int(configured_limit) if configured_limit else None
        if self.max_changed_rows is not None and self.max_changed_rows < 0:
            raise ValueError("INGESTION_MAX_CHANGED_ROWS must be nonnegative")
        self.preflight_counts: dict[str, dict[str, int]] = {}
        self.tables: dict[str, dict[str, Any]] = {}
        configured_directory = os.getenv("INGESTION_SPOOL_DIR")
        if configured_directory:
            Path(configured_directory).mkdir(parents=True, exist_ok=True)
        self._directory = TemporaryDirectory(
            prefix="ingestion-spool-", dir=configured_directory
        )
        self.spool_path = Path(self._directory.name) / "validated.sqlite"
        self.spool = sqlite3.connect(self.spool_path)
        self.spool.execute(
            "CREATE TABLE source_rows (dataset TEXT NOT NULL, source_key TEXT NOT NULL, "
            "csv_record TEXT NOT NULL, PRIMARY KEY (dataset, source_key)) WITHOUT ROWID"
        )
        self._published = False
        self._failed = False

    def close(self) -> None:
        self.spool.close()
        self._directory.cleanup()

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
        if self._published or self._failed:
            raise RuntimeError("Cannot stage into a finished or invalid publication")
        if not records:
            return
        prepared = [prepare(record) for record in records]
        if any(record is None for record in prepared):
            self._failed = True
            raise ValueError(
                f"Invalid required fields in {model.__tablename__}; snapshot not published"
            )
        columns = sorted(prepared[0])
        if any(sorted(record) != columns for record in prepared):
            self._failed = True
            raise ValueError("Inconsistent canonical fields in ingestion batch")
        target = model.__tablename__
        if target not in self.tables:
            self.tables[target] = {
                "stage": "ingest_" + uuid4().hex,
                "model": model,
                "columns": columns,
                "rows": 0,
            }
        info = self.tables[target]
        if info["columns"] != columns:
            self._failed = True
            raise ValueError("Canonical schema changed between ingestion batches")
        keys = [column.name for column in model.__table__.primary_key]

        def spool_rows():
            buffer = StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            for record in prepared:
                key_values = [record.get(key) for key in keys]
                if any(value is None for value in key_values):
                    raise ValueError(f"Missing source primary key for {target}")
                # These models use text primary keys. Match COPY/PostgreSQL's
                # text identity even if a direct caller supplies a numeric ID.
                key_values = [str(value) for value in key_values]
                values = []
                for column in columns:
                    value = record[column]
                    if isinstance(value, WKTElement):
                        value = f"SRID={value.srid};{value.data}"
                    if value == "\\N":
                        raise ValueError("Reserved COPY null marker in source data")
                    values.append("\\N" if value is None else value)
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow(values)
                yield target, json.dumps(
                    key_values, separators=(",", ":")
                ), buffer.getvalue()

        try:
            self.spool.executemany(
                "INSERT INTO source_rows VALUES (?, ?, ?)", spool_rows()
            )
            self.spool.commit()
        except sqlite3.IntegrityError as error:
            self._failed = True
            self.spool.rollback()
            raise ValueError(
                f"Duplicate source primary key in {target}; publication rejected"
            ) from error
        except BaseException:
            self._failed = True
            self.spool.rollback()
            raise
        info["rows"] += len(prepared)

    def publish(self) -> dict[str, dict[str, Any]]:
        """Replay validated rows through bounded temp tables without committing."""
        if self._published or self._failed:
            raise RuntimeError("Cannot publish a finished or invalid source spool")
        self._published = True
        quote = self.session.bind.dialect.identifier_preparer.quote
        if self.max_changed_rows is not None:
            self._preflight()
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
            keys = [column.name for column in info["model"].__table__.primary_key]
            self._ensure_temp_table(target, info)
            key_names = ", ".join(map(quote, keys))
            stats = {
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "unchanged": 0,
                "rejected": 0,
            }
            cursor = self.spool.execute(
                "SELECT csv_record FROM source_rows WHERE dataset = ? ORDER BY source_key",
                (target,),
            )
            while rows := cursor.fetchmany(self.batch_size):
                self._copy_batch(info, rows)
                # Fresh statistics keep joins focused on the small source batch.
                self.session.execute(text(f"ANALYZE {stage} ({key_names})"))
                batch_stats = self._merge_batch(target, info, len(rows))
                for key in stats:
                    stats[key] += batch_stats[key]
                # Created in this transaction: PostgreSQL truncates in-place,
                # without retaining old temp relfilenodes until final commit.
                self.session.execute(text(f"TRUNCATE {stage}"))
            stats["merge_seconds"] = perf_counter() - merge_started
            results[target] = stats
        return results

    def _ensure_temp_table(self, target: str, info: dict[str, Any]) -> None:
        if info.get("temp_created"):
            return
        quote = self.session.bind.dialect.identifier_preparer.quote
        stage = quote(info["stage"])
        columns = ", ".join(map(quote, info["columns"]))
        keys = ", ".join(
            quote(column.name) for column in info["model"].__table__.primary_key
        )
        self.session.execute(
            text(
                f"CREATE TEMP TABLE {stage} ON COMMIT DROP AS SELECT {columns} FROM {quote(target)} WITH NO DATA"
            )
        )
        self.session.execute(text(f"CREATE UNIQUE INDEX ON {stage} ({keys})"))
        info["temp_created"] = True

    def _preflight(self) -> None:
        """Count target mutations before any writes, bounded by the same temp size.

        This is a conservative operational row guard, not a byte/free-space
        guarantee: row widths, indexes, WAL, and MVCC versions still vary.
        """
        quote = self.session.bind.dialect.identifier_preparer.quote
        for target, info in self.tables.items():
            self._ensure_temp_table(target, info)
            stage = quote(info["stage"])
            keys = ", ".join(
                quote(column.name) for column in info["model"].__table__.primary_key
            )
            totals = {"inserted": 0, "updated": 0}
            cursor = self.spool.execute(
                "SELECT csv_record FROM source_rows WHERE dataset = ? ORDER BY source_key",
                (target,),
            )
            while rows := cursor.fetchmany(self.batch_size):
                self._copy_batch(info, rows)
                self.session.execute(text(f"ANALYZE {stage} ({keys})"))
                counts = self._batch_change_counts(target, info)
                for key in totals:
                    totals[key] += counts[key]
                self.session.execute(text(f"TRUNCATE {stage}"))
            self.preflight_counts[target] = totals
        changed = sum(sum(counts.values()) for counts in self.preflight_counts.values())
        logger.info(
            "Ingestion change preflight",
            changed_rows=changed,
            max_changed_rows=self.max_changed_rows,
            tables=self.preflight_counts,
        )
        if changed > self.max_changed_rows:
            raise ValueError(
                f"Publication would change {changed} rows, exceeding INGESTION_MAX_CHANGED_ROWS={self.max_changed_rows}; "
                f"no destination rows written. Counts: {json.dumps(self.preflight_counts, sort_keys=True)}. "
                "Review database disk headroom and source changes before raising this operational guard."
            )

    def _batch_change_counts(self, target: str, info: dict[str, Any]) -> dict[str, int]:
        quote = self.session.bind.dialect.identifier_preparer.quote
        keys = [column.name for column in info["model"].__table__.primary_key]
        join = " AND ".join(f"existing.{quote(key)} = s.{quote(key)}" for key in keys)
        source_changed = " OR ".join(
            f"existing.{quote(column)} IS DISTINCT FROM s.{quote(column)}"
            for column in info["columns"]
            if column not in keys
        )
        absent = f"existing.{quote(keys[0])} IS NULL"
        row = self.session.execute(
            text(
                f"SELECT count(*) FILTER (WHERE {absent}) AS inserted, "
                f"count(*) FILTER (WHERE NOT ({absent}) AND ({source_changed})) AS updated "
                f"FROM {quote(info['stage'])} s LEFT JOIN {quote(target)} existing ON {join}"
            )
        ).one()
        return {"inserted": row.inserted, "updated": row.updated}

    def _copy_batch(self, info: dict[str, Any], rows: list[tuple[str]]) -> None:
        quote = self.session.bind.dialect.identifier_preparer.quote
        buffer = StringIO("".join(row[0] for row in rows))
        columns = ", ".join(map(quote, info["columns"]))
        sql = f"COPY {quote(info['stage'])} ({columns}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
        connection = self.session.connection().connection.driver_connection
        with connection.cursor() as cursor:
            cursor.copy_expert(sql, buffer)

    def _merge_batch(
        self, target: str, info: dict[str, Any], row_count: int
    ) -> dict[str, int]:
        quote = self.session.bind.dialect.identifier_preparer.quote
        stage = quote(info["stage"])
        destination = quote(target)
        keys = [column.name for column in info["model"].__table__.primary_key]
        columns = info["columns"]
        join = " AND ".join(f"existing.{quote(key)} = s.{quote(key)}" for key in keys)
        existing_count = self.session.execute(
            text(
                f"SELECT count(*) FROM {stage} s JOIN {destination} existing ON {join}"
            )
        ).scalar_one()
        mutable = [column for column in columns if column not in keys]
        changed = " OR ".join(
            f"d.{quote(column)} IS DISTINCT FROM EXCLUDED.{quote(column)}"
            for column in mutable
        )
        source_changed = " OR ".join(
            f"existing.{quote(column)} IS DISTINCT FROM s.{quote(column)}"
            for column in mutable
        )
        updates = ", ".join(
            f"{quote(column)} = EXCLUDED.{quote(column)}" for column in mutable
        )
        if "updated_at" in info["model"].__table__.columns:
            updates += ", updated_at = CURRENT_TIMESTAMP"
        names = ", ".join(map(quote, columns))
        selection = ", ".join(f"s.{quote(column)}" for column in columns)
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
                f"INSERT INTO {destination} AS d ({names}) SELECT {selection} FROM {stage} s "
                f"LEFT JOIN {destination} existing ON {join} "
                f"WHERE existing.{quote(keys[0])} IS NULL OR ({source_changed}) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {updates} WHERE {changed}"
            )
        )
        inserted = row_count - existing_count
        updated = result.rowcount - inserted
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": existing_count - updated,
            "unchanged": existing_count - updated,
            "rejected": 0,
        }


__all__ = ["DatabaseService", "get_db"]

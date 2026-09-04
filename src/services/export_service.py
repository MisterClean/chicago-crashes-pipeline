"""Bounded exports from one PostgreSQL snapshot, executed by a leased worker."""

from __future__ import annotations

import csv
import hashlib
import json
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from src.api.routers.dashboard import (
    LocationReportExportRequest,
    _build_date_filter,
    _build_location_report_filters,
)
from src.models.base import SessionLocal, engine
from src.models.exports import ExportJob
from src.services.object_storage import ExportSettings, ObjectStorage
from src.utils.logging import get_logger

logger = get_logger(__name__)
SCHEMA_VERSION = 1
QUEUE_LOCK = 764029182

# Versioned public columns. Changes require an explicit schema-version decision.
EXPORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "crashes": (
        "crash_record_id",
        "crash_date",
        "crash_date_est_i",
        "posted_speed_limit",
        "traffic_control_device",
        "device_condition",
        "weather_condition",
        "lighting_condition",
        "street_no",
        "street_direction",
        "street_name",
        "sec_contributory_cause",
        "street_direction_2",
        "street_name_2",
        "crash_type",
        "crash_record_id_original",
        "crash_date_original",
        "latitude",
        "longitude",
        "geometry",
        "beat_of_occurrence",
        "photos_taken_i",
        "statements_taken_i",
        "damage",
        "date_police_notified",
        "prim_contributory_cause",
        "work_zone_i",
        "work_zone_type",
        "workers_present_i",
        "injuries_total",
        "injuries_fatal",
        "injuries_incapacitating",
        "injuries_non_incapacitating",
        "injuries_reported_not_evident",
        "injuries_no_indication",
        "injuries_unknown",
        "hit_and_run_i",
        "dooring_i",
        "intersection_related_i",
        "not_right_of_way_i",
        "lane_cnt",
        "alignment",
        "roadway_surface_cond",
        "road_defect",
        "report_type",
        "most_severe_injury",
    ),
    "people": (
        "crash_record_id",
        "person_id",
        "crash_date",
        "vehicle_id",
        "person_type",
        "age",
        "sex",
        "safety_equipment",
        "airbag_deployed",
        "ejection",
        "injury_classification",
        "hospital",
        "ems_agency",
        "ems_unit",
        "area_00_i",
        "area_01_i",
        "area_02_i",
        "area_03_i",
        "area_04_i",
        "area_05_i",
        "area_06_i",
        "area_07_i",
        "area_08_i",
        "area_09_i",
        "area_10_i",
        "area_11_i",
        "area_12_i",
        "drivers_license_state",
        "drivers_license_class",
        "driver_action",
        "driver_vision",
        "physical_condition",
        "pedpedal_action",
        "pedpedal_visibility",
        "pedpedal_location",
        "bac_result",
        "bac_result_value",
        "cell_phone_use",
    ),
    "vehicles": (
        "crash_unit_id",
        "crash_record_id",
        "unit_no",
        "crash_date",
        "unit_type",
        "num_passengers",
        "vehicle_id",
        "cmv_id",
        "make",
        "model",
        "lic_plate_state",
        "vehicle_year",
        "vehicle_defect",
        "vehicle_type",
        "vehicle_use",
        "travel_direction",
        "maneuver",
        "towed_i",
        "fire_i",
        "hazmat_placard_i",
        "hazmat_name",
        "hazmat_present_i",
        "occupant_cnt",
        "first_contact_point",
    ),
    "vision_zero": (
        "person_id",
        "rd_no",
        "crash_date",
        "crash_location",
        "victim",
        "crash_circumstances",
        "longitude",
        "latitude",
        "geometry",
        "geocoded_column",
    ),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def submit_export(
    db: Session, request: LocationReportExportRequest, settings: ExportSettings
) -> ExportJob:
    if not request.datasets or set(request.datasets) - EXPORT_COLUMNS.keys():
        raise ValueError("Select crashes, people, vehicles, or vision_zero")
    if (
        request.start_date
        and request.end_date
        and request.start_date > request.end_date
    ):
        raise ValueError("Start date must not exceed end date")
    # Resolve boundaries at submission so a later layer edit cannot change the job.
    _, _, area = _build_location_report_filters(request, db)
    payload = request.model_dump(mode="json", exclude_none=True)
    if request.place_type is not None and request.place_id is not None:
        # The helper returns the resolved query area as a GeoJSON feature.
        payload["resolved_area"] = area
    payload["datasets"] = sorted(set(request.datasets))
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK})
    pending = db.scalar(
        select(func.count())
        .select_from(ExportJob)
        .where(ExportJob.status.in_(["queued", "running"]))
    )
    if pending >= settings.max_pending:
        raise ValueError("Export queue is full; try again later")
    now = utcnow()
    job = ExportJob(
        id=str(uuid.uuid4()),
        status="queued",
        request=payload,
        request_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(hours=settings.retention_hours),
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def claim_export(db: Session, settings: ExportSettings) -> ExportJob | None:
    now = utcnow()
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK})
    db.execute(
        update(ExportJob)
        .where(
            ExportJob.status.in_(["queued", "running"]),
            or_(
                ExportJob.expires_at <= now,
                (ExportJob.attempts >= settings.max_attempts)
                & (ExportJob.lease_until <= now),
            ),
        )
        .values(status="failed", error="Export expired or exhausted retries")
    )
    active = db.scalar(
        select(func.count())
        .select_from(ExportJob)
        .where(ExportJob.status == "running", ExportJob.lease_until > now)
    )
    if active >= settings.max_concurrent:
        db.commit()
        return None
    job = db.scalar(
        select(ExportJob)
        .where(
            ExportJob.expires_at > now,
            ExportJob.attempts < settings.max_attempts,
            or_(
                ExportJob.status == "queued",
                (ExportJob.status == "running") & (ExportJob.lease_until <= now),
            ),
        )
        .order_by(ExportJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is not None:
        job.status = "running"
        job.lease_token = str(uuid.uuid4())
        job.lease_until = now + timedelta(seconds=settings.lease_seconds)
        job.attempts += 1
        job.error = None
    db.commit()
    if job is not None:
        db.refresh(job)
        db.expunge(job)
    return job


def _renew(job: ExportJob, settings: ExportSettings) -> bool:
    with SessionLocal() as db:
        changed = db.execute(
            update(ExportJob)
            .where(
                ExportJob.id == job.id,
                ExportJob.status == "running",
                ExportJob.lease_token == job.lease_token,
                ExportJob.lease_until > utcnow(),
                ExportJob.expires_at > utcnow(),
            )
            .values(lease_until=utcnow() + timedelta(seconds=settings.lease_seconds))
        )
        db.commit()
        return changed.rowcount == 1


def _select_columns(dataset: str, alias: str) -> str:
    return ", ".join(
        f"ST_AsText({alias}.geometry) AS geometry"
        if name == "geometry"
        else f"{alias}.{name}"
        for name in EXPORT_COLUMNS[dataset]
    )


def _dataset_query(dataset: str, spatial: str, date_filter: str) -> str:
    if dataset == "vision_zero":
        return (
            f"SELECT {_select_columns(dataset, 'vz')} FROM vision_zero_fatalities vz "
            f"WHERE vz.geometry IS NOT NULL AND {spatial} {date_filter}"
        )
    tables = {
        "crashes": ("crashes", "c"),
        "people": ("crash_people", "cp"),
        "vehicles": ("crash_vehicles", "cv"),
    }
    table, alias = tables[dataset]
    return (
        f"SELECT {_select_columns(dataset, alias)} FROM {table} {alias} "
        f"JOIN export_selected_crashes s ON s.crash_record_id={alias}.crash_record_id"
    )


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_csv(
    connection: Any,
    query: str,
    params: dict,
    path: Path,
    settings: ExportSettings,
    check: Callable[[], None],
) -> dict:
    count = 0
    with connection.execution_options(yield_per=2000).execute(
        text(query), params
    ) as rows:
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(rows.keys())
            for row in rows:
                count += 1
                if count > settings.max_rows:
                    raise ValueError("Export exceeds configured row limit")
                writer.writerow(row)
                if count % 2000 == 0:
                    check()
                    if output.tell() > settings.max_bytes:
                        raise ValueError("Export exceeds configured byte limit")
    check()
    if path.stat().st_size > settings.max_bytes:
        raise ValueError("Export exceeds configured byte limit")
    return {"rows": count, "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def generate_export(
    job: ExportJob, directory: Path, settings: ExportSettings, check: Callable[[], None]
) -> tuple[Path, dict]:
    request = LocationReportExportRequest.model_validate(job.request)
    manifest: dict = {
        "schema_version": SCHEMA_VERSION,
        "filters": job.request,
        "generated_at": utcnow().isoformat(),
        "datasets": {},
        "data_version": None,
        "consistency": "PostgreSQL repeatable-read snapshot",
    }
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": str(settings.timeout_seconds * 1000)},
            )
            manifest["snapshot"] = conn.scalar(
                text("SELECT txid_current_snapshot()::text")
            )
            if (
                request.place_type is not None
                and request.place_id is not None
                and "resolved_area" in job.request
            ):
                area = job.request["resolved_area"]
                geometry = area.get("geometry", area)
                spatial = (
                    "ST_Contains(ST_SetSRID(ST_GeomFromGeoJSON(:area),4326), "
                    "{geometry_column})"
                )
                params = {"area": json.dumps(geometry)}
            else:
                spatial, params, _ = _build_location_report_filters(request, conn)
            date_filter = _build_date_filter(request, params, "c.crash_date")
            selected_query = (
                "SELECT c.crash_record_id FROM crashes c WHERE "
                "c.geometry IS NOT NULL AND "
                + spatial.format(geometry_column="c.geometry")
                + date_filter
            )
            # A materialized CTE avoids DDL in the read-only snapshot.
            for dataset in request.datasets:
                check()
                vz_date = _build_date_filter(request, params, "vz.crash_date")
                query = _dataset_query(
                    dataset, spatial.format(geometry_column="vz.geometry"), vz_date
                )
                if dataset != "vision_zero":
                    query = (
                        "WITH export_selected_crashes AS MATERIALIZED ("
                        + selected_query
                        + ") "
                        + query
                    )
                path = directory / f"{dataset}.csv"
                manifest["datasets"][dataset] = _write_csv(
                    conn, query, params, path, settings, check
                )
                # Reset execution option for subsequent control statements.
                conn.execution_options(stream_results=False, yield_per=None)
                if (
                    sum(item["bytes"] for item in manifest["datasets"].values())
                    > settings.max_bytes
                ):
                    raise ValueError("Export exceeds configured total byte limit")
    if len(request.datasets) == 1:
        return directory / f"{request.datasets[0]}.csv", manifest
    artifact = directory / "location-report.zip"
    with zipfile.ZipFile(
        artifact, "w", zipfile.ZIP_DEFLATED, compresslevel=1
    ) as archive:
        for dataset in request.datasets:
            check()
            archive.write(directory / f"{dataset}.csv", f"{dataset}.csv")
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    check()
    return artifact, manifest


def process_one_export_job() -> bool:
    """Claim and finish one job; return False if no work or storage is disabled."""
    settings = ExportSettings()
    if not settings.configured():
        return False
    storage = ObjectStorage(settings)
    with SessionLocal() as db:
        job = claim_export(db, settings)
    if job is None:
        return False
    stopped, lost = threading.Event(), threading.Event()
    deadline = time.monotonic() + settings.timeout_seconds

    def check() -> None:
        if lost.is_set() or time.monotonic() > deadline:
            raise TimeoutError("Export deadline or lease exceeded")

    def heartbeat() -> None:
        while not stopped.wait(settings.lease_seconds / 3):
            try:
                if not _renew(job, settings):
                    lost.set()
                    return
            except Exception:
                logger.exception("Export heartbeat failed", export_id=job.id)
                lost.set()
                return

    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    key = None
    published = False
    try:
        with TemporaryDirectory(prefix="crash-export-") as scratch:
            path, manifest = generate_export(job, Path(scratch), settings, check)
            check()
            key = f"exports/{job.id}/{job.lease_token}/{path.name}"
            storage.upload(path, key, path.name, file_sha256(path))
            check()
            with SessionLocal() as db:
                changed = db.execute(
                    update(ExportJob)
                    .where(
                        ExportJob.id == job.id,
                        ExportJob.status == "running",
                        ExportJob.lease_token == job.lease_token,
                        ExportJob.lease_until > utcnow(),
                        ExportJob.expires_at > utcnow(),
                    )
                    .values(
                        status="completed",
                        object_key=key,
                        filename=path.name,
                        manifest=manifest,
                        lease_until=None,
                    )
                )
                db.commit()
                published = changed.rowcount == 1
    except Exception:
        logger.exception("Export failed", export_id=job.id)
        with SessionLocal() as db:
            db.execute(
                update(ExportJob)
                .where(
                    ExportJob.id == job.id,
                    ExportJob.status == "running",
                    ExportJob.lease_token == job.lease_token,
                )
                .values(
                    status="failed"
                    if job.attempts >= settings.max_attempts
                    else "queued",
                    error="Export generation failed; retry or narrow the selection",
                    lease_until=None,
                )
            )
            db.commit()
    finally:
        stopped.set()
        pulse.join(timeout=5)
        if key is not None and not published:
            storage.delete(key)
    return True


def cleanup_expired_exports() -> int:
    settings = ExportSettings()
    if not settings.configured():
        return 0
    storage = ObjectStorage(settings)
    count = 0
    with SessionLocal() as db:
        jobs = db.scalars(
            select(ExportJob)
            .where(
                ExportJob.expires_at <= utcnow(),
                ExportJob.status != "expired",
            )
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        for job in jobs:
            if job.object_key is not None:
                storage.delete(job.object_key)
            job.status = "expired"
            job.object_key = None
            count += 1
        db.commit()

    def retain_key(key: str) -> bool:
        parts = key.split("/")
        if len(parts) < 2:
            return True
        with SessionLocal() as session:
            job = session.get(ExportJob, parts[1])
            return (
                job is not None
                and job.expires_at > utcnow()
                and job.status in {"queued", "running", "completed"}
            )

    storage.cleanup_orphans(
        utcnow() - timedelta(hours=settings.retention_hours), retain_key
    )
    return count

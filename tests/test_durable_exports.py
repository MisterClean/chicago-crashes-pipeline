"""Run DB cases with EXPORT_TEST_DATABASE_URL pointing to disposable PostGIS."""

import csv
import io
import json
import os
import uuid
import zipfile
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.routers.dashboard import LocationReportExportRequest
from src.models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from src.models.exports import ExportJob
from src.services import export_service as service
from src.services.object_storage import ExportSettings


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("EXPORT_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("EXPORT_TEST_DATABASE_URL is not set")
    admin = create_engine(url)
    schema = "export_test_" + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema},public"}
    )
    for model in (Crash, CrashPerson, CrashVehicle, VisionZeroFatality, ExportJob):
        model.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(service, "engine", engine)
    monkeypatch.setattr(service, "SessionLocal", sessions)
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO crashes
            (crash_record_id, crash_date, geometry, created_at, updated_at)
            VALUES ('inside', '2024-01-01',
                    ST_SetSRID(ST_Point(-87.63,41.88),4326),now(),now()),
                   ('outside','2024-01-01',ST_SetSRID(ST_Point(-88,42),4326),now(),now())""")
        )
        conn.execute(
            text("""INSERT INTO crash_people
            (crash_record_id,person_id,age,created_at,updated_at)
            VALUES ('inside','one',30,now(),now()),('outside','two',40,now(),now())""")
        )
    yield engine, sessions
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def request(datasets=None):
    return LocationReportExportRequest(
        latitude=41.88,
        longitude=-87.63,
        radius_feet=1000,
        datasets=datasets or ["crashes"],
    )


def test_invalid_datasets_rejected_before_database():
    with pytest.raises(ValueError, match="Select"):
        service.submit_export(None, request(["secrets"]), ExportSettings())


def test_schema_has_no_internal_timestamp_columns():
    assert "updated_at" not in service.EXPORT_COLUMNS["crashes"]
    assert "crash_record_id" in service.EXPORT_COLUMNS["people"]


def test_snapshot_zip_and_spatial_join(database, tmp_path):
    engine, sessions = database
    settings = ExportSettings()
    with sessions() as db:
        service.submit_export(db, request(["crashes", "people"]), settings)
        job = service.claim_export(db, settings)
    checks = 0

    def update_after_snapshot():
        nonlocal checks
        checks += 1
        if checks == 1:
            # Snapshot is pinned before this callback. Later dataset must see age 30.
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE crash_people SET age=99 WHERE person_id='one'")
                )

    path, manifest = service.generate_export(
        job, tmp_path, settings, update_after_snapshot
    )
    with zipfile.ZipFile(path) as archive:
        crashes = list(
            csv.DictReader(io.StringIO(archive.read("crashes.csv").decode()))
        )
        people = list(csv.DictReader(io.StringIO(archive.read("people.csv").decode())))
        assert len(crashes) == len(people) == 1
        assert crashes[0]["crash_record_id"] == "inside"
        assert people[0]["age"] == "30"
        assert (
            json.loads(archive.read("manifest.json"))["datasets"]["people"]["rows"] == 1
        )
    assert manifest["snapshot"]


def test_claim_limit_reclaim_and_fencing(database):
    _, sessions = database
    settings = ExportSettings(max_concurrent=1)
    with sessions() as db:
        service.submit_export(db, request(), settings)
        service.submit_export(db, request(), settings)
        first = service.claim_export(db, settings)
        assert service.claim_export(db, settings) is None
        db.execute(
            text("UPDATE export_jobs SET lease_until=:expired WHERE id=:id"),
            {"expired": service.utcnow() - timedelta(seconds=1), "id": first.id},
        )
        db.commit()
        replacement = service.claim_export(db, settings)
        assert replacement.id == first.id
        assert replacement.lease_token != first.lease_token
        assert replacement.attempts == 2
    assert not service._renew(first, settings)
    assert service._renew(replacement, settings)


def test_export_bound(database, tmp_path):
    engine, sessions = database
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO crashes
            (crash_record_id,crash_date,geometry,created_at,updated_at)
            SELECT 'extra-' || n, now(), ST_SetSRID(ST_Point(-87.63,41.88),4326),
                   now(),now() FROM generate_series(1,30) n""")
        )
    with sessions() as db:
        job = service.submit_export(db, request(), ExportSettings())
        with pytest.raises(ValueError, match="byte limit"):
            service.generate_export(
                job, tmp_path, ExportSettings(max_bytes=1024), lambda: None
            )


def test_worker_publish_and_expiry(database, monkeypatch):
    _, sessions = database
    settings = ExportSettings(
        endpoint="https://example.invalid",
        bucket="test",
        access_key_id="test",
        secret_access_key="test",
    )
    artifacts = {}

    class Storage:
        def __init__(self, config):
            pass

        def upload(self, path, key, filename, sha256):
            artifacts[key] = path.read_bytes()
            assert service.file_sha256(path) == sha256

        def delete(self, key):
            artifacts.pop(key, None)

        def cleanup_orphans(self, before, retain_key):
            return 0

    monkeypatch.setattr(service, "ExportSettings", lambda: settings)
    monkeypatch.setattr(service, "ObjectStorage", Storage)
    with sessions() as db:
        job_id = service.submit_export(db, request(), settings).id
    assert service.process_one_export_job()
    with sessions() as db:
        job = db.get(ExportJob, job_id)
        assert job.status == "completed"
        assert job.manifest["datasets"]["crashes"]["rows"] == 1
        assert job.object_key in artifacts
        job.expires_at = service.utcnow() - timedelta(seconds=1)
        db.commit()
    assert service.cleanup_expired_exports() == 1
    assert not artifacts
    with sessions() as db:
        assert db.get(ExportJob, job_id).status == "expired"


def test_worker_upload_failure_never_publishes(database, monkeypatch):
    _, sessions = database
    settings = ExportSettings(
        endpoint="https://example.invalid",
        bucket="test",
        access_key_id="test",
        secret_access_key="test",
        max_attempts=1,
    )
    deleted = []

    class Storage:
        def __init__(self, config):
            pass

        def upload(self, *args):
            raise OSError("storage unavailable")

        def delete(self, key):
            deleted.append(key)

    monkeypatch.setattr(service, "ExportSettings", lambda: settings)
    monkeypatch.setattr(service, "ObjectStorage", Storage)
    with sessions() as db:
        job_id = service.submit_export(db, request(), settings).id
    assert service.process_one_export_job()
    with sessions() as db:
        job = db.get(ExportJob, job_id)
        assert job.status == "failed"
        assert job.object_key is None
        assert "storage unavailable" not in job.error
    assert len(deleted) == 1


@pytest.mark.parametrize("stray_place_type", [None, "wards"])
def test_radius_export_keeps_exact_distance_at_buffer_edge(
    database, tmp_path, stray_place_type
):
    engine, sessions = database
    settings = ExportSettings()
    radius_request = request()
    radius_request.place_type = stray_place_type
    with engine.begin() as conn:
        # A point just inside the true circle between buffer vertices lies outside
        # the polygon approximation. Exports must use ST_DWithin like the report.
        conn.execute(
            text("""INSERT INTO crashes
            (crash_record_id,crash_date,geometry,created_at,updated_at)
            VALUES ('near-boundary','2024-01-01',
              ST_Project(ST_SetSRID(ST_Point(-87.63,41.88),4326)::geography,
                         1000 * 0.3048 * 0.9999, pi()/32)::geometry,
              now(),now())""")
        )
        assert conn.scalar(
            text("""SELECT NOT ST_Contains(
            ST_Buffer(ST_SetSRID(ST_Point(-87.63,41.88),4326)::geography,
                      1000 * 0.3048)::geometry, geometry)
            FROM crashes WHERE crash_record_id='near-boundary'""")
        )
    with sessions() as db:
        job = service.submit_export(db, radius_request, settings)
        assert "resolved_area" not in job.request
    path, _ = service.generate_export(job, tmp_path, settings, lambda: None)
    with path.open(encoding="utf-8", newline="") as stream:
        assert "near-boundary" in {
            row["crash_record_id"] for row in csv.DictReader(stream)
        }

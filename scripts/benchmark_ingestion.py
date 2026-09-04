"""Compare legacy ORM and COPY ingestion in disposable local PostGIS schemas.

Example:
    INGESTION_TEST_DATABASE_URL=postgresql://.../crashes_refactor \
        venv/bin/python scripts/benchmark_ingestion.py --rows 5000 --output /tmp/benchmark.json

Only loopback PostgreSQL URLs are accepted. Two random benchmark-owned schemas
are created and dropped; existing schemas and application tables are untouched.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.crashes import Crash  # noqa: E402
from src.services.database_service import DatabaseService  # noqa: E402
from src.validators.data_sanitizer import DataSanitizer  # noqa: E402


def old_upsert(service, records):
    """The previous production algorithm, including one lookup per row."""
    inserted = updated = 0
    with service.session_factory() as session:
        for record in records:
            prepared = service._prepare_crash_record(record)
            existing = session.get(Crash, prepared["crash_record_id"])
            if existing is not None:
                service._assign_columns(existing, prepared)
                updated += 1
            else:
                session.add(Crash(**prepared))
                inserted += 1
        session.commit()
    return {"inserted": inserted, "updated": updated}


def digest(engine):
    """Compare every stored source column, including geometry; omit audit clocks."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT (to_jsonb(c) - 'created_at' - 'updated_at')::text "
                "FROM crashes c ORDER BY crash_record_id"
            )
        ).scalars()
        checksum = hashlib.sha256()
        count = 0
        for row in rows:
            checksum.update(row.encode("utf-8"))
            checksum.update(b"\n")
            count += 1
        return {"rows": count, "sha256": checksum.hexdigest()}


def run(database_url: str, count: int):
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "Only an explicit disposable loopback PostgreSQL database is accepted"
        )
    if not url.database or not any(
        marker in url.database.lower() for marker in ("test", "refactor", "benchmark")
    ):
        raise ValueError("Database name must contain test, refactor, or benchmark")
    sanitizer = DataSanitizer()
    records = [
        sanitizer.sanitize_crash_record(
            {
                "crash_record_id": f"bench-{index:09}",
                "crash_date": "2026-01-01T13:00:00",
                "latitude": "41.9",
                "longitude": "-87.7",
                "street_name": "BENCHMARK",
                "injuries_total": "0",
                "injuries_fatal": "0",
                "injuries_incapacitating": "0",
                "injuries_non_incapacitating": "0",
                "injuries_reported_not_evident": "0",
                "injuries_no_indication": "0",
                "injuries_unknown": "0",
            }
        )
        for index in range(count)
    ]
    changed = [
        dict(record, street_name="BENCHMARK CHANGED", injuries_total=1)
        for record in records
    ]
    report = {
        "rows_per_phase": count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": {},
        "notes": "Single local synthetic trial; timings exclude common input sanitization, include DB prepare/COPY or ORM operations and commit. Not a portal download or production speed forecast.",
    }
    admin = create_engine(url)
    try:
        for name in ("legacy_orm", "copy_staging"):
            schema = "benchmark_ingestion_" + uuid4().hex
            with admin.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = create_engine(
                url, connect_args={"options": f"-csearch_path={schema},public"}
            )
            try:
                Crash.__table__.create(engine)
                service = DatabaseService()
                service.session_factory = sessionmaker(bind=engine, autoflush=False)
                phases = {}
                for phase, inputs in (
                    ("initial", records),
                    ("unchanged", records),
                    ("changed", changed),
                ):
                    started = perf_counter()
                    metrics = (
                        old_upsert(service, inputs)
                        if name == "legacy_orm"
                        else service.upsert_crash_records(inputs)
                    )
                    seconds = perf_counter() - started
                    phases[phase] = {
                        "seconds": seconds,
                        "rows_per_second": count / seconds,
                        "metrics": metrics,
                        "stored_data": digest(engine),
                    }
                report["results"][name] = phases
            finally:
                engine.dispose()
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        admin.dispose()
    for phase in ("initial", "unchanged", "changed"):
        old = report["results"]["legacy_orm"][phase]
        new = report["results"]["copy_staging"][phase]
        if (
            old["stored_data"] != new["stored_data"]
            or new["stored_data"]["rows"] != count
        ):
            raise AssertionError(
                f"Stored data differs for phase {phase}; benchmark invalid"
            )
        new["speedup_vs_legacy"] = old["seconds"] / new["seconds"]
    report["equivalence_verified"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("INGESTION_TEST_DATABASE_URL")
    )
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error(
            "Pass --database-url or set INGESTION_TEST_DATABASE_URL explicitly"
        )
    if not 1 <= arguments.rows <= 10000:
        parser.error("--rows must be between 1 and 10000 for this bounded benchmark")
    report = run(arguments.database_url, arguments.rows)
    serialized = json.dumps(report, indent=2)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()

"""Transport regressions and optional isolated PostgreSQL publication tests."""

import csv
import io
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.etl.csv_client import CSVClient
from src.etl.soda_client import SODAClient
from src.models.crashes import Crash, CrashPerson, CrashVehicle, VisionZeroFatality
from src.models.ingestion import IngestionCheckpoint
from src.services.database_service import DatabaseService
from src.services.sync_service import SyncService
from src.validators.data_sanitizer import DataSanitizer


@pytest.mark.asyncio
async def test_api_pages_without_count_and_orders_ties():
    async with SODAClient() as client:
        calls = []

        async def fetch(**kwargs):
            calls.append(kwargs)
            return [{"id": 1}, {"id": 2}] if kwargs["offset"] == 0 else [{"id": 3}]

        client.fetch_records = fetch
        batches = [batch async for batch in client.iter_batches("unused", batch_size=2)]
        assert sum(map(len, batches)) == 3
        assert calls[1]["offset"] == 2
        assert calls[0]["order_by"] == "crash_date, :id"


def test_end_date_includes_final_second_and_csv_clock():
    assert "2025-01-01T00:00:00" in SODAClient._build_date_where_clause(
        None, "2024-12-31", "crash_date"
    )
    sanitizer = DataSanitizer()
    for value, hour in [("12:00:00 AM", 0), ("12:00:00 PM", 12), ("01:04:05 PM", 13)]:
        parsed = sanitizer._parse_datetime("09/04/2026 " + value)
        assert parsed.hour == hour
    assert (
        sanitizer.sanitize_vehicle_record({"crash_date": "09/04/2026 01:04:05 PM"})[
            "crash_date"
        ].hour
        == 13
    )


@pytest.mark.asyncio
async def test_csv_mapping_ids_and_embedded_newline():
    csv_client = CSVClient()
    headers = csv_client.mapping["crashes"]["observed_csv_headers"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    writer.writerow(
        {
            "CRASH_RECORD_ID": "0000123",
            "CRASH_DATE": "09/04/2026 01:00:00 PM",
            "STREET_NAME": "quoted,\navenue",
        }
    )

    def response(request):
        if "/resource/" in request.url.path:
            return httpx.Response(200, json=[{"count": "1"}])
        if request.url.path.endswith(".json"):
            return httpx.Response(200, json={"rowsUpdatedAt": 123})
        return httpx.Response(200, text=stream.getvalue())

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        csv_client.client = client
        batches = [batch async for batch in csv_client.iter_batches("crashes", 1)]
    assert batches[0][0]["crash_record_id"] == "0000123"
    assert batches[0][0]["street_name"] == "quoted,\navenue"
    assert csv_client.manifests["crashes"]["rows"] == 1
    with pytest.raises(ValueError, match="schema drift"):
        csv_client.normalize_headers("crashes", headers[:-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["count", "revision"])
async def test_csv_rejects_partial_snapshot_and_source_mutation(failure):
    csv_client = CSVClient()
    headers = csv_client.mapping["crashes"]["observed_csv_headers"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    writer.writerow({"CRASH_RECORD_ID": "one"})
    metadata_reads = 0

    def response(request):
        nonlocal metadata_reads
        if "/resource/" in request.url.path:
            return httpx.Response(
                200, json=[{"count": "2" if failure == "count" else "1"}]
            )
        if request.url.path.endswith(".json"):
            metadata_reads += 1
            return httpx.Response(200, json={"rowsUpdatedAt": metadata_reads})
        return httpx.Response(200, text=stream.getvalue())

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        csv_client.client = client
        with pytest.raises(ValueError, match="count mismatch|Source changed"):
            _ = [batch async for batch in csv_client.iter_batches("crashes")]
    assert csv_client.manifests == {}


@pytest.mark.asyncio
async def test_incremental_keyset_bounds():
    calls = []
    async with SODAClient() as client:

        async def fetch(endpoint, **kwargs):
            calls.append(kwargs)
            return (
                [
                    {
                        "source_row_id": "abc",
                        "source_updated_at": "2026-09-01T13:00:00.000Z",
                    }
                ]
                if len(calls) == 1
                else []
            )

        client.fetch_records = fetch
        batches = [
            batch
            async for batch in client.iter_incremental_batches(
                "unused",
                datetime(2026, 9, 1, tzinfo=timezone.utc),
                datetime(2026, 9, 2, tzinfo=timezone.utc),
                1,
            )
        ]
    assert len(batches) == 1
    assert ":id > 'abc'" in calls[1]["where_clause"]
    assert calls[0]["order_by"] == ":updated_at, :id"
    assert ":updated_at < '2026-09-02" in calls[0]["where_clause"]


@pytest.fixture
def postgres_service():
    url = os.getenv("INGESTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set INGESTION_TEST_DATABASE_URL to a disposable PostGIS database")
    schema = "ingestion_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema},public"}
    )
    tables = [
        Crash.__table__,
        CrashPerson.__table__,
        CrashVehicle.__table__,
        VisionZeroFatality.__table__,
        IngestionCheckpoint.__table__,
    ]
    for table in tables:
        table.create(engine)
    service = DatabaseService()
    service.session_factory = sessionmaker(bind=engine, autoflush=False)
    try:
        yield service
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_copy_merge_unchanged_and_rollback(postgres_service):
    service = postgres_service
    sanitizer = DataSanitizer()
    record = sanitizer.sanitize_crash_record(
        {
            "crash_record_id": "001",
            "crash_date": "2026-01-01",
            "latitude": "41.9",
            "longitude": "-87.7",
        }
    )
    assert service.upsert_crash_records([record]) == {
        "inserted": 1,
        "updated": 0,
        "skipped": 0,
    }
    assert service.upsert_crash_records([record]) == {
        "inserted": 0,
        "updated": 0,
        "skipped": 1,
    }
    changed = dict(record, street_name="TEST")
    assert service.upsert_crash_records([changed])["updated"] == 1
    with pytest.raises(ValueError):
        with service.publication() as publication:
            publication.stage_endpoint(
                "crashes", [dict(record, crash_record_id="002")], service
            )
            publication.set_checkpoint("crashes", datetime.now(timezone.utc))
            raise ValueError("download interrupted")
    with service.session_factory() as session:
        assert session.query(Crash).count() == 1
        assert session.query(IngestionCheckpoint).count() == 0


@pytest.mark.asyncio
async def test_full_second_source_failure_does_not_publish(postgres_service):
    class BrokenCSV:
        manifests = {}

        async def iter_batches(self, endpoint, batch_size):
            if endpoint == "people":
                raise ValueError("incomplete second file")
            yield [
                {
                    "crash_record_id": "never-published",
                    "crash_date": "09/04/2026 01:00:00 PM",
                }
            ]

    service = SyncService(database_service=postgres_service, csv_client=BrokenCSV())
    with pytest.raises(ValueError, match="second file"):
        await service.sync(["crashes", "people"], mode="full")
    with postgres_service.session_factory() as session:
        assert session.query(Crash).count() == 0
        assert session.query(IngestionCheckpoint).count() == 0


def test_duplicate_snapshot_keys_fail_before_publication(postgres_service):
    record = DataSanitizer().sanitize_crash_record(
        {"crash_record_id": "dup", "crash_date": "2026-01-01"}
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with postgres_service.publication() as publication:
            publication.stage_endpoint("crashes", [record, record], postgres_service)
            publication.publish()
    with postgres_service.session_factory() as session:
        assert session.query(Crash).count() == 0


@pytest.mark.asyncio
async def test_full_catches_historical_edits_and_commits_checkpoint(postgres_service):
    class SnapshotCSV:
        manifests = {"crashes": {"rows": 1}}

        async def iter_batches(self, endpoint, batch_size):
            yield [
                {
                    "crash_record_id": "old",
                    "crash_date": "01/01/2018 01:00:00 PM",
                    "street_name": "BEFORE",
                }
            ]

    class DeltaClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def iter_incremental_batches(self, endpoint, lower, upper, batch_size):
            assert lower <= upper
            yield [
                {
                    "crash_record_id": "old",
                    "crash_date": "2018-01-01T13:00:00",
                    "street_name": "AFTER",
                }
            ]

    service = SyncService(
        database_service=postgres_service,
        csv_client=SnapshotCSV(),
        client_factory=DeltaClient,
    )
    result = await service.sync(["crashes"], mode="full")
    assert result.total_inserted == 1
    assert result.total_updated == 1
    assert result.source_manifests["crashes"]["rows"] == 1
    with postgres_service.session_factory() as session:
        assert session.get(Crash, "old").street_name == "AFTER"
        assert (
            session.get(IngestionCheckpoint, "crashes").source_updated_before
            is not None
        )


def test_publication_lock_rejects_concurrent_writer(postgres_service):
    with postgres_service.publication():
        with pytest.raises(RuntimeError, match="Another ingestion"):
            with postgres_service.publication():
                pytest.fail("Second publisher acquired the global lock")

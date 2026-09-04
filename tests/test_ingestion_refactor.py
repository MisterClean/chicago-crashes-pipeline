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
from src.services.sync_service import EndpointSyncResult, SyncService
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


def test_fatality_csv_api_source_point_parity_without_chicago_bounds():
    sanitizer = DataSanitizer()
    common = {"person_id": "parity", "latitude": "40.0", "longitude": "-88.0"}
    csv_row = sanitizer.sanitize_fatality_record(
        dict(
            common,
            crash_date="07/19/2025 11:19:00 PM",
            geocoded_column="POINT (-88.0000 40.0000)",
        )
    )
    api_row = sanitizer.sanitize_fatality_record(
        dict(
            common,
            crash_date="2025-07-19T23:19:00.000",
            geocoded_column={"type": "Point", "coordinates": [-88.0, 40.0]},
        )
    )
    assert csv_row == api_row
    assert csv_row["latitude"] is None
    assert csv_row["longitude"] is None
    assert csv_row["geocoded_column"] == "POINT (-88 40)"
    assert sanitizer._canonical_source_point(
        "POINT (-87.58095357 41.79898927)"
    ) == sanitizer._canonical_source_point(
        {"type": "Point", "coordinates": [-87.58095357, 41.79898927]}
    )
    assert sanitizer._canonical_source_point(None) is None


def test_fatality_point_transport_change_is_unchanged_in_postgres(postgres_service):
    sanitizer = DataSanitizer()
    common = {
        "person_id": "parity",
        "crash_date": "2025-07-19T23:19:00",
        "latitude": "41.79898927",
        "longitude": "-87.58095357",
    }
    csv_row = sanitizer.sanitize_fatality_record(
        dict(common, geocoded_column="POINT (-87.58095357 41.79898927)")
    )
    api_row = sanitizer.sanitize_fatality_record(
        dict(
            common,
            geocoded_column={
                "type": "Point",
                "coordinates": [-87.58095357, 41.79898927],
            },
        )
    )
    assert postgres_service.upsert_fatality_records([csv_row])["inserted"] == 1
    assert postgres_service.upsert_fatality_records([api_row]) == {
        "inserted": 0,
        "updated": 0,
        "skipped": 1,
    }


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


def test_missing_fatality_ids_are_explicit_and_diagnostics_bounded():
    raw = [{"person_id": "", "crash_date": "2020-01-01"}] * 25
    raw += [{"person_id": str(index)} for index in range(975)]
    progress = EndpointSyncResult(name="fatalities", records_fetched=len(raw))
    accepted = SyncService._reject_unidentified_fatalities(
        "fatalities", raw, raw, progress
    )
    SyncService._validate_rejections(progress, "full")
    assert len(accepted) == 975
    assert progress.records_rejected == 25
    assert progress.rejection_reasons == {"missing_person_id": 25}
    assert len(progress.rejection_samples) == 20
    assert progress.rejection_samples[0]["row"] == 1
    assert progress.rejection_samples[-1]["row"] == 20
    other = SyncService._reject_unidentified_fatalities("people", raw, raw, progress)
    assert other is raw  # No general relaxation of required identity fields.


@pytest.mark.parametrize(
    "total,rejected,mode",
    [(20, 2, "full"), (1000, 101, "full"), (101, 101, "incremental")],
)
def test_missing_fatality_id_guards(total, rejected, mode):
    progress = EndpointSyncResult(
        name="fatalities", records_fetched=total, records_rejected=rejected
    )
    with pytest.raises(ValueError, match="publication rejected"):
        SyncService._validate_rejections(progress, mode)


@pytest.mark.asyncio
async def test_full_fatalities_publish_valid_rows_and_account_for_rejects(
    postgres_service,
):
    class Snapshot:
        manifests = {"fatalities": {"rows": 20}}

        async def iter_batches(self, endpoint, batch_size):
            yield [{"person_id": "", "crash_date": "01/01/2020 01:00:00 PM"}]
            yield [
                {"person_id": f"valid-{index}", "crash_date": "01/01/2020 01:00:00 PM"}
                for index in range(19)
            ]

    class Delta:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def iter_incremental_batches(self, *args):
            pytest.fail("Fatalities must revalidate all source identities")

        async def iter_batches(self, **kwargs):
            assert "start_date" not in kwargs
            async for batch in Snapshot().iter_batches("fatalities", 100):
                yield batch

    result = await SyncService(
        database_service=postgres_service, csv_client=Snapshot(), client_factory=Delta
    ).sync(["fatalities"], mode="full")
    assert result.total_inserted == 19
    assert result.total_rejected == 2  # One excluded in each source pass.
    assert result.total_skipped == 21
    assert result.total_unchanged == 19
    assert result.total_records == 40
    manifest = result.source_manifests["fatalities"]
    assert manifest["validation"]["accepted_rows"] == 19
    assert manifest["validation"]["rejected_rows"] == 1
    assert manifest["catchup_validation"]["rejected_rows"] == 1
    with postgres_service.session_factory() as session:
        assert session.query(VisionZeroFatality).count() == 19
        assert session.get(IngestionCheckpoint, "fatalities") is not None


def test_fatality_duplicates_keep_identical_and_reject_entire_conflict():
    progress = EndpointSyncResult(name="fatalities")
    rows = [
        {"person_id": "same", "crash_date": "2020-01-01"},
        {"person_id": "conflict", "crash_date": "2020-01-01"},
        {"person_id": "unique", "crash_date": "2020-01-01"},
        {"person_id": "same", "crash_date": "2020-01-01"},
        {"person_id": "conflict", "crash_date": "2021-01-01"},
    ]
    accepted = SyncService._deduplicate_fatalities(rows, progress)
    assert {row["person_id"] for row in accepted} == {"same", "unique"}
    assert progress.records_rejected == 3
    assert progress.rejection_reasons == {
        "identical_duplicate_person_id": 1,
        "conflicting_person_id": 2,
    }
    assert progress.rejection_samples[-1]["different_fields"] == ["crash_date"]
    reversed_progress = EndpointSyncResult(name="fatalities")
    reversed_rows = SyncService._deduplicate_fatalities(
        list(reversed(rows)), reversed_progress
    )
    assert sorted(accepted, key=lambda row: row["person_id"]) == sorted(
        reversed_rows, key=lambda row: row["person_id"]
    )


@pytest.mark.asyncio
async def test_fatality_conflicts_across_batches_preserve_existing_ambiguous_row(
    postgres_service,
):
    original = DataSanitizer().sanitize_fatality_record(
        {"person_id": "conflict", "crash_date": "2019-01-01"}
    )
    postgres_service.upsert_fatality_records([original])

    class Source:
        manifests = {"fatalities": {"rows": 42}}

        async def iter_batches(self, *args, **kwargs):
            yield [{"person_id": "conflict", "crash_date": "2020-01-01"}]
            yield [
                {"person_id": f"valid-{index}", "crash_date": "2020-01-01"}
                for index in range(40)
            ]
            yield [{"person_id": "conflict", "crash_date": "2021-01-01"}]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def iter_incremental_batches(self, *args):
            pytest.fail("Fatalities must not read an incomplete identity delta")

    result = await SyncService(
        database_service=postgres_service, csv_client=Source(), client_factory=Source
    ).sync(["fatalities"], mode="full")
    assert result.total_inserted == 40
    assert result.total_rejected == 4
    assert result.source_manifests["fatalities"]["validation"]["rejection_reasons"] == {
        "conflicting_person_id": 2
    }
    with postgres_service.session_factory() as session:
        assert session.query(VisionZeroFatality).count() == 41
        assert session.get(VisionZeroFatality, "conflict").crash_date == datetime(
            2019, 1, 1
        )

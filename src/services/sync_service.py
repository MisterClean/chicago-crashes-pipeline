"""High-level data synchronization orchestration for Chicago crash datasets."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Literal

from src.etl.csv_client import CSVClient
from src.etl.soda_client import SODAClient
from src.services.database_service import DatabaseService
from src.utils.config import settings
from src.utils.logging import get_logger
from src.validators.data_sanitizer import DataSanitizer

logger = get_logger(__name__)


@dataclass
class EndpointSyncResult:
    """Summary of a sync run for a single endpoint."""

    name: str
    batches_processed: int = 0
    records_fetched: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    records_unchanged: int = 0
    records_rejected: int = 0
    timing_seconds: dict[str, float] = field(default_factory=dict)


@dataclass
class SyncResult:
    """Aggregate sync run summary across all endpoints."""

    started_at: datetime
    completed_at: datetime | None = None
    endpoint_results: dict[str, EndpointSyncResult] = field(default_factory=dict)
    source_manifests: dict[str, dict[str, Any]] = field(default_factory=dict)
    timing_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def total_records(self) -> int:
        return sum(result.records_fetched for result in self.endpoint_results.values())

    @property
    def total_inserted(self) -> int:
        return sum(result.records_inserted for result in self.endpoint_results.values())

    @property
    def total_updated(self) -> int:
        return sum(result.records_updated for result in self.endpoint_results.values())

    @property
    def total_skipped(self) -> int:
        return sum(result.records_skipped for result in self.endpoint_results.values())

    @property
    def total_unchanged(self) -> int:
        return sum(
            result.records_unchanged for result in self.endpoint_results.values()
        )

    @property
    def total_rejected(self) -> int:
        return sum(result.records_rejected for result in self.endpoint_results.values())


class SyncService:
    """Coordinates streaming fetch + persistence for crash pipeline data."""

    def __init__(
        self,
        batch_size: int | None = None,
        sanitizer: DataSanitizer | None = None,
        database_service: DatabaseService | None = None,
        client_factory: Callable[[], SODAClient] | None = None,
        csv_client: CSVClient | None = None,
    ) -> None:
        self.batch_size = batch_size or settings.api.batch_size
        self.sanitizer = sanitizer or DataSanitizer()
        self.database_service = database_service or DatabaseService()
        self.client_factory: Callable[[], SODAClient] = client_factory or SODAClient
        self.csv_client = csv_client or CSVClient()

    async def sync(
        self,
        endpoints: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
        batch_callback: Callable[[EndpointSyncResult], None] | None = None,
        mode: Literal["api", "full", "incremental"] = "api",
    ) -> SyncResult:
        """Synchronise one or more endpoints.

        Args:
            endpoints: Collection of endpoint slugs to sync (crashes, people, ...).
            start_date: Optional ISO date (YYYY-MM-DD) lower bound.
            end_date: Optional ISO date (YYYY-MM-DD) upper bound.
            batch_callback: Optional hook invoked after each batch with interim stats.

        Returns:
            SyncResult summarising work completed.
        """

        if mode not in {"api", "full", "incremental"}:
            raise ValueError(f"Unknown ingestion mode: {mode}")
        if mode != "api" and (start_date is not None or end_date is not None):
            raise ValueError("Full/incremental ingestion cannot use crash-date filters")
        if not endpoints or len(set(endpoints)) != len(endpoints):
            raise ValueError("Select nonempty, unique ingestion endpoints")
        if any(endpoint not in settings.api.endpoints for endpoint in endpoints):
            raise ValueError("Unknown ingestion endpoint")
        if isinstance(self.database_service, DatabaseService):
            result = await self._staged_sync(
                endpoints, start_date, end_date, batch_callback, mode
            )
            if mode == "full":
                # Full publication has committed successfully. A separately
                # atomic catch-up picks up historical edits made during download.
                # If it fails, the committed checkpoint permits a safe retry;
                # the validated full snapshot remains available to readers.
                catchup = await self._staged_sync(
                    endpoints, None, None, batch_callback, "incremental"
                )
                for endpoint, delta in catchup.endpoint_results.items():
                    snapshot = result.endpoint_results[endpoint]
                    for metric in (
                        "batches_processed",
                        "records_fetched",
                        "records_inserted",
                        "records_updated",
                        "records_skipped",
                        "records_unchanged",
                        "records_rejected",
                    ):
                        setattr(
                            snapshot,
                            metric,
                            getattr(snapshot, metric) + getattr(delta, metric),
                        )
                    for stage, seconds in delta.timing_seconds.items():
                        snapshot.timing_seconds[stage] = (
                            snapshot.timing_seconds.get(stage, 0) + seconds
                        )
                for stage, seconds in catchup.timing_seconds.items():
                    result.timing_seconds[stage] = (
                        result.timing_seconds.get(stage, 0) + seconds
                    )
                result.completed_at = catchup.completed_at
            return result
        if mode != "api":
            raise ValueError(
                "Full/incremental modes require staged database publication"
            )

        result = SyncResult(started_at=datetime.utcnow())

        client_context = self.client_factory()
        is_async_context = hasattr(client_context, "__aenter__")

        if is_async_context:
            client_cm = client_context
        else:
            client_cm = _AsyncNullContext(client_context)

        async with client_cm as client:
            for endpoint in endpoints:
                endpoint_result = await self._sync_single_endpoint(
                    client=client,
                    endpoint=endpoint,
                    start_date=start_date,
                    end_date=end_date,
                    batch_callback=batch_callback,
                )
                result.endpoint_results[endpoint] = endpoint_result

        result.completed_at = datetime.utcnow()
        return result

    async def _staged_sync(self, endpoints, start_date, end_date, batch_callback, mode):
        result = SyncResult(started_at=datetime.now(timezone.utc))
        started = perf_counter()
        # Leave a small safety lag for visibility of source modifications. A full
        # snapshot sets the watermark to its start, so the next incremental run
        # catches changes during the download rather than skipping them.
        upper_bound = result.started_at - timedelta(minutes=5)
        with self.database_service.publication() as publication:
            async with self.client_factory() as client:
                for endpoint in endpoints:
                    progress = EndpointSyncResult(name=endpoint)
                    progress.timing_seconds = {
                        "fetch": 0.0,
                        "normalize": 0.0,
                        "copy": 0.0,
                        "merge": 0.0,
                    }
                    endpoint_started = perf_counter()
                    result.endpoint_results[endpoint] = progress
                    if mode == "full":
                        batches = self.csv_client.iter_batches(
                            endpoint, self.batch_size
                        )
                    elif mode == "incremental":
                        checkpoint = publication.checkpoint(endpoint)
                        if checkpoint is None:
                            raise ValueError(
                                f"No source checkpoint for {endpoint}; run a full refresh first"
                            )
                        batches = client.iter_incremental_batches(
                            settings.api.endpoints[endpoint],
                            checkpoint - timedelta(minutes=5),
                            upper_bound,
                            self.batch_size,
                        )
                    else:
                        batches = client.iter_batches(
                            endpoint=settings.api.endpoints[endpoint],
                            batch_size=self.batch_size,
                            start_date=start_date,
                            end_date=end_date,
                            date_field=self._resolve_date_field(endpoint),
                        )
                    fetch_started = perf_counter()
                    async for batch in batches:
                        progress.timing_seconds["fetch"] += (
                            perf_counter() - fetch_started
                        )
                        progress.batches_processed += 1
                        progress.records_fetched += len(batch)
                        normalize_started = perf_counter()
                        cleaned = self._sanitize_batch(endpoint, batch)
                        progress.timing_seconds["normalize"] += (
                            perf_counter() - normalize_started
                        )
                        copy_started = perf_counter()
                        publication.stage_endpoint(
                            endpoint, cleaned, self.database_service
                        )
                        progress.timing_seconds["copy"] += perf_counter() - copy_started
                        if batch_callback is not None:
                            batch_callback(progress)
                        fetch_started = perf_counter()
                    progress.timing_seconds["fetch"] += perf_counter() - fetch_started
                    progress.timing_seconds["total"] = perf_counter() - endpoint_started
                    if mode in {"full", "incremental"}:
                        publication.set_checkpoint(endpoint, upper_bound)
            merge_started = perf_counter()
            results = publication.publish()
            result.timing_seconds["merge"] = perf_counter() - merge_started
            table_names = {
                "crashes": "crashes",
                "people": "crash_people",
                "vehicles": "crash_vehicles",
                "fatalities": "vision_zero_fatalities",
            }
            for endpoint, progress in result.endpoint_results.items():
                stats = results.get(
                    table_names[endpoint], {"inserted": 0, "updated": 0, "skipped": 0}
                )
                progress.records_inserted = stats["inserted"]
                progress.records_updated = stats["updated"]
                progress.records_skipped = stats["skipped"]
                progress.records_unchanged = stats.get("unchanged", 0)
                progress.records_rejected = stats.get("rejected", 0)
                progress.timing_seconds["merge"] = stats.get("merge_seconds", 0)
                progress.timing_seconds["total"] += stats.get("merge_seconds", 0)
        result.source_manifests = (
            dict(self.csv_client.manifests) if mode == "full" else {}
        )
        result.completed_at = datetime.now(timezone.utc)
        result.timing_seconds["total"] = perf_counter() - started
        for stage in ("fetch", "normalize", "copy"):
            result.timing_seconds[stage] = sum(
                progress.timing_seconds[stage]
                for progress in result.endpoint_results.values()
            )
        for endpoint, manifest in result.source_manifests.items():
            result.endpoint_results[endpoint].timing_seconds["download"] = manifest.get(
                "download_seconds", 0
            )
        return result

    async def _sync_single_endpoint(
        self,
        *,
        client: SODAClient,
        endpoint: str,
        start_date: str | None,
        end_date: str | None,
        batch_callback: Callable[[EndpointSyncResult], None] | None,
    ) -> EndpointSyncResult:
        endpoint_result = EndpointSyncResult(name=endpoint)

        date_field = self._resolve_date_field(endpoint)

        if hasattr(client, "iter_batches"):
            async for batch in client.iter_batches(
                endpoint=settings.api.endpoints[endpoint],
                batch_size=self.batch_size,
                start_date=start_date,
                end_date=end_date,
                date_field=date_field,
            ):
                endpoint_result.batches_processed += 1
                endpoint_result.records_fetched += len(batch)

                processed_records = self._sanitize_batch(endpoint, batch)
                db_result = self._persist_batch(endpoint, processed_records)

                endpoint_result.records_inserted += db_result["inserted"]
                endpoint_result.records_updated += db_result["updated"]
                endpoint_result.records_skipped += db_result["skipped"]

                if batch_callback:
                    batch_callback(endpoint_result)
        else:  # pragma: no cover - compatibility path for mocked clients
            records = await _maybe_await(
                client.fetch_all_records(
                    endpoint=settings.api.endpoints[endpoint],
                    batch_size=self.batch_size,
                    start_date=start_date,
                    end_date=end_date,
                    date_field=date_field,
                    show_progress=False,
                )
            )
            if records:
                endpoint_result.records_fetched += len(records)
                processed_records = self._sanitize_batch(endpoint, records)
                db_result = self._persist_batch(endpoint, processed_records)
                endpoint_result.records_inserted += db_result["inserted"]
                endpoint_result.records_updated += db_result["updated"]
                endpoint_result.records_skipped += db_result["skipped"]

                if batch_callback:
                    batch_callback(endpoint_result)

        logger.info(
            "Endpoint sync complete",
            endpoint=endpoint,
            batches=endpoint_result.batches_processed,
            fetched=endpoint_result.records_fetched,
            inserted=endpoint_result.records_inserted,
            updated=endpoint_result.records_updated,
            skipped=endpoint_result.records_skipped,
        )

        return endpoint_result

    def _sanitize_batch(self, endpoint: str, records: Iterable[dict]) -> list[dict]:
        if endpoint == "crashes":
            return [self.sanitizer.sanitize_crash_record(record) for record in records]
        if endpoint == "people":
            return [self.sanitizer.sanitize_person_record(record) for record in records]
        if endpoint == "vehicles":
            return [
                self.sanitizer.sanitize_vehicle_record(record) for record in records
            ]
        if endpoint == "fatalities":
            return [
                self.sanitizer.sanitize_fatality_record(record) for record in records
            ]

        logger.warning("Unknown endpoint requested during sync", endpoint=endpoint)
        return list(records)

    def _persist_batch(self, endpoint: str, records: list[dict]) -> dict[str, int]:
        if not records:
            return {"inserted": 0, "updated": 0, "skipped": 0}

        if endpoint == "crashes":
            return self.database_service.upsert_crash_records(records)
        if endpoint == "people":
            return self.database_service.upsert_person_records(records)
        if endpoint == "vehicles":
            return self.database_service.upsert_vehicle_records(records)
        if endpoint == "fatalities":
            return self.database_service.upsert_fatality_records(records)

        return {"inserted": 0, "updated": 0, "skipped": len(records)}

    @staticmethod
    def _resolve_date_field(endpoint: str) -> str:
        if endpoint in {"crashes", "people", "vehicles"}:
            return "crash_date"
        if endpoint == "fatalities":
            return "crash_date"
        return "crash_date"


async def run_sync(  # pragma: no cover - thin convenience wrapper used by CLI
    endpoints: Sequence[str],
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int | None = None,
    client_factory: Callable[[], SODAClient] | None = None,
    mode: Literal["api", "full", "incremental"] = "api",
) -> SyncResult:
    service = SyncService(batch_size=batch_size, client_factory=client_factory)
    return await service.sync(
        endpoints=endpoints, start_date=start_date, end_date=end_date, mode=mode
    )


class _AsyncNullContext:
    """Utility context manager for SyncService."""

    # Allows treating sync + async clients the same

    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:  # pragma: no cover - trivial helper
        return self.value

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # pragma: no cover
        closer = getattr(self.value, "close", None)
        if closer:
            maybe = closer()
            if asyncio.iscoroutine(maybe):
                await maybe


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value

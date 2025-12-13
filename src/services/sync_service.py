"""High-level data synchronization orchestration for Chicago crash datasets."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

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


@dataclass
class SyncResult:
    """Aggregate sync run summary across all endpoints."""

    started_at: datetime
    completed_at: Optional[datetime] = None
    endpoint_results: Dict[str, EndpointSyncResult] = field(default_factory=dict)

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


class SyncService:
    """Coordinates streaming fetch + persistence for crash pipeline data."""

    def __init__(
        self,
        batch_size: Optional[int] = None,
        sanitizer: Optional[DataSanitizer] = None,
        database_service: Optional[DatabaseService] = None,
        client_factory: Optional[Callable[[], SODAClient]] = None,
    ) -> None:
        self.batch_size = batch_size or settings.api.batch_size
        self.sanitizer = sanitizer or DataSanitizer()
        self.database_service = database_service or DatabaseService()
        self.client_factory: Callable[[], SODAClient] = client_factory or SODAClient

    async def sync(
        self,
        endpoints: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        batch_callback: Optional[Callable[[EndpointSyncResult], None]] = None,
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

    async def _sync_single_endpoint(
        self,
        *,
        client: SODAClient,
        endpoint: str,
        start_date: Optional[str],
        end_date: Optional[str],
        batch_callback: Optional[Callable[[EndpointSyncResult], None]],
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

    def _sanitize_batch(self, endpoint: str, records: Iterable[Dict]) -> List[Dict]:
        if endpoint == "crashes":
            return [self.sanitizer.sanitize_crash_record(record) for record in records]
        if endpoint == "people":
            return [self.sanitizer.sanitize_person_record(record) for record in records]
        if endpoint == "vehicles":
            return [
                self.sanitizer.sanitize_vehicle_record(record) for record in records
            ]
        if endpoint == "fatalities":
            cleaned = [
                self.sanitizer.sanitize_fatality_record(record) for record in records
            ]
            return self.sanitizer.remove_duplicates(cleaned, "person_id")

        logger.warning("Unknown endpoint requested during sync", endpoint=endpoint)
        return list(records)

    def _persist_batch(self, endpoint: str, records: List[Dict]) -> Dict[str, int]:
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
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: Optional[int] = None,
    client_factory: Optional[Callable[[], SODAClient]] = None,
) -> SyncResult:
    service = SyncService(batch_size=batch_size, client_factory=client_factory)
    return await service.sync(
        endpoints=endpoints, start_date=start_date, end_date=end_date
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

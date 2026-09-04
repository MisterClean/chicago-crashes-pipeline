"""SODA API client for Chicago Open Data Portal."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from tqdm.asyncio import tqdm

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SODAClient:
    """Async client for Chicago Open Data SODA API."""

    def __init__(self, timeout: int = 30, rate_limit: int = 1000):
        """Initialize SODA client.

        Args:
            timeout: Request timeout in seconds
            rate_limit: Requests per hour limit
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.rate_limiter = asyncio.Semaphore(rate_limit)

        # Request session with timeout and retry configuration
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=settings.api.max_concurrent),
        )

        # Headers for API requests
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "ChicagoCrashPipeline/1.0",
        }

        # Add API token if available
        if settings.api.token:
            self.headers["X-App-Token"] = settings.api.token

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    async def fetch_records(
        self,
        endpoint: str,
        limit: int = 50000,
        offset: int = 0,
        where_clause: str | None = None,
        order_by: str | None = None,
        select_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch records from SODA API endpoint.

        Args:
            endpoint: API endpoint URL
            limit: Maximum records to fetch per request
            offset: Number of records to skip
            where_clause: SQL WHERE clause for filtering
            order_by: SQL ORDER BY clause
            select_fields: List of fields to select

        Returns:
            List of record dictionaries
        """
        params = {"$limit": str(limit), "$offset": str(offset)}

        if where_clause:
            params["$where"] = where_clause

        if order_by:
            params["$order"] = order_by

        if select_fields:
            params["$select"] = ",".join(select_fields)

        # Build URL with parameters
        url = f"{endpoint}?{urlencode(params)}"

        # Rate limiting
        async with self.rate_limiter:
            try:
                response = await self._make_request(url)
                return response.json()

            except httpx.TimeoutException:
                logger.error("Request timed out", url=url)
                raise
            except httpx.HTTPError as e:
                logger.error("HTTP error", url=url, error=str(e))
                raise

    async def iter_batches(
        self,
        endpoint: str,
        batch_size: int = 50000,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "crash_date",
        order_by: str | None = None,
        show_progress: bool = False,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield batches of records without loading everything into memory."""

        where_clause = self._build_date_where_clause(start_date, end_date, date_field)
        order_clause = order_by or f"{date_field}, :id"

        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        progress = None
        if show_progress:
            progress = tqdm(desc=f"Fetching {endpoint}", unit="records")

        offset = 0
        while True:
            batch = await self.fetch_records(
                endpoint=endpoint,
                limit=batch_size,
                offset=offset,
                where_clause=where_clause,
                order_by=order_clause,
            )

            if not batch:
                break

            if progress:
                progress.update(len(batch))

            yield batch
            offset += len(batch)

            if len(batch) < batch_size:
                break

        if progress:
            progress.close()

    async def fetch_all_records(
        self,
        endpoint: str,
        batch_size: int = 50000,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "crash_date",
        order_by: str | None = None,
        show_progress: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch all records from endpoint with pagination.

        Args:
            endpoint: API endpoint URL
            batch_size: Records per batch
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            date_field: Field name for date filtering
            order_by: SQL ORDER BY clause
            show_progress: Whether to show progress bar

        Returns:
            List of all record dictionaries
        """
        logger.info("Starting data fetch", endpoint=endpoint, batch_size=batch_size)

        all_records: list[dict[str, Any]] = []
        async for batch in self.iter_batches(
            endpoint=endpoint,
            batch_size=batch_size,
            start_date=start_date,
            end_date=end_date,
            date_field=date_field,
            order_by=order_by,
            show_progress=show_progress,
        ):
            all_records.extend(batch)
            await asyncio.sleep(0.05)

        logger.info("Data fetch completed", total_records=len(all_records))
        return all_records

    async def fetch_incremental_records(
        self,
        endpoint: str,
        last_modified: datetime,
        batch_size: int = 50000,
        show_progress: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch records modified since last sync.

        Args:
            endpoint: API endpoint URL
            last_modified: DateTime of last successful sync
            batch_size: Records per batch
            show_progress: Whether to show progress bar

        Returns:
            List of modified record dictionaries
        """
        records: list[dict[str, Any]] = []
        async for batch in self.iter_incremental_batches(
            endpoint, last_modified, datetime.now(timezone.utc), batch_size
        ):
            records.extend(batch)
        return records

    async def iter_incremental_batches(
        self,
        endpoint: str,
        lower_bound: datetime,
        upper_bound: datetime,
        batch_size: int = 50000,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Read a bounded source-modification interval with a stable row cursor.

        Bounds are UTC source timestamps, not local crash timestamps. The caller
        persists the upper bound only after successfully publishing every batch.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        def literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        def timestamp(value: datetime) -> str:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")

        bounds = (
            f":updated_at >= {literal(timestamp(lower_bound))} AND "
            f":updated_at < {literal(timestamp(upper_bound))}"
        )
        cursor: tuple[str, str] | None = None
        while True:
            where = bounds
            if cursor is not None:
                modified, row_id = map(literal, cursor)
                where += (
                    f" AND (:updated_at > {modified} OR "
                    f"(:updated_at = {modified} AND :id > {row_id}))"
                )
            batch = await self.fetch_records(
                endpoint,
                limit=batch_size,
                where_clause=where,
                order_by=":updated_at, :id",
                select_fields=[
                    "*",
                    ":id AS source_row_id",
                    ":updated_at AS source_updated_at",
                ],
            )
            if not batch:
                return
            tail = batch[-1]
            next_cursor = (str(tail["source_updated_at"]), str(tail["source_row_id"]))
            if next_cursor == cursor:
                raise ValueError("SODA incremental cursor did not advance")
            yield batch
            cursor = next_cursor
            if len(batch) < batch_size:
                return

    @staticmethod
    def _build_date_where_clause(
        start_date: str | None,
        end_date: str | None,
        date_field: str,
    ) -> str | None:
        clauses: list[str] = []
        if start_date:
            clauses.append(f"{date_field} >= '{start_date}T00:00:00'")
        if end_date:
            next_day = date.fromisoformat(end_date) + timedelta(days=1)
            clauses.append(f"{date_field} < '{next_day.isoformat()}T00:00:00'")
        return " AND ".join(clauses) if clauses else None

    async def _make_request(self, url: str) -> httpx.Response:
        """Make HTTP request with retry logic.

        Args:
            url: Request URL

        Returns:
            HTTP response
        """
        for attempt in range(settings.api.max_retries + 1):
            try:
                response = await self.client.get(url, headers=self.headers)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = settings.api.backoff_factor**attempt
                    logger.warning(
                        "Rate limited, retrying", attempt=attempt, wait_time=wait_time
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(
                        "HTTP error", status_code=e.response.status_code, url=url
                    )
                    raise

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < settings.api.max_retries:
                    wait_time = settings.api.backoff_factor**attempt
                    logger.warning(
                        "Request failed, retrying",
                        attempt=attempt,
                        wait_time=wait_time,
                        error=str(e),
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("Request failed after all retries", error=str(e))
                    raise

        raise Exception(
            f"Failed to fetch data after {settings.api.max_retries} retries"
        )

    async def _get_record_count(
        self, endpoint: str, where_clause: str | None = None
    ) -> int:
        """Get total record count for endpoint.

        Args:
            endpoint: API endpoint URL
            where_clause: SQL WHERE clause for filtering

        Returns:
            Total number of records
        """
        params = {"$select": "COUNT(*) as count"}

        if where_clause:
            params["$where"] = where_clause

        url = f"{endpoint}?{urlencode(params)}"

        try:
            response = await self._make_request(url)
            data = response.json()
            return int(data[0]["count"]) if data else 0

        except Exception as e:
            logger.warning("Could not get record count, using fallback", error=str(e))
            # Fallback: try to fetch first batch to estimate
            try:
                first_batch = await self.fetch_records(
                    endpoint=endpoint, limit=1000, where_clause=where_clause
                )
                # If we got a full batch, there are likely more records
                # This is just an estimate for progress bar
                return (
                    len(first_batch) * 10
                    if len(first_batch) == 1000
                    else len(first_batch)
                )
            except Exception:
                return 0

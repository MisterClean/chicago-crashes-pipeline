"""Verified portal CSV transport producing the same field names as SODA."""

import csv
import hashlib
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx


class CSVClient:
    """Download completely before parsing; never publish a truncated response."""

    def __init__(
        self, client: httpx.AsyncClient | None = None, archive_dir: Path | None = None
    ) -> None:
        self.client = client
        configured_archive = os.getenv("INGESTION_ARCHIVE_DIR")
        self.archive_dir = archive_dir or (
            Path(configured_archive) if configured_archive else None
        )
        self.mapping = json.loads(
            Path(__file__)
            .with_name("csv_column_mapping.json")
            .read_text(encoding="utf-8")
        )
        self.manifests: dict[str, dict[str, Any]] = {}

    def normalize_headers(self, endpoint: str, headers: list[str]) -> dict[str, str]:
        specification = self.mapping[endpoint]
        expected = specification["observed_csv_headers"]
        if len(headers) != len(set(headers)) or set(headers) != set(expected):
            raise ValueError(
                f"CSV schema drift for {endpoint}: unexpected or missing headers"
            )
        mapping = {c["csv_header"]: c["api_field"] for c in specification["columns"]}
        if any(header not in mapping for header in headers):
            raise ValueError(f"CSV mapping incomplete for {endpoint}")
        return {header: mapping[header] for header in headers}

    async def iter_batches(
        self, endpoint: str, batch_size: int = 50000
    ) -> AsyncIterator[list[dict[str, Any]]]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.client is None:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120, connect=30), follow_redirects=True
            ) as client:
                async for batch in self._download_batches(client, endpoint, batch_size):
                    yield batch
        else:
            async for batch in self._download_batches(
                self.client, endpoint, batch_size
            ):
                yield batch

    async def _download_batches(self, client, endpoint, batch_size):
        specification = self.mapping[endpoint]
        url = specification["csv_download_url"]
        metadata_response = await client.get(specification["metadata_url"])
        metadata_response.raise_for_status()
        source_revision = metadata_response.json().get("rowsUpdatedAt")
        if source_revision is None:
            raise ValueError(f"Missing source revision for {endpoint}")
        count_url = f"https://data.cityofchicago.org/resource/{specification['dataset_id']}.json"
        count_response = await client.get(
            count_url, params={"$select": "count(*) as count"}
        )
        count_response.raise_for_status()
        expected_rows = int(count_response.json()[0]["count"])
        with TemporaryDirectory(prefix="crash-csv-") as directory:
            path = Path(directory) / "source.csv"
            checksum = hashlib.sha256()
            size = 0
            download_started = perf_counter()
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with path.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)
                        checksum.update(chunk)
                        size += len(chunk)
            download_seconds = perf_counter() - download_started
            rows = 0
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                mapping = self.normalize_headers(endpoint, reader.fieldnames or [])
                batch = []
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError(f"Malformed CSV row in {endpoint}")
                    batch.append({mapping[key]: value for key, value in row.items()})
                    rows += 1
                    if len(batch) == batch_size:
                        yield batch
                        batch = []
                if batch:
                    yield batch
            if rows == 0:
                raise ValueError(f"Refusing empty full snapshot for {endpoint}")
            if rows != expected_rows:
                raise ValueError(
                    f"CSV count mismatch for {endpoint}: expected {expected_rows}, received {rows}"
                )
            metadata_response = await client.get(specification["metadata_url"])
            metadata_response.raise_for_status()
            if metadata_response.json().get("rowsUpdatedAt") != source_revision:
                raise ValueError(
                    f"Source changed during CSV snapshot for {endpoint}; retry full refresh"
                )
            self.manifests[endpoint] = {
                "url": url,
                "sha256": checksum.hexdigest(),
                "bytes": size,
                "rows": rows,
                "source_revision": source_revision,
                "download_seconds": download_seconds,
            }
            if self.archive_dir is not None:
                directory = self.archive_dir / endpoint
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / f"{checksum.hexdigest()}.csv"
                temporary = directory / f"{uuid4().hex}.part"
                try:
                    shutil.copyfile(path, temporary)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                self.manifests[endpoint]["archive_path"] = str(destination)
                destination.with_suffix(".json").write_text(
                    json.dumps(self.manifests[endpoint], indent=2), encoding="utf-8"
                )

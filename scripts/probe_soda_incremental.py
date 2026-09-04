"""Verify live incremental query syntax, fetching at most two rows per dataset."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.etl.soda_client import SODAClient  # noqa: E402
from src.utils.config import settings  # noqa: E402


async def probe():
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "datasets": {}}
    async with SODAClient() as client:
        for endpoint, url in settings.api.endpoints.items():
            rows = []
            try:
                async for batch in client.iter_incremental_batches(
                    url,
                    datetime(1970, 1, 1, tzinfo=timezone.utc),
                    datetime.now(timezone.utc),
                    batch_size=1,
                ):
                    rows.append(
                        {
                            key: batch[0][key]
                            for key in ("source_row_id", "source_updated_at")
                        }
                    )
                    if len(rows) == 2:
                        break
                report["datasets"][endpoint] = {
                    "ok": len(rows) == 2,
                    "cursor_rows": rows,
                }
            except Exception as error:
                report["datasets"][endpoint] = {"ok": False, "error": str(error)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(probe())
    serialized = json.dumps(report, indent=2)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    if not all(dataset["ok"] for dataset in report["datasets"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

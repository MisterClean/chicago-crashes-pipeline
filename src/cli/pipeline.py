"""CLI entry points for orchestrating pipeline sync operations."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from typing import List, Sequence

from src.services.sync_service import run_sync
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _parse_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:  # pragma: no cover - argparse handles error path
        raise argparse.ArgumentTypeError("Dates must be YYYY-MM-DD") from exc
    return value


def _default_endpoints() -> List[str]:
    return ["crashes", "people", "vehicles", "fatalities"]


async def _run_sync_command(args: argparse.Namespace) -> None:
    endpoints: Sequence[str] = args.endpoints or _default_endpoints()
    result = await run_sync(
        endpoints=endpoints,
        start_date=args.start_date,
        end_date=args.end_date,
        batch_size=args.batch_size,
    )

    logger.info(
        "Sync completed",
        endpoints=list(endpoints),
        total_records=result.total_records,
        inserted=result.total_inserted,
        updated=result.total_updated,
        skipped=result.total_skipped,
        duration_seconds=(result.completed_at - result.started_at).total_seconds()
        if result.completed_at
        else None,
    )


def _resolve_start_date(args: argparse.Namespace) -> None:
    if args.start_date:
        return
    if args.mode == "initial-load":
        args.start_date = "2017-01-01"  # Historical backfill default
    elif args.mode == "delta":
        window_days = args.window_days or 7
        start = datetime.utcnow() - timedelta(days=window_days)
        args.start_date = start.strftime("%Y-%m-%d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chicago Crash Pipeline CLI")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument(
        "--endpoints",
        nargs="*",
        help="Subset of endpoints to sync (default: all)",
    )
    base_parser.add_argument(
        "--start-date",
        type=_parse_date,
        help="Inclusive start date (YYYY-MM-DD)",
    )
    base_parser.add_argument(
        "--end-date",
        type=_parse_date,
        help="Exclusive end date (YYYY-MM-DD)",
    )
    base_parser.add_argument(
        "--batch-size",
        type=int,
        default=50000,
        help="Batch size for SODA API requests",
    )

    initial = subparsers.add_parser(
        "initial-load",
        parents=[base_parser],
        help="Perform a historical backfill from a start date",
    )
    initial.set_defaults(mode="initial-load")

    delta = subparsers.add_parser(
        "delta",
        parents=[base_parser],
        help="Fetch recent changes over a moving window (default 7 days)",
    )
    delta.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Number of trailing days to sync when start date omitted",
    )
    delta.set_defaults(mode="delta")

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_start_date(args)

    asyncio.run(_run_sync_command(args))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()

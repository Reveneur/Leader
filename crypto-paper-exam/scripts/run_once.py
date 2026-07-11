#!/usr/bin/env python3
"""Runs exactly one hourly cycle for a given (or the current) hour. Useful
for manual testing and for catching up a single missed hour; the scheduler
itself calls scheduler.run_hourly the same way.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from database.connection import init_db  # noqa: E402
from reporting.hourly_report import render_hourly_report  # noqa: E402
from scheduler import run_hourly  # noqa: E402
from settings import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hour",
        type=str,
        default=None,
        help="ISO timestamp for the scheduled hour (default: current hour, UTC).",
    )
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings)

    if args.hour:
        scheduled = dt.datetime.fromisoformat(args.hour)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=dt.timezone.utc)
    else:
        scheduled = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)

    outcome = run_hourly(scheduled, settings=settings)
    if outcome.already_completed:
        print(f"Run {outcome.run.run_id} was already completed; no action taken.")
    else:
        print(render_hourly_report(outcome.run))
        if outcome.errors:
            print(f"\nErrors during this run: {outcome.errors}")


if __name__ == "__main__":
    main()

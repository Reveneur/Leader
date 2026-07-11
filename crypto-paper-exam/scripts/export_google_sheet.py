#!/usr/bin/env python3
"""Re-exports hourly runs to Google Sheets — the retry path referenced in
spec section 15/18: a Sheets failure never blocks trading, and this script
can be re-run safely (dedup is by Run-ID, the sheet's last column).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from database.connection import init_db, session_scope  # noqa: E402
from database.repositories import list_hourly_runs, signal_scores_for_run, upsert_hourly_run  # noqa: E402
from reporting.google_sheets import export_run  # noqa: E402
from settings import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="Re-export every run, not just ones with sheet_status != OK."
    )
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        runs = list_hourly_runs(session)
        pending = runs if args.all else [r for r in runs if r.sheet_status != "OK"]
        print(f"Exporting {len(pending)} run(s) ...")

        for run in pending:
            scores = signal_scores_for_run(session, run.run_id)
            top_score = scores[0] if scores else None
            ok, error = export_run(run, top_score, settings)
            run.sheet_status = "OK" if ok else "RETRY_QUEUED"
            upsert_hourly_run(session, run)
            print(f"  {run.run_id}: {'OK' if ok else f'FAILED ({error})'}")


if __name__ == "__main__":
    main()

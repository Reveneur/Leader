#!/usr/bin/env python3
"""Runs the audit.integrity checks over the persisted exam data and prints
a pass/fail report (spec section 23's "Audittests" and section 24's
acceptance criteria). Exits non-zero if any ERROR/CRITICAL finding exists.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from audit.config_freeze import load_strategy_config  # noqa: E402
from audit.integrity import run_integrity_checks  # noqa: E402
from database.connection import init_db, session_scope  # noqa: E402
from settings import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-missing-hours", action="store_true", help="Also check for missing hourly rows across the exam window.")
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings)

    exam_start = exam_end = None
    if args.check_missing_hours:
        config = load_strategy_config(settings.strategy_config_path)
        exam_start = dt.datetime.fromisoformat(config.exam.start)
        exam_end = dt.datetime.fromisoformat(config.exam.end)

    with session_scope(settings) as session:
        report = run_integrity_checks(session, exam_start, exam_end)

    if not report.findings:
        print("No integrity findings. The exam ledger is clean.")
        sys.exit(0)

    for finding in report.findings:
        print(f"[{finding.severity}] {finding.check}: {finding.description}")

    print(f"\n{len(report.findings)} finding(s); clean={report.is_clean}")
    sys.exit(0 if report.is_clean else 1)


if __name__ == "__main__":
    main()

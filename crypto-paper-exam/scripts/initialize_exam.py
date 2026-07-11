#!/usr/bin/env python3
"""Initializes a fresh Exam V1 run (spec section 25's 'examenreset'):
creates/clears the database schema, freezes config/exam_v1.yaml, and
records the wallet's administrative start. Run this exactly once before a
new exam period begins.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from audit.config_freeze import freeze_config  # noqa: E402
from audit.auditor import Auditor  # noqa: E402
from database.connection import init_db, session_scope  # noqa: E402
from database.migrations import drop_schema  # noqa: E402
from database.repositories import active_config_freeze  # noqa: E402
from settings import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="Drop and recreate the schema even if data already exists."
    )
    args = parser.parse_args()

    settings = get_settings()

    if args.reset:
        print(f"Resetting database at {settings.database_path} ...")
        init_db(settings)
        drop_schema()

    init_db(settings)

    with session_scope(settings) as session:
        existing = active_config_freeze(session)
        if existing is not None and not args.reset:
            print(
                f"Config already frozen (hash={existing.config_hash[:12]}..., "
                f"strategy_version={existing.strategy_version}). Use --reset to re-freeze."
            )
            return
        freeze = freeze_config(session, settings.strategy_config_path)
        Auditor(session).log(
            "exam_initialized",
            f"Exam initialized with strategy_version={freeze.strategy_version}, config_hash={freeze.config_hash}",
        )
        print(f"Database ready at {settings.database_path}")
        print(f"Config frozen: strategy_version={freeze.strategy_version}, hash={freeze.config_hash}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backfills candle history for the configured market universe, across all
four intervals used by the strategy (1m, 15m, 1h, 4h — spec section 4.1).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from data.bitvavo_client import BitvavoClient  # noqa: E402
from data.candle_repository import INTERVALS, safe_refresh  # noqa: E402
from database.connection import init_db, session_scope  # noqa: E402
from settings import get_settings  # noqa: E402


def load_universe(markets_config_path: Path) -> list[str]:
    data = yaml.safe_load(markets_config_path.read_text())
    return data.get("universe", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", nargs="*", help="Override the market list from config/markets.yaml.")
    parser.add_argument("--limit", type=int, default=1440, help="Candles per market/interval to fetch.")
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings)

    markets = args.markets or load_universe(settings.markets_config_path)
    print(f"Backfilling {len(markets)} market(s) x {len(INTERVALS)} interval(s) ...")

    with BitvavoClient() as client, session_scope(settings) as session:
        for market in markets:
            for interval in INTERVALS:
                ok, err = safe_refresh(session, client, market, interval, limit=args.limit)
                status = "OK" if ok else f"FAILED ({err})"
                print(f"  {market} {interval}: {status}")


if __name__ == "__main__":
    main()

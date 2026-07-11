"""Fetches candles from Bitvavo and persists them via
database.repositories, and provides read access for strategy/execution
code. The database is the source of truth for anything already fetched —
this module re-fetches only what's missing.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from data.bitvavo_client import BitvavoClient, MarketDataError
from database.models import Candle
from database.repositories import candles_between, latest_candle, upsert_candle

INTERVALS = ("1m", "15m", "1h", "4h")


def _parse_raw_candle(market: str, interval: str, raw: list) -> Candle:
    timestamp_ms, open_, high, low, close, volume = raw
    return Candle(
        market=market,
        interval=interval,
        timestamp=dt.datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=dt.timezone.utc),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
        source="bitvavo",
    )


def fetch_and_store_candles(
    session: Session,
    client: BitvavoClient,
    market: str,
    interval: str,
    limit: int = 1440,
) -> int:
    """Returns the number of candles stored. Raises MarketDataError on
    network failure — callers must catch this and record a data_status
    (spec section 17), never silently substitute fabricated candles.
    """
    raw_candles = client.get_candles(market, interval, limit=limit)
    count = 0
    for raw in raw_candles:
        candle = _parse_raw_candle(market, interval, raw)
        upsert_candle(session, candle)
        count += 1
    return count


def get_candles(
    session: Session, market: str, interval: str, start: dt.datetime, end: dt.datetime
) -> list[Candle]:
    return candles_between(session, market, interval, start, end)


def get_latest_candle(session: Session, market: str, interval: str) -> Candle | None:
    return latest_candle(session, market, interval)


def safe_refresh(
    session: Session, client: BitvavoClient, market: str, interval: str, limit: int = 1440
) -> tuple[bool, str | None]:
    """Never raises. Returns (ok, error_message) so a scheduler run can
    continue with stale-but-known data rather than aborting entirely.
    """
    try:
        fetch_and_store_candles(session, client, market, interval, limit=limit)
        return True, None
    except MarketDataError as exc:
        return False, str(exc)

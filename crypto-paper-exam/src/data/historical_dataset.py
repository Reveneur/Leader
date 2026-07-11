"""Loads real historical OHLCV data committed directly to a public GitHub
repo, for backtesting only. This is NOT part of the live engine's data path
— the live engine's only market data source is Bitvavo
(data/bitvavo_client.py). See scripts/backtest.py for how this is used.

Source: ff137/bitstamp-btcusd-minute-data — real Bitstamp BTC/USD 1-minute
trade-derived OHLCV, updated daily, no missing minutes/duplicates/nulls
(verified against the repo's own README claims at integration time).
"""
from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

BTC_USD_1M_URL = (
    "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/"
    "main/data/updates/btcusd_bitstamp_1min_latest.csv"
)


class HistoricalDataError(RuntimeError):
    pass


@dataclass(slots=True)
class HistoricalCandle:
    timestamp: dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def fetch_btc_usd_1m(cache_path: Path, force_refresh: bool = False, url: str = BTC_USD_1M_URL) -> Path:
    """Downloads the dataset to cache_path unless it already exists. Only
    hits the network once per cache_path — re-run with force_refresh=True
    to pick up new daily updates.
    """
    if cache_path.exists() and not force_refresh:
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    except OSError as exc:
        raise HistoricalDataError(f"failed to download {url}: {exc}") from exc
    cache_path.write_bytes(data)
    return cache_path


def load_1m_candles(
    csv_path: Path, start: dt.datetime | None = None, end: dt.datetime | None = None
) -> list[HistoricalCandle]:
    candles: list[HistoricalCandle] = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = dt.datetime.fromtimestamp(int(row["timestamp"]), tz=dt.timezone.utc)
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                break
            candles.append(
                HistoricalCandle(
                    timestamp=ts,
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            )
    if not candles:
        raise HistoricalDataError(f"no candles loaded from {csv_path} in range {start}..{end}")
    return candles


def resample(candles: list[HistoricalCandle], minutes: int) -> list[HistoricalCandle]:
    """Dependency-free resampling to a coarser interval, bucketed on epoch
    time so bucket boundaries are stable regardless of the input's start
    time (e.g. every 1h candle starts on the hour).
    """
    if not candles:
        return []
    bucket_seconds = minutes * 60
    buckets: dict[int, list[HistoricalCandle]] = {}
    for c in candles:
        key = int(c.timestamp.timestamp()) // bucket_seconds
        buckets.setdefault(key, []).append(c)

    result = []
    for key in sorted(buckets):
        group = buckets[key]
        result.append(
            HistoricalCandle(
                timestamp=dt.datetime.fromtimestamp(key * bucket_seconds, tz=dt.timezone.utc),
                open=group[0].open,
                high=max(g.high for g in group),
                low=min(g.low for g in group),
                close=group[-1].close,
                volume=sum(g.volume for g in group),
            )
        )
    return result

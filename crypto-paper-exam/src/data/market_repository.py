"""Builds execution-ready MarketSnapshots from live Bitvavo data and applies
the liquidity screen from spec section 8 — Bitvavo is the reference for
tradable EUR pairs, executable price, spread, and liquidity.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from audit.config_freeze import LiquidityConfig
from data.bitvavo_client import BitvavoClient, MarketDataError
from execution.paper_broker import MarketSnapshot


@dataclass
class LiquidityCheck:
    eligible: bool
    reasons: list[str]


def fetch_market_snapshot(client: BitvavoClient, market: str) -> MarketSnapshot | None:
    """Returns None (never a fabricated snapshot) if any required field is
    unavailable — callers must treat that as missing data (spec section 17).
    """
    try:
        book = client.get_ticker_book(market)
        stats_24h = client.get_ticker_24h(market)
    except MarketDataError:
        return None

    if not book or not stats_24h:
        return None

    book_entry = book[0]
    stats_entry = stats_24h[0]

    bid_raw, ask_raw = book_entry.get("bid"), book_entry.get("ask")
    if bid_raw is None or ask_raw is None:
        return None

    bid, ask = Decimal(str(bid_raw)), Decimal(str(ask_raw))
    if bid <= 0 or ask <= 0 or ask < bid:
        return None

    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100

    last_raw = stats_entry.get("last")
    last = Decimal(str(last_raw)) if last_raw is not None else mid

    volume_base = stats_entry.get("volume")
    volume_24h_eur = Decimal(str(volume_base)) * last if volume_base is not None else None

    bid_size = book_entry.get("bidSize")
    ask_size = book_entry.get("askSize")
    book_depth_eur = None
    if bid_size is not None and ask_size is not None:
        book_depth_eur = min(Decimal(str(bid_size)) * bid, Decimal(str(ask_size)) * ask)

    return MarketSnapshot(
        market=market,
        timestamp=dt.datetime.now(dt.timezone.utc),
        bid=bid,
        ask=ask,
        last=last,
        spread_pct=spread_pct,
        volume_24h_eur=volume_24h_eur,
        book_depth_eur=book_depth_eur,
    )


def check_liquidity(
    snapshot: MarketSnapshot, config: LiquidityConfig, market_history_days: int | None = None
) -> LiquidityCheck:
    reasons = []
    if snapshot.volume_24h_eur is None or snapshot.volume_24h_eur < config.min_24h_volume_eur:
        reasons.append("24h volume below minimum")
    if snapshot.spread_pct > config.max_spread_pct:
        reasons.append("spread above maximum")
    if snapshot.book_depth_eur is None or snapshot.book_depth_eur < config.min_book_depth_eur:
        reasons.append("order book depth below minimum")
    if market_history_days is not None and market_history_days < config.min_market_history_days:
        reasons.append("market history too short")
    return LiquidityCheck(eligible=not reasons, reasons=reasons)


def get_eligible_universe(
    client: BitvavoClient, candidate_markets: list[str], config: LiquidityConfig
) -> dict[str, tuple[MarketSnapshot | None, LiquidityCheck]]:
    results: dict[str, tuple[MarketSnapshot | None, LiquidityCheck]] = {}
    for market in candidate_markets:
        snapshot = fetch_market_snapshot(client, market)
        if snapshot is None:
            results[market] = (None, LiquidityCheck(False, ["no market data available"]))
            continue
        check = check_liquidity(snapshot, config)
        results[market] = (snapshot, check)
    return results

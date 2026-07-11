"""Market Regime Agent (spec section 9.1). Classifies BTC's regime from
multi-timeframe trend + realized volatility, and scores how well a
candidate asset's setup fits that regime (component #1 of section 10).
"""
from __future__ import annotations

from decimal import Decimal
from statistics import pstdev

REGIMES = ("TREND-UP", "RANGE", "TREND-DOWN", "SHOCK")

TREND_THRESHOLD_PCT = Decimal("1.0")
SHOCK_VOLATILITY_PCT = Decimal("5.0")


def trend_direction(closes: list[Decimal]) -> str:
    if len(closes) < 2 or closes[0] == 0:
        return "FLAT"
    change_pct = (closes[-1] - closes[0]) / closes[0] * 100
    if change_pct >= TREND_THRESHOLD_PCT:
        return "UP"
    if change_pct <= -TREND_THRESHOLD_PCT:
        return "DOWN"
    return "FLAT"


def realized_volatility_pct(closes: list[Decimal]) -> Decimal:
    if len(closes) < 2:
        return Decimal("0")
    returns = [
        float((closes[i] - closes[i - 1]) / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] != 0
    ]
    if not returns:
        return Decimal("0")
    return Decimal(str(pstdev(returns) * 100))


def classify_market_regime(
    btc_closes_15m: list[Decimal],
    btc_closes_1h: list[Decimal],
    btc_closes_4h: list[Decimal],
) -> str:
    volatility = realized_volatility_pct(btc_closes_15m)
    if volatility >= SHOCK_VOLATILITY_PCT:
        return "SHOCK"

    directions = [
        trend_direction(btc_closes_15m),
        trend_direction(btc_closes_1h),
        trend_direction(btc_closes_4h),
    ]
    if all(d == "UP" for d in directions):
        return "TREND-UP"
    if all(d == "DOWN" for d in directions):
        return "TREND-DOWN"
    return "RANGE"


def regime_fit_score(regime: str, asset_shows_relative_strength: bool) -> int:
    base_score = {"TREND-UP": 8, "RANGE": 5, "TREND-DOWN": 2, "SHOCK": 1}[regime]
    if asset_shows_relative_strength and regime in ("TREND-UP", "RANGE"):
        base_score = min(10, base_score + 1)
    if regime == "TREND-DOWN" and not asset_shows_relative_strength:
        base_score = max(0, base_score - 1)
    return base_score

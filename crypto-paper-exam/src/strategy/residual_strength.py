"""Residual Strength Agent (spec section 9.2). Isolates the part of an
asset's move that is not explained by BTC/ETH beta — munt-specifieke
kracht, not a market-wide rally.
"""
from __future__ import annotations

from decimal import Decimal


def period_return_pct(closes: list[Decimal]) -> Decimal:
    if len(closes) < 2 or closes[0] == 0:
        return Decimal("0")
    return (closes[-1] - closes[0]) / closes[0] * 100


def expected_return_pct(btc_closes: list[Decimal], eth_closes: list[Decimal]) -> Decimal:
    """Simple equal-weight proxy for expected co-movement — no regression
    beta is fit (an explicit simplification for Exam V1's deterministic,
    auditable scoring; a future version could fit true beta).
    """
    btc_return = period_return_pct(btc_closes)
    eth_return = period_return_pct(eth_closes)
    return (btc_return + eth_return) / 2


def compute_residual_return_pct(
    asset_closes: list[Decimal], btc_closes: list[Decimal], eth_closes: list[Decimal]
) -> Decimal:
    return period_return_pct(asset_closes) - expected_return_pct(btc_closes, eth_closes)


def is_persistent(residual_series: list[Decimal], min_positive_fraction: Decimal = Decimal("0.6")) -> bool:
    """A single positive residual bar is not enough — section 9.2 requires
    checking that the outperformance persists across the lookback.
    """
    if not residual_series:
        return False
    positive = sum(1 for r in residual_series if r > 0)
    return Decimal(positive) / Decimal(len(residual_series)) >= min_positive_fraction


def residual_strength_score(
    residual_return_pct: Decimal, persistent: bool, volume_confirmed: bool
) -> int:
    if residual_return_pct <= 0:
        return 0
    # 0-10 pts scaled off residual return, capped, then gated by
    # persistence/volume confirmation per spec section 9.2.
    raw = min(Decimal("10"), residual_return_pct * Decimal("2"))
    if not persistent:
        raw = min(raw, Decimal("5"))
    if not volume_confirmed:
        raw = min(raw, Decimal("6"))
    return int(raw)

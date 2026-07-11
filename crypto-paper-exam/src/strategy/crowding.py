"""Crowding Agent (spec section 9.7). Exam V1 only trades spot, but
derivatives data can still warn that a move is already over-leveraged on
the long side. Missing derivatives data is treated as neutral (score 6),
not as a red flag — Exam V1 does not require this data to trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CrowdingSignals:
    funding_rate_pct: Decimal | None
    open_interest_change_pct: Decimal | None
    long_short_ratio: Decimal | None


NEUTRAL_SCORE = 6


def crowding_quality_score(signals: CrowdingSignals) -> int:
    if signals.funding_rate_pct is None and signals.open_interest_change_pct is None and signals.long_short_ratio is None:
        return NEUTRAL_SCORE

    score = 10
    if signals.funding_rate_pct is not None and signals.funding_rate_pct > Decimal("0.05"):
        score -= 4  # expensive to be long => crowded
    if signals.open_interest_change_pct is not None and signals.open_interest_change_pct > Decimal("20"):
        score -= 3  # rapid leverage build-up
    if signals.long_short_ratio is not None and signals.long_short_ratio > Decimal("2"):
        score -= 3  # heavily skewed long

    return max(0, score)


def has_critical_crowding_risk(signals: CrowdingSignals) -> bool:
    return crowding_quality_score(signals) <= 2

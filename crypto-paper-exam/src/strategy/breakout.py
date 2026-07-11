"""Breakout Quality Agent (spec section 9.4)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class BreakoutContext:
    close: Decimal
    resistance: Decimal
    avg_volume: Decimal
    current_volume: Decimal
    retested: bool
    already_extended_pct: Decimal  # how far price has run since the breakout, without a retest


def breakout_quality_score(ctx: BreakoutContext) -> int:
    if ctx.resistance <= 0 or ctx.close <= ctx.resistance:
        return 0  # no breakout at all

    distance_pct = (ctx.close - ctx.resistance) / ctx.resistance * 100
    volume_ratio = ctx.current_volume / ctx.avg_volume if ctx.avg_volume > 0 else Decimal("0")

    score = Decimal("0")
    score += min(Decimal("4"), distance_pct)  # up to 4 pts for a clean, meaningful break
    score += min(Decimal("3"), (volume_ratio - 1) * 3) if volume_ratio > 1 else Decimal("0")
    score += Decimal("3") if ctx.retested else Decimal("0")

    # Late entries with no retest and an already-extended move are
    # penalized — chasing an unfavorable entry (spec section 9.4).
    if not ctx.retested and ctx.already_extended_pct > Decimal("8"):
        score -= Decimal("3")

    return max(0, min(10, int(score)))

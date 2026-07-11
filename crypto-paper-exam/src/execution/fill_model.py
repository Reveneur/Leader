"""Determines how much of a requested order can realistically be filled
given available liquidity (spec section 3: "gedeeltelijke of niet-
uitgevoerde limietorders", section 8: max order impact of 50 EUR).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class FillDecision:
    status: str  # FILLED, PARTIAL, REJECTED
    fillable_eur: Decimal
    reason: str | None = None


def determine_fill(
    requested_eur: Decimal,
    book_depth_eur: Decimal | None,
    max_impact_eur: Decimal,
) -> FillDecision:
    if requested_eur <= 0:
        return FillDecision("REJECTED", Decimal("0"), "requested amount is not positive")

    # No orderbook data: assume full liquidity for an order this small,
    # since Exam V1 caps position size at max_impact_eur-scale amounts
    # anyway (spec section 8's own liquidity screen already filtered out
    # illiquid markets before we get here).
    if book_depth_eur is None:
        return FillDecision("FILLED", requested_eur, "no orderbook depth data; assumed fillable")

    if book_depth_eur <= 0:
        return FillDecision("REJECTED", Decimal("0"), "no liquidity available")

    fillable = min(requested_eur, book_depth_eur)
    if fillable < requested_eur:
        return FillDecision("PARTIAL", fillable, "insufficient depth for full size")
    return FillDecision("FILLED", fillable, None)

"""Intrahour reconstruction using 1-minute candles (spec section 7).

Determines whether a stop-loss, target, or trailing stop was touched during
the elapsed hour, and in what order. When a stop and a target both fall
within the same 1-minute candle and finer data cannot disambiguate them,
the conservative rule applies: the stop is deemed to have been hit first
(spec section 7's explicit anti-self-favoring rule).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from database.models import Candle, Position


@dataclass
class IntrahourEvent:
    kind: str  # STOP, TARGET_1, TARGET_2, TRAILING_STOP
    trigger_price: Decimal
    fill_price: Decimal
    candle_timestamp: object


@dataclass
class IntrahourResult:
    event: IntrahourEvent | None
    mfe_pct: Decimal
    mae_pct: Decimal


def _parse_trailing_pct(trailing_rule: str | None) -> Decimal | None:
    if not trailing_rule:
        return None
    try:
        data = json.loads(trailing_rule)
    except (json.JSONDecodeError, TypeError):
        return None
    value = data.get("trail_pct")
    return Decimal(str(value)) if value is not None else None


def evaluate_intrahour(
    position: Position,
    candles_1m: list[Candle],
    ambiguous_rule: str = "stop_first",
) -> IntrahourResult:
    entry = position.entry_price
    hard_stop = position.stop_price
    target_1 = position.target_1
    target_2 = position.target_2
    trail_pct = _parse_trailing_pct(position.trailing_rule)

    ordered = sorted(candles_1m, key=lambda c: c.timestamp)

    peak = entry
    trough = entry
    effective_stop = hard_stop

    for candle in ordered:
        peak = max(peak, candle.high)
        if trail_pct is not None:
            trailing_price = peak * (Decimal("1") - trail_pct / Decimal("100"))
            effective_stop = max(effective_stop, trailing_price)

        stop_hit = candle.low <= effective_stop
        target_1_hit = target_1 is not None and candle.high >= target_1
        target_2_hit = target_2 is not None and candle.high >= target_2

        if stop_hit and (target_1_hit or target_2_hit):
            if ambiguous_rule != "stop_first":
                raise NotImplementedError("only the stop_first tie-break rule is supported")
            fill_price = candle.open if candle.open < effective_stop else effective_stop
            kind = "TRAILING_STOP" if effective_stop > hard_stop else "STOP"
            return IntrahourResult(
                IntrahourEvent(kind, effective_stop, fill_price, candle.timestamp),
                mfe_pct=_pct(peak, entry, favorable=True),
                mae_pct=_pct(trough, entry, favorable=False),
            )

        if stop_hit:
            fill_price = candle.open if candle.open < effective_stop else effective_stop
            kind = "TRAILING_STOP" if effective_stop > hard_stop else "STOP"
            trough = min(trough, candle.low)
            return IntrahourResult(
                IntrahourEvent(kind, effective_stop, fill_price, candle.timestamp),
                mfe_pct=_pct(peak, entry, favorable=True),
                mae_pct=_pct(trough, entry, favorable=False),
            )

        if target_2_hit:
            fill_price = candle.open if candle.open > target_2 else target_2
            return IntrahourResult(
                IntrahourEvent("TARGET_2", target_2, fill_price, candle.timestamp),
                mfe_pct=_pct(peak, entry, favorable=True),
                mae_pct=_pct(trough, entry, favorable=False),
            )

        if target_1_hit:
            fill_price = candle.open if candle.open > target_1 else target_1
            return IntrahourResult(
                IntrahourEvent("TARGET_1", target_1, fill_price, candle.timestamp),
                mfe_pct=_pct(peak, entry, favorable=True),
                mae_pct=_pct(trough, entry, favorable=False),
            )

        trough = min(trough, candle.low)

    return IntrahourResult(
        event=None,
        mfe_pct=_pct(peak, entry, favorable=True),
        mae_pct=_pct(trough, entry, favorable=False),
    )


def _pct(extreme: Decimal, entry: Decimal, favorable: bool) -> Decimal:
    if entry == 0:
        return Decimal("0")
    if favorable:
        value = (extreme - entry) / entry * 100
    else:
        value = (entry - extreme) / entry * 100
    return max(value, Decimal("0"))

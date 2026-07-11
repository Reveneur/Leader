"""Position lifecycle: open (spec section 12's full pre-trade registration),
mark-to-market valuation (section 5), and close (section 13's full
post-trade registration).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Position
from database.repositories import add_position, open_positions
from portfolio.accounting import eur_to_cents, estimate_executable_sell_value
from portfolio.wallet import HoldingsValuation


@dataclass
class PositionOpenRequest:
    asset: str
    market: str
    strategy_version: str
    opened_at: dt.datetime
    entry_price: Decimal
    entry_units: Decimal
    gross_spend_eur_cents: int
    entry_fee_eur_cents: int
    entry_slippage_eur_cents: int
    entry_spread_pct: Decimal
    entry_order_type: str
    stop_price: Decimal
    target_1: Decimal | None
    target_2: Decimal | None
    trailing_rule: str | None
    regime_at_entry: str | None
    scores: dict | None
    contradictions: list[str] | None
    missing_data: list[str] | None
    catalyst: str | None
    onchain_confirmation: str | None
    thesis: str | None
    expected_hold_period: str | None
    max_eur_risk_cents: int
    expected_gross_profit_eur_cents: int
    expected_net_profit_eur_cents: int
    net_reward_risk: Decimal
    confidence: Decimal
    invalidation_criterion: str | None
    sources: list[str] | None


def entry_total_cost_cents(position: Position) -> int:
    return position.gross_spend_eur_cents + position.entry_fee_eur_cents + position.entry_slippage_eur_cents


def open_position(session: Session, req: PositionOpenRequest) -> Position:
    position = Position(
        asset=req.asset,
        market=req.market,
        status="OPEN",
        strategy_version=req.strategy_version,
        opened_at=req.opened_at,
        closed_at=None,
        entry_price=req.entry_price,
        entry_units=req.entry_units,
        gross_spend_eur_cents=req.gross_spend_eur_cents,
        entry_fee_eur_cents=req.entry_fee_eur_cents,
        entry_slippage_eur_cents=req.entry_slippage_eur_cents,
        entry_spread_pct=req.entry_spread_pct,
        entry_order_type=req.entry_order_type,
        stop_price=req.stop_price,
        target_1=req.target_1,
        target_2=req.target_2,
        trailing_rule=req.trailing_rule,
        remaining_units=req.entry_units,
        current_value_eur_cents=req.gross_spend_eur_cents,
        realized_pnl_eur_cents=0,
        unrealized_pnl_eur_cents=0,
        regime_at_entry=req.regime_at_entry,
        scores_json=json.dumps(req.scores) if req.scores else None,
        contradictions_json=json.dumps(req.contradictions) if req.contradictions else None,
        missing_data_json=json.dumps(req.missing_data) if req.missing_data else None,
        catalyst=req.catalyst,
        onchain_confirmation=req.onchain_confirmation,
        thesis=req.thesis,
        expected_hold_period=req.expected_hold_period,
        max_eur_risk_cents=req.max_eur_risk_cents,
        expected_gross_profit_eur_cents=req.expected_gross_profit_eur_cents,
        expected_net_profit_eur_cents=req.expected_net_profit_eur_cents,
        net_reward_risk=req.net_reward_risk,
        confidence=req.confidence,
        invalidation_criterion=req.invalidation_criterion,
        sources_json=json.dumps(req.sources) if req.sources else None,
    )
    return add_position(session, position)


@dataclass
class PositionCloseRequest:
    closed_at: dt.datetime
    sell_reason: str
    exit_price: Decimal
    exit_spread_pct: Decimal
    exit_slippage_eur_cents: int
    exit_fee_eur_cents: int
    net_proceeds_eur_cents: int
    units_sold: Decimal
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    correct_signals: list[str] | None
    wrong_signals: list[str] | None
    classification: str  # CORRECT, WRONG, UNRESOLVED


def close_position(session: Session, position: Position, req: PositionCloseRequest) -> Position:
    """Supports full or partial exits. When units_sold < remaining_units the
    position stays OPEN with the remainder; cost basis is allocated pro-rata.
    """
    if req.units_sold > position.remaining_units:
        raise ValueError("cannot sell more units than remain in the position")

    fraction = req.units_sold / position.remaining_units
    allocated_entry_cost = int(round(entry_total_cost_cents(position) * float(fraction)))
    realized = req.net_proceeds_eur_cents - allocated_entry_cost

    position.realized_pnl_eur_cents = (position.realized_pnl_eur_cents or 0) + realized
    position.remaining_units -= req.units_sold
    position.sell_reason = req.sell_reason
    position.exit_price = req.exit_price
    position.exit_spread_pct = req.exit_spread_pct
    position.exit_slippage_eur_cents = (position.exit_slippage_eur_cents or 0) + req.exit_slippage_eur_cents
    position.exit_fee_eur_cents = (position.exit_fee_eur_cents or 0) + req.exit_fee_eur_cents
    position.net_proceeds_eur_cents = (position.net_proceeds_eur_cents or 0) + req.net_proceeds_eur_cents
    position.mfe_pct = req.mfe_pct
    position.mae_pct = req.mae_pct
    position.correct_signals_json = json.dumps(req.correct_signals) if req.correct_signals else None
    position.wrong_signals_json = json.dumps(req.wrong_signals) if req.wrong_signals else None
    position.classification = req.classification

    if position.remaining_units <= Decimal("0"):
        position.status = "CLOSED"
        position.closed_at = req.closed_at
        position.remaining_units = Decimal("0")
        position.current_value_eur_cents = 0
        position.unrealized_pnl_eur_cents = 0
        position.result_pct = (
            (Decimal(position.realized_pnl_eur_cents) / Decimal(entry_total_cost_cents(position))) * 100
            if entry_total_cost_cents(position) != 0
            else Decimal("0")
        )
        position.duration_seconds = int((position.closed_at - position.opened_at).total_seconds())

    return position


def value_open_position(
    position: Position, bid_price: Decimal, fee_pct: Decimal, slippage_pct: Decimal
) -> tuple[int, int]:
    """Returns (current_value_eur_cents, unrealized_pnl_eur_cents) for the
    remaining units, marked to the estimated executable sell value.
    """
    net_value_eur = estimate_executable_sell_value(
        position.remaining_units, bid_price, fee_pct, slippage_pct
    )
    current_value_cents = eur_to_cents(net_value_eur)

    fraction = (
        position.remaining_units / position.entry_units if position.entry_units else Decimal("0")
    )
    allocated_cost_basis = int(round(entry_total_cost_cents(position) * float(fraction)))
    unrealized_pnl_cents = current_value_cents - allocated_cost_basis
    return current_value_cents, unrealized_pnl_cents


def value_all_open_positions(
    session: Session,
    bid_prices: dict[str, Decimal],
    fee_pct: Decimal,
    slippage_pct: Decimal,
) -> HoldingsValuation:
    total_value = 0
    total_unrealized = 0
    for position in open_positions(session):
        bid_price = bid_prices.get(position.market)
        if bid_price is None:
            # Missing data for an open position: keep the last known value
            # rather than inventing a price (spec section 17 — conservative
            # fallback, no fabricated marks).
            total_value += position.current_value_eur_cents
            total_unrealized += position.unrealized_pnl_eur_cents
            continue
        value_cents, unrealized_cents = value_open_position(position, bid_price, fee_pct, slippage_pct)
        position.current_value_eur_cents = value_cents
        position.unrealized_pnl_eur_cents = unrealized_cents
        total_value += value_cents
        total_unrealized += unrealized_cents
    return HoldingsValuation(holdings_value_cents=total_value, unrealized_pnl_cents=total_unrealized)

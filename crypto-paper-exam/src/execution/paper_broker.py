"""Simulates order execution as if it happened on Bitvavo (spec section
4.3). This is the only place that turns a trading decision into an Order
row, a Position mutation, and — via Wallet's order-replay design — a cash
movement, all inside the caller's transaction.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from audit.config_freeze import StrategyConfig
from database.models import Order, Position
from database.repositories import add_order
from execution.fee_model import MakerEligibility, determine_fee_pct
from execution.fill_model import determine_fill
from execution.slippage_model import estimate_slippage_pct
from portfolio import accounting
from portfolio.positions import PositionCloseRequest, PositionOpenRequest, close_position, open_position


@dataclass
class MarketSnapshot:
    market: str
    timestamp: dt.datetime
    bid: Decimal
    ask: Decimal
    last: Decimal
    spread_pct: Decimal
    volume_24h_eur: Decimal | None = None
    book_depth_eur: Decimal | None = None


class InsufficientCashError(RuntimeError):
    pass


@dataclass
class PositionPlan:
    """The full pre-trade registration required by spec section 12, minus
    the fields the broker itself determines at fill time (price, units,
    fees, slippage).
    """

    asset: str
    strategy_version: str
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


def execute_buy(
    session: Session,
    run_id: str,
    config: StrategyConfig,
    snapshot: MarketSnapshot,
    requested_eur: Decimal,
    available_cash_eur: Decimal,
    plan: PositionPlan,
    order_type: str = "TAKER",
    maker_eligibility: MakerEligibility | None = None,
) -> Order:
    fee_pct = determine_fee_pct(order_type, config.execution, maker_eligibility)
    fill = determine_fill(requested_eur, snapshot.book_depth_eur, config.liquidity.max_impact_eur)
    if fill.status == "REJECTED":
        order = Order(
            run_id=run_id,
            position_id=None,
            side="BUY",
            order_type=order_type,
            requested_price=snapshot.ask,
            executed_price=None,
            units=Decimal("0"),
            gross_value_eur_cents=0,
            fee_eur_cents=0,
            slippage_eur_cents=0,
            status="REJECTED",
            created_at=snapshot.timestamp,
            filled_at=None,
        )
        return add_order(session, order)

    gross_eur = fill.fillable_eur
    slippage_pct = estimate_slippage_pct(gross_eur, "BUY", config.execution, snapshot.book_depth_eur)
    total_cost_eur, fee_eur, slippage_eur = accounting.apply_buy_costs(gross_eur, fee_pct, slippage_pct)

    if total_cost_eur > available_cash_eur:
        raise InsufficientCashError(
            f"buy of {total_cost_eur} EUR exceeds available cash {available_cash_eur} EUR"
        )

    units = gross_eur / snapshot.ask
    executed_price = (gross_eur + slippage_eur) / units

    order = Order(
        run_id=run_id,
        position_id=None,
        side="BUY",
        order_type=order_type,
        requested_price=snapshot.ask,
        executed_price=executed_price,
        units=units,
        gross_value_eur_cents=accounting.eur_to_cents(gross_eur),
        fee_eur_cents=accounting.eur_to_cents(fee_eur),
        slippage_eur_cents=accounting.eur_to_cents(slippage_eur),
        status=fill.status,
        created_at=snapshot.timestamp,
        filled_at=snapshot.timestamp,
    )
    add_order(session, order)

    open_req = PositionOpenRequest(
        asset=plan.asset,
        market=snapshot.market,
        strategy_version=plan.strategy_version,
        opened_at=snapshot.timestamp,
        entry_price=executed_price,
        entry_units=units,
        gross_spend_eur_cents=accounting.eur_to_cents(gross_eur),
        entry_fee_eur_cents=accounting.eur_to_cents(fee_eur),
        entry_slippage_eur_cents=accounting.eur_to_cents(slippage_eur),
        entry_spread_pct=snapshot.spread_pct,
        entry_order_type=order_type,
        stop_price=plan.stop_price,
        target_1=plan.target_1,
        target_2=plan.target_2,
        trailing_rule=plan.trailing_rule,
        regime_at_entry=plan.regime_at_entry,
        scores=plan.scores,
        contradictions=plan.contradictions,
        missing_data=plan.missing_data,
        catalyst=plan.catalyst,
        onchain_confirmation=plan.onchain_confirmation,
        thesis=plan.thesis,
        expected_hold_period=plan.expected_hold_period,
        max_eur_risk_cents=plan.max_eur_risk_cents,
        expected_gross_profit_eur_cents=plan.expected_gross_profit_eur_cents,
        expected_net_profit_eur_cents=plan.expected_net_profit_eur_cents,
        net_reward_risk=plan.net_reward_risk,
        confidence=plan.confidence,
        invalidation_criterion=plan.invalidation_criterion,
        sources=plan.sources,
    )
    position = open_position(session, open_req)
    order.position_id = position.id
    return order


def execute_sell(
    session: Session,
    run_id: str,
    config: StrategyConfig,
    snapshot: MarketSnapshot,
    position: Position,
    units_to_sell: Decimal,
    sell_reason: str,
    classification: str = "UNRESOLVED",
    order_type: str = "TAKER",
    maker_eligibility: MakerEligibility | None = None,
    mfe_pct: Decimal | None = None,
    mae_pct: Decimal | None = None,
    correct_signals: list[str] | None = None,
    wrong_signals: list[str] | None = None,
    override_price: Decimal | None = None,
) -> Order:
    """override_price lets the stop/target engine's conservative fill price
    (which may differ from the current snapshot bid, e.g. a gap-through)
    drive the executed price, while fees/slippage still apply on top.
    """
    reference_price = override_price if override_price is not None else snapshot.bid
    fee_pct = determine_fee_pct(order_type, config.execution, maker_eligibility)
    gross_eur = units_to_sell * reference_price
    slippage_pct = estimate_slippage_pct(gross_eur, "SELL", config.execution, snapshot.book_depth_eur)
    net_proceeds_eur, fee_eur, slippage_eur = accounting.apply_sell_costs(gross_eur, fee_pct, slippage_pct)
    executed_price = (gross_eur - slippage_eur) / units_to_sell

    order = Order(
        run_id=run_id,
        position_id=position.id,
        side="SELL",
        order_type=order_type,
        requested_price=reference_price,
        executed_price=executed_price,
        units=units_to_sell,
        gross_value_eur_cents=accounting.eur_to_cents(gross_eur),
        fee_eur_cents=accounting.eur_to_cents(fee_eur),
        slippage_eur_cents=accounting.eur_to_cents(slippage_eur),
        status="FILLED",
        created_at=snapshot.timestamp,
        filled_at=snapshot.timestamp,
    )
    add_order(session, order)

    close_req = PositionCloseRequest(
        closed_at=snapshot.timestamp,
        sell_reason=sell_reason,
        exit_price=executed_price,
        exit_spread_pct=snapshot.spread_pct,
        exit_slippage_eur_cents=accounting.eur_to_cents(slippage_eur),
        exit_fee_eur_cents=accounting.eur_to_cents(fee_eur),
        net_proceeds_eur_cents=accounting.eur_to_cents(net_proceeds_eur),
        units_sold=units_to_sell,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        correct_signals=correct_signals,
        wrong_signals=wrong_signals,
        classification=classification,
    )
    close_position(session, position, close_req)
    return order

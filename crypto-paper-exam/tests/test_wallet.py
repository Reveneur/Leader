import datetime as dt
from decimal import Decimal

import pytest

from audit.config_freeze import load_strategy_config
from execution.paper_broker import (
    InsufficientCashError,
    MarketSnapshot,
    PositionPlan,
    execute_buy,
    execute_sell,
)
from database.repositories import open_positions
from portfolio.positions import value_all_open_positions
from portfolio.wallet import Wallet
from settings import REPO_ROOT

CONFIG = load_strategy_config(REPO_ROOT / "config" / "exam_v1.yaml")
NOW = dt.datetime(2026, 7, 11, 14, 0, tzinfo=dt.timezone.utc)


def make_plan(**overrides) -> PositionPlan:
    defaults = dict(
        asset="SOL",
        strategy_version="Exam V1",
        stop_price=Decimal("95"),
        target_1=Decimal("115"),
        target_2=None,
        trailing_rule=None,
        regime_at_entry="TREND-UP",
        scores={"overall": 80},
        contradictions=[],
        missing_data=[],
        catalyst=None,
        onchain_confirmation=None,
        thesis="test thesis",
        expected_hold_period="4h",
        max_eur_risk_cents=150,
        expected_gross_profit_eur_cents=750,
        expected_net_profit_eur_cents=700,
        net_reward_risk=Decimal("2.5"),
        confidence=Decimal("80"),
        invalidation_criterion="close below stop",
        sources=["bitvavo"],
    )
    defaults.update(overrides)
    return PositionPlan(**defaults)


def snapshot(bid="99.9", ask="100.1", spread="0.2") -> MarketSnapshot:
    return MarketSnapshot(
        market="SOL-EUR",
        timestamp=NOW,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=Decimal("100"),
        spread_pct=Decimal(spread),
        volume_24h_eur=Decimal("1000000"),
        book_depth_eur=Decimal("10000"),
    )


def test_buy_lowers_cash_by_exactly_gross_plus_fee_plus_slippage(session):
    wallet = Wallet(session, CONFIG.wallet.initial_cash_eur)
    starting_cash = wallet.cash_cents()

    order = execute_buy(
        session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan()
    )
    session.flush()

    total_debit_cents = order.gross_value_eur_cents + order.fee_eur_cents + order.slippage_eur_cents
    assert wallet.cash_cents() == starting_cash - total_debit_cents
    assert order.fee_eur_cents > 0
    assert order.slippage_eur_cents > 0


def test_buy_creates_open_position_with_correct_units(session):
    order = execute_buy(
        session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan()
    )
    session.flush()

    positions = open_positions(session)
    assert len(positions) == 1
    position = positions[0]
    assert position.id == order.position_id
    assert position.entry_units == order.units
    assert position.remaining_units == order.units
    assert position.status == "OPEN"


def test_buy_exceeding_cash_raises_and_does_not_mutate_wallet(session):
    wallet = Wallet(session, CONFIG.wallet.initial_cash_eur)
    starting_cash = wallet.cash_cents()

    with pytest.raises(InsufficientCashError):
        execute_buy(
            session, "run-1", CONFIG, snapshot(), Decimal("500"), Decimal("100"), make_plan()
        )

    assert wallet.cash_cents() == starting_cash


def test_sell_raises_cash_by_net_proceeds(session):
    wallet = Wallet(session, CONFIG.wallet.initial_cash_eur)
    execute_buy(session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan())
    session.flush()
    position = open_positions(session)[0]
    cash_after_buy = wallet.cash_cents()

    sell_order = execute_sell(
        session,
        "run-2",
        CONFIG,
        snapshot(),
        position,
        position.remaining_units,
        sell_reason="target hit",
        classification="CORRECT",
    )
    session.flush()

    net_credit_cents = sell_order.gross_value_eur_cents - sell_order.fee_eur_cents - sell_order.slippage_eur_cents
    assert wallet.cash_cents() == cash_after_buy + net_credit_cents
    assert sell_order.fee_eur_cents > 0
    assert sell_order.slippage_eur_cents > 0


def test_sell_closes_position_and_records_realized_pnl(session):
    execute_buy(session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan())
    session.flush()
    position = open_positions(session)[0]

    execute_sell(
        session,
        "run-2",
        CONFIG,
        snapshot(bid="105", ask="105.2", spread="0.2"),
        position,
        position.remaining_units,
        sell_reason="target hit",
        classification="CORRECT",
    )
    session.flush()

    assert position.status == "CLOSED"
    assert position.closed_at is not None
    assert position.remaining_units == Decimal("0")
    assert position.realized_pnl_eur_cents != 0
    assert position.classification == "CORRECT"
    assert open_positions(session) == []


def test_wallet_equity_closes_exactly_cash_plus_holdings(session):
    wallet = Wallet(session, CONFIG.wallet.initial_cash_eur)
    execute_buy(session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan())
    session.flush()

    valuation = value_all_open_positions(
        session, {"SOL-EUR": Decimal("101")}, CONFIG.execution.taker_fee_pct, CONFIG.execution.default_slippage_sell_pct
    )
    snap = wallet.record_snapshot("run-1", NOW, valuation)

    assert snap.equity_eur_cents == snap.cash_eur_cents + snap.holdings_value_eur_cents
    assert snap.cash_eur_cents + valuation.holdings_value_cents == snap.equity_eur_cents


def test_open_position_is_valued_below_naive_mark_to_last(session):
    """A position's stored value must reflect executable sell proceeds
    (bid - slippage - fee), not the raw last/bid price times units.
    """
    execute_buy(session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan())
    session.flush()
    position = open_positions(session)[0]

    bid = Decimal("100.1")  # same as entry ask, roughly flat market
    valuation = value_all_open_positions(
        session, {"SOL-EUR": bid}, CONFIG.execution.taker_fee_pct, CONFIG.execution.default_slippage_sell_pct
    )
    naive_value_cents = int(position.remaining_units * bid * 100)
    assert valuation.holdings_value_cents < naive_value_cents


def test_missing_price_data_keeps_last_known_value_instead_of_fabricating(session):
    execute_buy(session, "run-1", CONFIG, snapshot(), Decimal("50"), Decimal("100"), make_plan())
    session.flush()
    position = open_positions(session)[0]
    prior_value = position.current_value_eur_cents

    valuation = value_all_open_positions(
        session, {}, CONFIG.execution.taker_fee_pct, CONFIG.execution.default_slippage_sell_pct
    )
    assert valuation.holdings_value_cents == prior_value

from decimal import Decimal

from portfolio.accounting import (
    apply_buy_costs,
    apply_sell_costs,
    cents_to_eur,
    compute_drawdown_pct,
    compute_equity_cents,
    estimate_executable_sell_value,
    eur_to_cents,
    pct_of,
)


def test_eur_to_cents_round_trip():
    assert eur_to_cents(Decimal("100.00")) == 10000
    assert eur_to_cents(Decimal("0.005")) == 1  # ROUND_HALF_UP
    assert cents_to_eur(10000) == Decimal("100.00")


def test_pct_of():
    assert pct_of(Decimal("100"), Decimal("0.25")) == Decimal("0.25")


def test_apply_buy_costs_adds_slippage_and_fee_on_top():
    total, fee, slippage = apply_buy_costs(Decimal("50"), Decimal("0.25"), Decimal("0.10"))
    assert slippage == Decimal("0.05")
    assert fee == (Decimal("50") + Decimal("0.05")) * Decimal("0.25") / 100
    assert total == Decimal("50") + slippage + fee


def test_apply_sell_costs_subtracts_slippage_and_fee():
    net, fee, slippage = apply_sell_costs(Decimal("50"), Decimal("0.25"), Decimal("0.10"))
    assert slippage == Decimal("0.05")
    assert net == Decimal("50") - slippage - fee
    assert net < Decimal("50")


def test_buy_then_sell_same_amount_loses_money_to_costs():
    """A round trip at an unchanged price must lose money to fees+slippage —
    the simulator must never let costs net out to zero or favor the trader.
    """
    total_cost, _, _ = apply_buy_costs(Decimal("50"), Decimal("0.25"), Decimal("0.10"))
    net_proceeds, _, _ = apply_sell_costs(Decimal("50"), Decimal("0.25"), Decimal("0.10"))
    assert net_proceeds < total_cost


def test_estimate_executable_sell_value_below_gross():
    value = estimate_executable_sell_value(Decimal("10"), Decimal("5.00"), Decimal("0.25"), Decimal("0.10"))
    assert value < Decimal("50.00")


def test_compute_equity_cents():
    assert compute_equity_cents(5000, 3000) == 8000


def test_compute_drawdown_pct_no_drawdown_at_peak():
    assert compute_drawdown_pct(10000, 10000) == Decimal("0")


def test_compute_drawdown_pct_below_peak():
    dd = compute_drawdown_pct(9200, 10000)
    assert dd == Decimal("8.0000")


def test_compute_drawdown_pct_zero_peak_is_safe():
    assert compute_drawdown_pct(0, 0) == Decimal("0")

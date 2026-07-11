from decimal import Decimal

from audit.config_freeze import ExecutionConfig
from execution.slippage_model import estimate_slippage_pct

CONFIG = ExecutionConfig(
    taker_fee_pct=Decimal("0.25"),
    maker_fee_pct=Decimal("0.15"),
    default_slippage_buy_pct=Decimal("0.10"),
    default_slippage_sell_pct=Decimal("0.10"),
)


def test_default_slippage_without_orderbook_data():
    assert estimate_slippage_pct(Decimal("50"), "BUY", CONFIG, None) == Decimal("0.10")
    assert estimate_slippage_pct(Decimal("50"), "SELL", CONFIG, None) == Decimal("0.10")


def test_zero_depth_uses_default():
    assert estimate_slippage_pct(Decimal("50"), "BUY", CONFIG, Decimal("0")) == Decimal("0.10")


def test_thin_book_increases_slippage_beyond_default():
    # order is half the book depth -> impact-based slippage should dominate
    pct = estimate_slippage_pct(Decimal("50"), "BUY", CONFIG, Decimal("100"))
    assert pct > Decimal("0.10")


def test_slippage_never_goes_below_default_even_with_deep_book():
    pct = estimate_slippage_pct(Decimal("50"), "BUY", CONFIG, Decimal("1000000"))
    assert pct == Decimal("0.10")

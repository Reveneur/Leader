from decimal import Decimal

from audit.config_freeze import ExecutionConfig
from execution.fee_model import MakerEligibility, determine_fee_pct

CONFIG = ExecutionConfig(
    taker_fee_pct=Decimal("0.25"),
    maker_fee_pct=Decimal("0.15"),
    default_slippage_buy_pct=Decimal("0.10"),
    default_slippage_sell_pct=Decimal("0.10"),
)


def test_default_order_is_taker():
    assert determine_fee_pct("TAKER", CONFIG) == Decimal("0.25")


def test_maker_without_eligibility_falls_back_to_taker():
    assert determine_fee_pct("MAKER", CONFIG, None) == Decimal("0.25")


def test_maker_with_full_eligibility_gets_maker_fee():
    eligibility = MakerEligibility(True, True, True, True, True)
    assert determine_fee_pct("MAKER", CONFIG, eligibility) == Decimal("0.15")


def test_maker_touching_limit_only_is_not_enough():
    """Section 6.2: touching the limit price alone must not grant maker fee."""
    eligibility = MakerEligibility(
        limit_price_set_before_order=True,
        order_not_immediately_marketable=True,
        market_later_traded_through_limit=False,  # only touched, not traded through
        sufficient_volume_available=True,
        realistically_fillable=True,
    )
    assert not eligibility.eligible
    assert determine_fee_pct("MAKER", CONFIG, eligibility) == Decimal("0.25")


def test_maker_missing_any_single_condition_is_ineligible():
    base = dict(
        limit_price_set_before_order=True,
        order_not_immediately_marketable=True,
        market_later_traded_through_limit=True,
        sufficient_volume_available=True,
        realistically_fillable=True,
    )
    for key in base:
        flags = dict(base)
        flags[key] = False
        assert not MakerEligibility(**flags).eligible

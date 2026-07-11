import datetime as dt
from decimal import Decimal

from audit.config_freeze import PortfolioConfig
from portfolio.risk_manager import (
    allowed_risk_pct,
    check_max_positions,
    drawdown_blocks_new_positions,
    drawdown_position_size_factor,
    evaluate_new_position,
    in_loss_pause,
    is_correlation_blocked,
    max_position_eur,
    position_size_from_risk,
)

CONFIG = PortfolioConfig(
    max_positions=2,
    max_position_eur=Decimal("50"),
    max_position_equity_pct=Decimal("50"),
    normal_risk_pct=Decimal("3"),
    exceptional_risk_pct=Decimal("5"),
    exceptional_risk_min_score=Decimal("90"),
    exceptional_risk_min_rr=Decimal("3.0"),
    drawdown_reduce_pct=Decimal("8"),
    drawdown_reduce_factor=Decimal("0.5"),
    drawdown_stop_pct=Decimal("12"),
)

NOW = dt.datetime(2026, 7, 12, 12, 0, tzinfo=dt.timezone.utc)


def test_max_position_size_is_the_lower_of_fixed_cap_and_pct_of_equity():
    # equity 100 -> 50% = 50, fixed cap 50 -> min is 50
    assert max_position_eur(Decimal("100"), Decimal("0"), CONFIG) == Decimal("50")
    # equity 60 -> 50% = 30, fixed cap 50 -> min is 30
    assert max_position_eur(Decimal("60"), Decimal("0"), CONFIG) == Decimal("30")


def test_max_two_open_positions():
    assert check_max_positions(0, CONFIG).allowed
    assert check_max_positions(1, CONFIG).allowed
    assert not check_max_positions(2, CONFIG).allowed


def test_loss_pause_triggers_after_two_losses_within_24h():
    losses = [NOW - dt.timedelta(hours=20), NOW - dt.timedelta(hours=1)]
    assert in_loss_pause(NOW, losses, window_hours=24, losses_threshold=2, pause_hours=12)


def test_loss_pause_does_not_trigger_for_losses_far_apart():
    losses = [NOW - dt.timedelta(hours=30), NOW - dt.timedelta(hours=1)]
    assert not in_loss_pause(NOW, losses, window_hours=24, losses_threshold=2, pause_hours=12)


def test_loss_pause_expires_after_pause_hours():
    losses = [NOW - dt.timedelta(hours=20), NOW - dt.timedelta(hours=13)]
    assert not in_loss_pause(NOW, losses, window_hours=24, losses_threshold=2, pause_hours=12)


def test_drawdown_8pct_halves_position_size():
    assert drawdown_position_size_factor(Decimal("8"), CONFIG) == Decimal("0.5")
    assert max_position_eur(Decimal("100"), Decimal("8"), CONFIG) == Decimal("25")


def test_drawdown_12pct_blocks_new_positions():
    assert drawdown_blocks_new_positions(Decimal("12"), CONFIG)
    assert max_position_eur(Decimal("100"), Decimal("12"), CONFIG) == Decimal("0")


def test_drawdown_below_8pct_is_unaffected():
    assert drawdown_position_size_factor(Decimal("7.9"), CONFIG) == Decimal("1")


def test_correlation_blocks_second_highly_correlated_position():
    correlations = {("ETH", "BTC"): Decimal("0.95")}
    decision = is_correlation_blocked("ETH", ["BTC"], correlations)
    assert not decision.allowed


def test_correlation_allows_uncorrelated_position():
    correlations = {("SOL", "BTC"): Decimal("0.30")}
    decision = is_correlation_blocked("SOL", ["BTC"], correlations)
    assert decision.allowed


def test_normal_risk_pct_for_ordinary_setup():
    assert allowed_risk_pct(Decimal("80"), Decimal("2.0"), CONFIG) == Decimal("3")


def test_exceptional_risk_pct_requires_both_score_and_rr():
    assert allowed_risk_pct(Decimal("95"), Decimal("3.5"), CONFIG) == Decimal("5")
    assert allowed_risk_pct(Decimal("95"), Decimal("2.5"), CONFIG) == Decimal("3")  # RR too low
    assert allowed_risk_pct(Decimal("85"), Decimal("4.0"), CONFIG) == Decimal("3")  # score too low


def test_position_size_from_risk():
    units = position_size_from_risk(Decimal("100"), Decimal("95"), Decimal("5"))
    assert units == Decimal("1")


def test_insufficient_reward_to_risk_is_a_scoring_concern_not_sized_here():
    # risk_manager only sizes; eligibility (net RR >= 2:1) is enforced in
    # strategy.scoring before evaluate_new_position is ever called.
    assert position_size_from_risk(Decimal("100"), Decimal("100"), Decimal("5")) == Decimal("0")


def test_evaluate_new_position_blocked_by_drawdown_stop():
    decision, size, risk = evaluate_new_position(
        equity_eur=Decimal("88"),
        drawdown_pct=Decimal("12"),
        open_positions_count=0,
        candidate_asset="SOL",
        open_assets=[],
        correlations={},
        loss_timestamps=[],
        now=NOW,
        overall_score=Decimal("80"),
        net_reward_risk=Decimal("2.5"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        config=CONFIG,
        loss_pause_losses=2,
        loss_pause_window_hours=24,
        loss_pause_pause_hours=12,
    )
    assert not decision.allowed
    assert size == Decimal("0")


def test_evaluate_new_position_happy_path_sizes_correctly():
    decision, size, risk = evaluate_new_position(
        equity_eur=Decimal("100"),
        drawdown_pct=Decimal("0"),
        open_positions_count=0,
        candidate_asset="SOL",
        open_assets=[],
        correlations={},
        loss_timestamps=[],
        now=NOW,
        overall_score=Decimal("80"),
        net_reward_risk=Decimal("2.5"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        config=CONFIG,
        loss_pause_losses=2,
        loss_pause_window_hours=24,
        loss_pause_pause_hours=12,
    )
    assert decision.allowed
    # normal risk = 3% of 100 = 3 EUR risk; per-unit risk = 5 -> 0.6 units -> 60 EUR
    # but capped at max_position_eur = min(50, 50% of 100) = 50
    assert size == Decimal("50")
    assert risk == Decimal("2.5")  # 0.5 units * 5 EUR risk/unit

"""Risk rules (spec section 11). Pure decision functions over explicit
inputs — no DB or network access — so every rule (max positions, sizing,
drawdown throttling, loss pause, correlation block) is independently
testable per spec section 23's "Risicotests".
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from audit.config_freeze import PortfolioConfig

CORRELATION_BLOCK_THRESHOLD = Decimal("0.85")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str | None = None


def drawdown_position_size_factor(drawdown_pct: Decimal, config: PortfolioConfig) -> Decimal:
    """Section 11.5: >=12% drawdown stops new positions entirely (factor 0
    is a signal, callers must also check drawdown_blocks_new_positions);
    >=8% halves the max position size.
    """
    if drawdown_pct >= config.drawdown_stop_pct:
        return Decimal("0")
    if drawdown_pct >= config.drawdown_reduce_pct:
        return config.drawdown_reduce_factor
    return Decimal("1")


def drawdown_blocks_new_positions(drawdown_pct: Decimal, config: PortfolioConfig) -> bool:
    return drawdown_pct >= config.drawdown_stop_pct


def max_position_eur(equity_eur: Decimal, drawdown_pct: Decimal, config: PortfolioConfig) -> Decimal:
    base_cap = min(config.max_position_eur, equity_eur * config.max_position_equity_pct / 100)
    factor = drawdown_position_size_factor(drawdown_pct, config)
    return base_cap * factor


def check_max_positions(open_positions_count: int, config: PortfolioConfig) -> RiskDecision:
    if open_positions_count >= config.max_positions:
        return RiskDecision(False, f"max_positions ({config.max_positions}) already open")
    return RiskDecision(True)


def loss_pause_windows(
    loss_timestamps: list[dt.datetime], window_hours: int, losses_threshold: int, pause_hours: int
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Section 11.4: after `losses_threshold` closed losing trades within a
    rolling `window_hours` window, a `pause_hours` pause begins at the
    qualifying (threshold-th) loss.
    """
    ordered = sorted(loss_timestamps)
    windows: list[tuple[dt.datetime, dt.datetime]] = []
    for i in range(len(ordered) - losses_threshold + 1):
        group = ordered[i : i + losses_threshold]
        if group[-1] - group[0] <= dt.timedelta(hours=window_hours):
            pause_start = group[-1]
            windows.append((pause_start, pause_start + dt.timedelta(hours=pause_hours)))
    return windows


def in_loss_pause(
    now: dt.datetime,
    loss_timestamps: list[dt.datetime],
    window_hours: int,
    losses_threshold: int,
    pause_hours: int,
) -> bool:
    windows = loss_pause_windows(loss_timestamps, window_hours, losses_threshold, pause_hours)
    return any(start <= now <= end for start, end in windows)


def allowed_risk_pct(
    overall_score: Decimal, net_reward_risk: Decimal, config: PortfolioConfig
) -> Decimal:
    """Section 11.3: up to 5% risk only for exceptional setups (score >= 90,
    RR >= 3:1); otherwise the normal 3% cap.
    """
    if overall_score >= config.exceptional_risk_min_score and net_reward_risk >= config.exceptional_risk_min_rr:
        return config.exceptional_risk_pct
    return config.normal_risk_pct


def position_size_from_risk(
    entry_price: Decimal, stop_price: Decimal, risk_eur: Decimal
) -> Decimal:
    per_unit_risk = abs(entry_price - stop_price)
    if per_unit_risk == 0:
        return Decimal("0")
    return risk_eur / per_unit_risk


def is_correlation_blocked(
    candidate_asset: str,
    open_assets: list[str],
    correlations: dict[tuple[str, str], Decimal],
    threshold: Decimal = CORRELATION_BLOCK_THRESHOLD,
) -> RiskDecision:
    for asset in open_assets:
        key = (candidate_asset, asset) if (candidate_asset, asset) in correlations else (asset, candidate_asset)
        corr = correlations.get(key)
        if corr is not None and corr >= threshold:
            return RiskDecision(
                False, f"{candidate_asset} is highly correlated with open position {asset} ({corr})"
            )
    return RiskDecision(True)


def evaluate_new_position(
    *,
    equity_eur: Decimal,
    drawdown_pct: Decimal,
    open_positions_count: int,
    candidate_asset: str,
    open_assets: list[str],
    correlations: dict[tuple[str, str], Decimal],
    loss_timestamps: list[dt.datetime],
    now: dt.datetime,
    overall_score: Decimal,
    net_reward_risk: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    config: PortfolioConfig,
    loss_pause_losses: int,
    loss_pause_window_hours: int,
    loss_pause_pause_hours: int,
) -> tuple[RiskDecision, Decimal, Decimal]:
    """Runs every section-11 gate in order and, if all pass, returns the
    allowed position size in EUR and the max EUR risk for that size.
    Returns (decision, position_size_eur, max_eur_risk).
    """
    zero = Decimal("0")

    if drawdown_blocks_new_positions(drawdown_pct, config):
        return RiskDecision(False, "drawdown_stop_pct reached; no new positions"), zero, zero

    positions_check = check_max_positions(open_positions_count, config)
    if not positions_check.allowed:
        return positions_check, zero, zero

    if in_loss_pause(now, loss_timestamps, loss_pause_window_hours, loss_pause_losses, loss_pause_pause_hours):
        return RiskDecision(False, "loss pause active"), zero, zero

    correlation_check = is_correlation_blocked(candidate_asset, open_assets, correlations)
    if not correlation_check.allowed:
        return correlation_check, zero, zero

    risk_pct = allowed_risk_pct(overall_score, net_reward_risk, config)
    risk_eur = equity_eur * risk_pct / 100
    size_from_risk_units = position_size_from_risk(entry_price, stop_price, risk_eur)
    size_from_risk_eur = size_from_risk_units * entry_price

    cap_eur = max_position_eur(equity_eur, drawdown_pct, config)
    position_size_eur = min(size_from_risk_eur, cap_eur)

    if position_size_eur <= 0:
        return RiskDecision(False, "computed position size is zero"), zero, zero

    actual_units = position_size_eur / entry_price
    actual_risk_eur = actual_units * abs(entry_price - stop_price)

    return RiskDecision(True), position_size_eur, actual_risk_eur

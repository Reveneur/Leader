"""Strategy config loading, typed access, and tamper-evident freezing.

At exam initialization the content hash of config/exam_v1.yaml is stored in
the config_freeze table. Every subsequent scheduler run recomputes the hash
of the live file and compares it to the frozen value. Any mismatch is a
hard stop — Exam V1's rules are fixed for the exam period (spec section 19).
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.models import ConfigFreeze
from database.repositories import active_config_freeze, add_config_freeze


class ConfigTamperedError(RuntimeError):
    """Raised when the live config file no longer matches the frozen hash."""


class ExamWindow(BaseModel):
    start: str
    end: str
    wallet_admin_start: str
    timezone: str


class WalletConfig(BaseModel):
    initial_cash_eur: Decimal


class ExecutionConfig(BaseModel):
    taker_fee_pct: Decimal
    maker_fee_pct: Decimal
    default_slippage_buy_pct: Decimal
    default_slippage_sell_pct: Decimal


class PortfolioConfig(BaseModel):
    max_positions: int
    max_position_eur: Decimal
    max_position_equity_pct: Decimal
    normal_risk_pct: Decimal
    exceptional_risk_pct: Decimal
    exceptional_risk_min_score: Decimal
    exceptional_risk_min_rr: Decimal
    drawdown_reduce_pct: Decimal
    drawdown_reduce_factor: Decimal
    drawdown_stop_pct: Decimal


class EligibilityConfig(BaseModel):
    regime_fit_min: int
    residual_strength_min: int
    breakout_min: int
    volume_min: int
    liquidity_execution_min: int
    adversarial_min: int
    overall_confidence_min: Decimal
    net_reward_risk_min: Decimal


class LossPauseConfig(BaseModel):
    losses: int
    window_hours: int
    pause_hours: int


class LiquidityConfig(BaseModel):
    min_24h_volume_eur: Decimal
    max_spread_pct: Decimal
    min_book_depth_eur: Decimal
    max_impact_eur: Decimal
    min_market_history_days: int


class IntrahourConfig(BaseModel):
    reconstruction_interval: str
    ambiguous_stop_target_rule: str


class StrategyConfig(BaseModel):
    strategy_version: str
    exam: ExamWindow
    wallet: WalletConfig
    execution: ExecutionConfig
    portfolio: PortfolioConfig
    eligibility: EligibilityConfig
    loss_pause: LossPauseConfig
    liquidity: LiquidityConfig
    intrahour: IntrahourConfig


def load_raw_config_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def compute_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def load_strategy_config(path: Path) -> StrategyConfig:
    raw = load_raw_config_text(path)
    data = yaml.safe_load(raw)
    return StrategyConfig.model_validate(data)


def freeze_config(session: Session, path: Path) -> ConfigFreeze:
    """Records the current config as authoritative. Only intended to be
    called once, by scripts/initialize_exam.py. Deactivates any prior freeze
    rather than deleting it, preserving history.
    """
    raw = load_raw_config_text(path)
    config_hash = compute_hash(raw)
    config = StrategyConfig.model_validate(yaml.safe_load(raw))

    existing = active_config_freeze(session)
    if existing is not None:
        existing.active = False

    freeze = ConfigFreeze(
        strategy_version=config.strategy_version,
        config_hash=config_hash,
        config_json=json.dumps(yaml.safe_load(raw), default=str),
        active=True,
    )
    return add_config_freeze(session, freeze)


def verify_config(session: Session, path: Path) -> StrategyConfig:
    """Raises ConfigTamperedError if the live file diverges from the frozen
    hash. Returns the parsed, verified config on success.
    """
    frozen = active_config_freeze(session)
    if frozen is None:
        raise ConfigTamperedError(
            "No frozen configuration found. Run scripts/initialize_exam.py first."
        )
    raw = load_raw_config_text(path)
    live_hash = compute_hash(raw)
    if live_hash != frozen.config_hash:
        raise ConfigTamperedError(
            f"config/exam_v1.yaml has changed since freeze "
            f"(frozen={frozen.config_hash}, live={live_hash}). "
            "Exam V1 parameters are locked; changes must be proposed as Version 2."
        )
    return StrategyConfig.model_validate(yaml.safe_load(raw))

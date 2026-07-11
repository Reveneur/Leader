"""Eligibility scoring (spec section 10). Combines the ten component scores
into an overall score and evaluates every mandatory gate. A BUY is only
ever permitted when *every* gate passes — a single missing condition is
enough to reject, per spec section 10's closing line.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from audit.config_freeze import EligibilityConfig


@dataclass
class ComponentScores:
    regime_fit: int
    residual_strength: int
    breakout_quality: int
    volume_quality: int
    microstructure_liquidity: int
    catalyst_credibility: int
    onchain_confirmation: int
    crowding_quality: int
    execution_quality: int
    adversarial_confidence: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def volume_quality_score(current_volume: Decimal, avg_volume: Decimal) -> int:
    if avg_volume <= 0:
        return 0
    ratio = current_volume / avg_volume
    if ratio >= Decimal("3"):
        return 10
    if ratio >= Decimal("2"):
        return 8
    if ratio >= Decimal("1.5"):
        return 6
    if ratio >= Decimal("1"):
        return 4
    return max(0, int(ratio * 3))


def execution_quality_score(
    spread_pct: Decimal,
    max_spread_pct: Decimal,
    expected_slippage_pct: Decimal,
    edge_pct: Decimal,
) -> int:
    """Edge must comfortably absorb spread + slippage. edge_pct is the
    expected gross move to target as a percentage.
    """
    if spread_pct > max_spread_pct:
        return 0
    total_cost_pct = spread_pct + expected_slippage_pct
    if edge_pct <= 0:
        return 0
    cost_ratio = total_cost_pct / edge_pct
    if cost_ratio <= Decimal("0.05"):
        return 10
    if cost_ratio <= Decimal("0.10"):
        return 8
    if cost_ratio <= Decimal("0.20"):
        return 6
    if cost_ratio <= Decimal("0.35"):
        return 4
    return max(0, int(10 * (1 - cost_ratio)))


def compute_overall_score(scores: ComponentScores) -> Decimal:
    total = sum(scores.as_dict().values())
    return (Decimal(total) / Decimal(100)) * 100  # 10 components * max 10 = 100


@dataclass
class EligibilityResult:
    eligible: bool
    rejection_reasons: list[str]


def evaluate_eligibility(
    scores: ComponentScores,
    overall_score: Decimal,
    net_reward_risk: Decimal,
    has_independent_confirmation: bool,
    critical_security_risk: bool,
    critical_unlock_risk: bool,
    critical_liquidity_risk: bool,
    critical_crowding_risk: bool,
    adversarial_veto: bool,
    config: EligibilityConfig,
) -> EligibilityResult:
    reasons: list[str] = []

    if scores.regime_fit < config.regime_fit_min:
        reasons.append(f"regime_fit {scores.regime_fit} < {config.regime_fit_min}")
    if scores.residual_strength < config.residual_strength_min:
        reasons.append(f"residual_strength {scores.residual_strength} < {config.residual_strength_min}")
    if scores.breakout_quality < config.breakout_min:
        reasons.append(f"breakout_quality {scores.breakout_quality} < {config.breakout_min}")
    if scores.volume_quality < config.volume_min:
        reasons.append(f"volume_quality {scores.volume_quality} < {config.volume_min}")
    if scores.microstructure_liquidity < config.liquidity_execution_min:
        reasons.append(
            f"microstructure_liquidity {scores.microstructure_liquidity} < {config.liquidity_execution_min}"
        )
    if scores.execution_quality < config.liquidity_execution_min:
        reasons.append(f"execution_quality {scores.execution_quality} < {config.liquidity_execution_min}")
    if scores.adversarial_confidence < config.adversarial_min:
        reasons.append(f"adversarial_confidence {scores.adversarial_confidence} < {config.adversarial_min}")
    if adversarial_veto:
        reasons.append("adversarial veto: a critical bear-case flag was raised")
    if overall_score < config.overall_confidence_min:
        reasons.append(f"overall_score {overall_score} < {config.overall_confidence_min}")
    if net_reward_risk < config.net_reward_risk_min:
        reasons.append(f"net_reward_risk {net_reward_risk} < {config.net_reward_risk_min}")
    if not has_independent_confirmation:
        reasons.append("no independent catalyst or on-chain confirmation")
    if critical_security_risk:
        reasons.append("critical security risk present")
    if critical_unlock_risk:
        reasons.append("critical token unlock risk present")
    if critical_liquidity_risk:
        reasons.append("critical liquidity risk present")
    if critical_crowding_risk:
        reasons.append("critical crowding risk present")

    return EligibilityResult(eligible=not reasons, rejection_reasons=reasons)

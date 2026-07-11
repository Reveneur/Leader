"""Adversarial Risk Agent (spec section 9.9). Actively builds the bear case
and holds veto power — any critical risk flag forces rejection regardless
of how strong every other score is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class RiskFlags:
    weak_market_context: bool = False
    weak_liquidity: bool = False
    catalyst_already_priced_in: bool = False
    negative_token_unlock: bool = False
    security_risk: bool = False
    spread_too_wide: bool = False
    poor_reward_to_risk: bool = False
    correlated_with_existing_position: bool = False
    late_entry: bool = False
    stop_too_far: bool = False
    insufficient_net_upside_after_costs: bool = False


CRITICAL_FLAGS = (
    "negative_token_unlock",
    "security_risk",
    "weak_liquidity",
)


@dataclass
class AdversarialResult:
    score: int
    veto: bool
    bear_case: list[str] = field(default_factory=list)


_FLAG_DESCRIPTIONS = {
    "weak_market_context": "Market regime does not support new risk-taking.",
    "weak_liquidity": "Liquidity is too thin to exit cleanly.",
    "catalyst_already_priced_in": "The catalyst is stale and likely already priced in.",
    "negative_token_unlock": "An upcoming unlock creates supply overhang.",
    "security_risk": "An unresolved security concern exists for this asset.",
    "spread_too_wide": "The spread erodes too much of the expected edge.",
    "poor_reward_to_risk": "Reward-to-risk does not clear the required minimum.",
    "correlated_with_existing_position": "This duplicates risk already held in the portfolio.",
    "late_entry": "Price has already moved too far from a sound entry.",
    "stop_too_far": "The stop distance implies an unacceptably large position risk.",
    "insufficient_net_upside_after_costs": "Expected profit after costs is too thin to justify the trade.",
}


def adversarial_review(flags: RiskFlags, net_reward_risk: Decimal, min_rr: Decimal) -> AdversarialResult:
    active = [name for name, value in vars(flags).items() if value]
    bear_case = [_FLAG_DESCRIPTIONS[name] for name in active]

    critical_hit = any(getattr(flags, name) for name in CRITICAL_FLAGS)
    if net_reward_risk < min_rr:
        critical_hit = True
        if "poor_reward_to_risk" not in active:
            bear_case.append(_FLAG_DESCRIPTIONS["poor_reward_to_risk"])

    if critical_hit:
        return AdversarialResult(score=0, veto=True, bear_case=bear_case)

    # Score starts at 10 and loses points per non-critical concern raised.
    score = max(0, 10 - 2 * len(active))
    return AdversarialResult(score=score, veto=False, bear_case=bear_case)

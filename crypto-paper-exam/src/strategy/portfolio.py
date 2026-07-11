"""Portfolio Agent (spec section 9.10): the final BUY/SELL/HOLD/CASH call
for opening a new position, given already-scored candidates. Management of
existing positions (stops/targets/invalidation -> SELL/HOLD) is decided by
the scheduler using execution.stop_target_engine and is combined with this
module's output to produce the single top-level action per hourly run
(spec section 14 — exactly one decision per run).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from strategy.scoring import ComponentScores, EligibilityResult


@dataclass
class CandidateEvaluation:
    asset: str
    market: str
    scores: ComponentScores
    overall_score: Decimal
    net_reward_risk: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_1: Decimal
    target_2: Decimal | None
    eligibility: EligibilityResult
    confidence: Decimal
    regime: str
    thesis: str


@dataclass
class PortfolioDecision:
    action: str  # BUY, CASH
    asset: str | None
    confidence: Decimal
    explanation: str
    contradiction: str | None
    top_candidate: str | None


def decide_new_entry(
    candidates: list[CandidateEvaluation], room_for_new_position: bool
) -> PortfolioDecision:
    if not candidates:
        return PortfolioDecision(
            action="CASH",
            asset=None,
            confidence=Decimal("0"),
            explanation="CASH. Geen kandidaten beschikbaar deze run.",
            contradiction=None,
            top_candidate=None,
        )

    ranked = sorted(candidates, key=lambda c: c.overall_score, reverse=True)
    top = ranked[0]

    if not room_for_new_position:
        return PortfolioDecision(
            action="CASH",
            asset=None,
            confidence=top.overall_score,
            explanation=(
                f"CASH. {top.asset} scoort het hoogst, maar er is geen ruimte voor een "
                "nieuwe positie (maximum posities bereikt of drawdown-stop actief)."
            ),
            contradiction="portfolio capacity or drawdown-stop",
            top_candidate=top.asset,
        )

    eligible = [c for c in candidates if c.eligibility.eligible]
    if not eligible:
        reasons = "; ".join(top.eligibility.rejection_reasons[:2]) or "onbekende reden"
        return PortfolioDecision(
            action="CASH",
            asset=None,
            confidence=top.overall_score,
            explanation=f"CASH. {top.asset} scoort het hoogst, maar voldoet niet aan de verplichte drempels: {reasons}.",
            contradiction=reasons,
            top_candidate=top.asset,
        )

    chosen = sorted(eligible, key=lambda c: c.overall_score, reverse=True)[0]
    return PortfolioDecision(
        action="BUY",
        asset=chosen.asset,
        confidence=chosen.confidence,
        explanation=f"BUY {chosen.asset}. {chosen.thesis}",
        contradiction=None,
        top_candidate=chosen.asset,
    )

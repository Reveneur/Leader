"""Narrative Agent (spec section 9.8). Explicitly NOT one of the ten scored
eligibility components in section 10 — narrative attention may only
support a thesis, never trigger a BUY by itself. This module produces a
qualitative assessment attached to the trade thesis, not a gating score.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NarrativeAssessment:
    attention_level: str  # NONE, ORGANIC, RECYCLED, HYPE, SUSPECTED_COORDINATED
    supporting: bool
    notes: str


def assess_narrative(
    mention_growth_pct: float,
    distinct_independent_sources: int,
    bot_activity_suspected: bool,
) -> NarrativeAssessment:
    if bot_activity_suspected:
        return NarrativeAssessment(
            "SUSPECTED_COORDINATED", False, "Coordinated/bot-like activity detected; disregarded."
        )
    if mention_growth_pct <= 0:
        return NarrativeAssessment("NONE", False, "No meaningful attention growth.")
    if distinct_independent_sources >= 3 and mention_growth_pct > 20:
        return NarrativeAssessment(
            "ORGANIC", True, f"Organic growth across {distinct_independent_sources} independent sources."
        )
    if mention_growth_pct > 50 and distinct_independent_sources < 2:
        return NarrativeAssessment("HYPE", False, "Rapid growth from very few sources — likely hype/promotion.")
    return NarrativeAssessment("RECYCLED", False, "Attention present but not clearly organic or new.")

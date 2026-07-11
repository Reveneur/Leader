"""Catalyst Verification Agent (spec section 9.5). Only primary-source
candidates count; influencer posts or copied news articles never count as
confirmation. With no candidates (e.g. news_client unavailable) the score
is 0 — missing data means "no catalyst credited", never a fabricated one.
"""
from __future__ import annotations

from data.news_client import CatalystCandidate

PRIMARY_SOURCE_TYPES = {
    "official_website",
    "official_docs",
    "github",
    "exchange_announcement",
    "governance",
    "security",
}


def is_credible(candidate: CatalystCandidate) -> bool:
    return candidate.is_primary_source and candidate.source_type in PRIMARY_SOURCE_TYPES


def catalyst_credibility_score(
    candidates: list[CatalystCandidate], economically_relevant: dict[str, bool] | None = None
) -> int:
    if not candidates:
        return 0

    credible = [c for c in candidates if is_credible(c)]
    if not credible:
        return 0

    relevant = credible
    if economically_relevant is not None:
        relevant = [c for c in credible if economically_relevant.get(c.headline, True)]
    if not relevant:
        return 2  # a verified-but-not-clearly-relevant catalyst is weak, not zero

    score = 5 + min(5, len(relevant) * 2)
    return min(10, score)

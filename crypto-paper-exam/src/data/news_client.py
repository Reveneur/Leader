"""Optional Phase-3 data source for catalyst verification (spec section
4.1, 9.5): official project announcements, GitHub activity, security
advisories. Deliberately pluggable and optional — the strategy.catalyst
module must run correctly (returning "unavailable") when no key is set.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CatalystCandidate:
    asset: str
    headline: str
    source_url: str
    source_type: str  # official_website, github, exchange_announcement, governance, security
    published_at: str
    is_primary_source: bool


class NewsClient:
    """No default implementation ships here — plugging in a real provider
    (RSS from official sources, GitHub API, exchange announcement feeds) is
    Phase 3 work per the README. Absence of an API key must never crash the
    core engine; it must simply mean no catalysts are found this run.
    """

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.available = bool(api_key)

    def fetch_candidates(self, asset: str) -> list[CatalystCandidate]:
        if not self.available:
            return []
        raise NotImplementedError(
            "No news provider is wired up yet. Configure NEWS_API_KEY and "
            "implement a provider-specific fetch here without changing this "
            "class's contract (empty list = no catalysts found)."
        )

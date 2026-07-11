"""Optional Phase-3 data source for on-chain confirmation (spec section
4.1, 9.6): exchange flows, active addresses, protocol revenue, etc.
Pluggable and optional, same contract as news_client.py — no key means no
data, never a crash.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class OnchainSnapshot:
    asset: str
    exchange_netflow_eur: Decimal | None
    active_addresses_change_pct: Decimal | None
    dex_volume_eur: Decimal | None
    as_of: str


class OnchainClient:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.available = bool(api_key)

    def fetch_snapshot(self, asset: str) -> OnchainSnapshot | None:
        if not self.available:
            return None
        raise NotImplementedError(
            "No on-chain data provider is wired up yet. Configure "
            "ONCHAIN_API_KEY and implement a provider-specific fetch here "
            "without changing this class's contract (None = no data)."
        )

"""On-Chain Agent (spec section 9.6). Never automatically decisive — a
supporting confirmation only. With no data available the score is 0.
"""
from __future__ import annotations

from decimal import Decimal

from data.onchain_client import OnchainSnapshot


def onchain_confirmation_score(snapshot: OnchainSnapshot | None) -> int:
    if snapshot is None:
        return 0

    score = 0
    if snapshot.exchange_netflow_eur is not None and snapshot.exchange_netflow_eur < 0:
        # net outflow from exchanges is commonly read as accumulation
        score += 4
    if snapshot.active_addresses_change_pct is not None and snapshot.active_addresses_change_pct > Decimal("5"):
        score += 3
    if snapshot.dex_volume_eur is not None and snapshot.dex_volume_eur > 0:
        score += 3
    return min(10, score)

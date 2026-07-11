"""Microstructure Agent (spec section 9.3). Scores executability and
order-book health. A single snapshot is explicitly never sufficient for a
strong signal — persistence across multiple snapshots is required.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class OrderBookSnapshot:
    spread_pct: Decimal
    depth_eur: Decimal
    buy_sell_ratio: Decimal  # >1 means more resting buy volume than sell


def microstructure_liquidity_score(
    snapshots: list[OrderBookSnapshot],
    max_spread_pct: Decimal,
    min_depth_eur: Decimal,
) -> int:
    if not snapshots:
        return 0

    healthy_count = 0
    ratios = []
    for snap in snapshots:
        if snap.spread_pct <= max_spread_pct and snap.depth_eur >= min_depth_eur:
            healthy_count += 1
        ratios.append(snap.buy_sell_ratio)

    persistence_fraction = Decimal(healthy_count) / Decimal(len(snapshots))
    if persistence_fraction < Decimal("0.5"):
        return 0

    base = int(persistence_fraction * 10)

    # A single snapshot, even a healthy one, cannot earn a top score —
    # spec section 9.3: "Eén losse orderboeksnapshot mag nooit voldoende
    # zijn om een sterk signaal te geven."
    if len(snapshots) < 3:
        base = min(base, 7)

    avg_ratio = sum(ratios) / len(ratios)
    if avg_ratio > Decimal("1.2"):
        base = min(10, base + 1)
    elif avg_ratio < Decimal("0.8"):
        base = max(0, base - 1)

    return base

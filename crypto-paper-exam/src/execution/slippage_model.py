"""Slippage estimation (spec section 6.3). Defaults to a fixed, conservative
0.10% each side whenever usable order-book depth isn't available — and even
when depth data exists, this model never selects the most favorable price
within a candle, only ever the same-or-worse one.
"""
from __future__ import annotations

from decimal import Decimal

from audit.config_freeze import ExecutionConfig

_IMPACT_SCALING = Decimal("1.0")


def estimate_slippage_pct(
    order_eur: Decimal,
    side: str,
    config: ExecutionConfig,
    book_depth_eur: Decimal | None = None,
) -> Decimal:
    default_pct = (
        config.default_slippage_buy_pct if side == "BUY" else config.default_slippage_sell_pct
    )
    if book_depth_eur is None or book_depth_eur <= 0:
        return default_pct

    impact_ratio = order_eur / book_depth_eur
    impact_pct = impact_ratio * _IMPACT_SCALING * Decimal("100")
    # Thin books can only make slippage worse than the default assumption,
    # never better.
    return max(default_pct, impact_pct)

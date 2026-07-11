"""Fee determination (spec section 6). Taker is the default; maker may only
be used when every strict precondition in section 6.2 is demonstrably true.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from audit.config_freeze import ExecutionConfig


@dataclass
class MakerEligibility:
    limit_price_set_before_order: bool
    order_not_immediately_marketable: bool
    market_later_traded_through_limit: bool
    sufficient_volume_available: bool
    realistically_fillable: bool

    @property
    def eligible(self) -> bool:
        """Section 6.2: 'Alleen het aanraken van de limietprijs is niet
        voldoende' — every condition must hold, not just a subset.
        """
        return all(
            (
                self.limit_price_set_before_order,
                self.order_not_immediately_marketable,
                self.market_later_traded_through_limit,
                self.sufficient_volume_available,
                self.realistically_fillable,
            )
        )


def determine_fee_pct(
    order_type: str,
    config: ExecutionConfig,
    maker_eligibility: MakerEligibility | None = None,
) -> Decimal:
    """order_type is 'MAKER' or 'TAKER'. A MAKER request without a satisfied
    MakerEligibility is silently and safely downgraded to TAKER — this
    system must never grant the cheaper fee on unproven grounds.
    """
    if order_type == "MAKER" and maker_eligibility is not None and maker_eligibility.eligible:
        return config.maker_fee_pct
    return config.taker_fee_pct

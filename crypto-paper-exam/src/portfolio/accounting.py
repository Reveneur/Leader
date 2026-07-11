"""Pure Decimal/eurocent arithmetic. No database access, no I/O — every
function here is a straight computation so it can be exhaustively unit
tested (spec section 23, "Wallettests") independent of the DB layer.

Money crosses this module's boundary as Decimal EUR and is converted to
integer eurocents only at the edge, per spec section 5.3: "bedragen bij
voorkeur als integer eurocenten" in storage, full Decimal precision
internally.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def eur_to_cents(amount: Decimal) -> int:
    return int((amount * HUNDRED).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_eur(cents: int) -> Decimal:
    return (Decimal(cents) / HUNDRED).quantize(CENT)


def pct_of(amount: Decimal, pct: Decimal) -> Decimal:
    """pct is expressed as a percentage number, e.g. Decimal('0.25') for 0.25%."""
    return amount * pct / HUNDRED


def apply_buy_costs(
    gross_eur: Decimal, fee_pct: Decimal, slippage_pct: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """A buy pays slippage as a worse (higher) effective price and a fee on
    top of the slippage-adjusted amount. Returns (total_cost_eur, fee_eur,
    slippage_eur) where total_cost_eur = gross_eur + slippage_eur + fee_eur.
    """
    slippage_eur = pct_of(gross_eur, slippage_pct)
    slippage_adjusted = gross_eur + slippage_eur
    fee_eur = pct_of(slippage_adjusted, fee_pct)
    total_cost_eur = slippage_adjusted + fee_eur
    return total_cost_eur, fee_eur, slippage_eur


def apply_sell_costs(
    gross_eur: Decimal, fee_pct: Decimal, slippage_pct: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """A sell pays slippage as a worse (lower) effective proceeds and a fee
    on top. Returns (net_proceeds_eur, fee_eur, slippage_eur) where
    net_proceeds_eur = gross_eur - slippage_eur - fee_eur.
    """
    slippage_eur = pct_of(gross_eur, slippage_pct)
    slippage_adjusted = gross_eur - slippage_eur
    fee_eur = pct_of(slippage_adjusted, fee_pct)
    net_proceeds_eur = slippage_adjusted - fee_eur
    return net_proceeds_eur, fee_eur, slippage_eur


def estimate_executable_sell_value(
    units: Decimal, bid_price: Decimal, fee_pct: Decimal, slippage_pct: Decimal
) -> Decimal:
    """The mark-to-market value of an open position per spec section 5: not
    the last traded price, but the estimated net proceeds if it were sold
    right now — bid price, minus expected slippage, minus expected fee.
    """
    gross = units * bid_price
    net_proceeds, _fee, _slippage = apply_sell_costs(gross, fee_pct, slippage_pct)
    return net_proceeds


def compute_equity_cents(cash_cents: int, holdings_value_cents: int) -> int:
    return cash_cents + holdings_value_cents


def compute_drawdown_pct(equity_cents: int, peak_equity_cents: int) -> Decimal:
    if peak_equity_cents <= 0:
        return Decimal("0")
    if equity_cents >= peak_equity_cents:
        return Decimal("0")
    drawdown = (Decimal(peak_equity_cents - equity_cents) / Decimal(peak_equity_cents)) * HUNDRED
    return drawdown.quantize(Decimal("0.0001"))

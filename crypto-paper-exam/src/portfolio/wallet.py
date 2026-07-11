"""The authoritative wallet. Cash is derived by replaying every order ever
recorded rather than trusting a mutable running balance — this makes the
ledger self-verifying: if wallet_snapshots and the order history ever
disagree, that disagreement is itself detectable (see audit.integrity).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Order, WalletSnapshot
from database.repositories import add_wallet_snapshot, peak_equity_cents
from portfolio.accounting import compute_drawdown_pct, compute_equity_cents


def order_cash_impact_cents(order: Order) -> int:
    """BUY debits gross+fee+slippage; SELL credits gross-fee-slippage."""
    if order.status != "FILLED":
        return 0
    magnitude = order.gross_value_eur_cents + order.fee_eur_cents + order.slippage_eur_cents
    if order.side == "BUY":
        return -magnitude
    if order.side == "SELL":
        return order.gross_value_eur_cents - order.fee_eur_cents - order.slippage_eur_cents
    raise ValueError(f"unknown order side: {order.side}")


def current_cash_cents(session: Session, initial_cash_cents: int) -> int:
    orders = session.execute(select(Order)).scalars().all()
    delta = sum(order_cash_impact_cents(o) for o in orders)
    return initial_cash_cents + delta


def cumulative_costs_cents(session: Session) -> int:
    orders = session.execute(select(Order)).scalars().all()
    return sum(o.fee_eur_cents + o.slippage_eur_cents for o in orders if o.status == "FILLED")


@dataclass
class HoldingsValuation:
    holdings_value_cents: int
    unrealized_pnl_cents: int


class Wallet:
    def __init__(self, session: Session, initial_cash_eur: Decimal) -> None:
        self.session = session
        self.initial_cash_cents = int(initial_cash_eur * 100)

    def cash_cents(self) -> int:
        return current_cash_cents(self.session, self.initial_cash_cents)

    def cumulative_costs_cents(self) -> int:
        return cumulative_costs_cents(self.session)

    def realized_pnl_cents(self) -> int:
        from database.repositories import closed_positions

        return sum(p.realized_pnl_eur_cents or 0 for p in closed_positions(self.session))

    def record_snapshot(
        self,
        run_id: str,
        timestamp: dt.datetime,
        holdings_valuation: HoldingsValuation,
    ) -> WalletSnapshot:
        cash = self.cash_cents()
        equity = compute_equity_cents(cash, holdings_valuation.holdings_value_cents)
        prior_peak = peak_equity_cents(self.session)
        peak = max(prior_peak, equity)
        drawdown = compute_drawdown_pct(equity, peak)

        snapshot = WalletSnapshot(
            run_id=run_id,
            timestamp=timestamp,
            cash_eur_cents=cash,
            holdings_value_eur_cents=holdings_valuation.holdings_value_cents,
            equity_eur_cents=equity,
            realized_pnl_eur_cents=self.realized_pnl_cents(),
            unrealized_pnl_eur_cents=holdings_valuation.unrealized_pnl_cents,
            cumulative_costs_eur_cents=self.cumulative_costs_cents(),
            peak_equity_eur_cents=peak,
            drawdown_pct=drawdown,
        )
        return add_wallet_snapshot(self.session, snapshot)

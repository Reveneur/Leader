"""Chart data preparation. Returns plain pandas DataFrames so both the
Streamlit dashboard and any future export can render them without this
module depending on a specific plotting backend.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import HourlyRun, WalletSnapshot


def equity_curve(session: Session) -> pd.DataFrame:
    rows = session.execute(select(WalletSnapshot).order_by(WalletSnapshot.timestamp.asc())).scalars().all()
    return pd.DataFrame(
        {
            "timestamp": [r.timestamp for r in rows],
            "equity_eur": [r.equity_eur_cents / 100 for r in rows],
            "cash_eur": [r.cash_eur_cents / 100 for r in rows],
            "holdings_eur": [r.holdings_value_eur_cents / 100 for r in rows],
            "drawdown_pct": [float(r.drawdown_pct) for r in rows],
        }
    )


def benchmark_comparison(session: Session) -> pd.DataFrame:
    rows = session.execute(select(HourlyRun).order_by(HourlyRun.scheduled_timestamp.asc())).scalars().all()
    return pd.DataFrame(
        {
            "timestamp": [r.scheduled_timestamp for r in rows],
            "wallet_eur": [r.equity_eur_cents / 100 for r in rows],
            "btc_benchmark_eur": [r.btc_benchmark_eur_cents / 100 for r in rows],
            "cash_benchmark_eur": [r.cash_benchmark_eur_cents / 100 for r in rows],
        }
    )

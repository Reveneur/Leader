"""Streamlit dashboard (spec section 4.6 / 21). Reads exclusively from the
SQLite database — never recomputes a trading decision — so what's shown
here always matches the authoritative ledger.

Run with: streamlit run dashboard/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402

from database.connection import init_db, session_scope  # noqa: E402
from database.repositories import (  # noqa: E402
    all_positions,
    list_hourly_runs,
    open_positions,
)
from reporting.charts import benchmark_comparison, equity_curve  # noqa: E402
from reporting.final_report import compute_final_report, render_final_report  # noqa: E402
from settings import get_settings  # noqa: E402

st.set_page_config(page_title="Exam V1 — Crypto Paper Trading", layout="wide")

settings = get_settings()
init_db(settings)

st.title("Exam V1 — Crypto Paper Trading Dashboard")

with session_scope(settings) as session:
    runs = list_hourly_runs(session)
    open_pos = open_positions(session)
    closed_pos = [p for p in all_positions(session) if p.status == "CLOSED"]
    equity_df = equity_curve(session)
    benchmark_df = benchmark_comparison(session)

    if not runs:
        st.warning("No hourly runs recorded yet. Run scripts/initialize_exam.py and scripts/run_once.py first.")
        st.stop()

    latest = runs[-1]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Walletwaarde", f"EUR {latest.equity_eur_cents / 100:.2f}")
    col2.metric("Cash", f"EUR {latest.cash_eur_cents / 100:.2f}")
    col3.metric("Gerealiseerd", f"EUR {latest.realized_pnl_eur_cents / 100:.2f}")
    col4.metric("Ongerealiseerd", f"EUR {latest.unrealized_pnl_eur_cents / 100:.2f}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Totale kosten", f"EUR {latest.cumulative_costs_eur_cents / 100:.2f}")
    peak = max((r.equity_eur_cents for r in runs), default=latest.equity_eur_cents)
    drawdown = (peak - latest.equity_eur_cents) / peak * 100 if peak else 0
    col6.metric("Actuele drawdown", f"{drawdown:.2f}%")
    col7.metric("Aantal transacties", str(len(closed_pos)))
    win_rate = (
        sum(1 for p in closed_pos if p.realized_pnl_eur_cents > 0) / len(closed_pos) * 100
        if closed_pos
        else 0
    )
    col8.metric("Winstpercentage", f"{win_rate:.1f}%")

    st.subheader("Open posities")
    if open_pos:
        st.dataframe(
            [
                {
                    "asset": p.asset,
                    "units": str(p.remaining_units),
                    "entry_price": str(p.entry_price),
                    "stop": str(p.stop_price),
                    "target_1": str(p.target_1),
                    "current_value_eur": p.current_value_eur_cents / 100,
                    "unrealized_pnl_eur": p.unrealized_pnl_eur_cents / 100,
                }
                for p in open_pos
            ]
        )
    else:
        st.info("Geen open posities.")

    st.subheader("Walletwaarde vs. benchmarks")
    if not benchmark_df.empty:
        st.line_chart(
            benchmark_df.set_index("timestamp")[["wallet_eur", "btc_benchmark_eur", "cash_benchmark_eur"]]
        )

    st.subheader("Drawdown")
    if not equity_df.empty:
        st.line_chart(equity_df.set_index("timestamp")[["drawdown_pct"]])

    st.subheader("Transactiehistorie")
    if closed_pos:
        st.dataframe(
            [
                {
                    "asset": p.asset,
                    "opened_at": p.opened_at,
                    "closed_at": p.closed_at,
                    "realized_pnl_eur": p.realized_pnl_eur_cents / 100,
                    "result_pct": str(p.result_pct),
                    "classification": p.classification,
                    "sell_reason": p.sell_reason,
                }
                for p in closed_pos
            ]
        )
    else:
        st.info("Nog geen afgesloten transacties.")

    st.subheader("Uurhistorie")
    st.dataframe(
        [
            {
                "run_id": r.run_id,
                "scheduled": r.scheduled_timestamp,
                "action": r.action,
                "equity_eur": r.equity_eur_cents / 100,
                "regime": r.regime,
                "top_candidate": r.top_candidate,
                "data_status": r.data_status,
            }
            for r in reversed(runs)
        ]
    )

    st.subheader("Laatste beslissing")
    st.write(f"**{latest.action}** — {latest.explanation}")
    if latest.contradiction:
        st.caption(f"Belangrijkste reden/contradictie: {latest.contradiction}")

    if st.button("Genereer eindrapport"):
        from audit.config_freeze import load_strategy_config

        config = load_strategy_config(settings.strategy_config_path)
        report = compute_final_report(session, config.wallet.initial_cash_eur)
        st.text(render_final_report(report))

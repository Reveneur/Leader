"""Human-readable per-hour report (spec section 4.5, step 12)."""
from __future__ import annotations

from database.models import HourlyRun


def render_hourly_report(run: HourlyRun) -> str:
    lines = [
        f"Run {run.run_id} ({run.strategy_version})",
        f"Scheduled: {run.scheduled_timestamp.isoformat()}",
        f"Action: {run.action}",
        f"Cash: EUR {run.cash_eur_cents / 100:.2f}  |  Positiewaarde: EUR {run.position_value_eur_cents / 100:.2f}",
        f"Walletwaarde: EUR {run.equity_eur_cents / 100:.2f}",
        f"BTC-benchmark: EUR {run.btc_benchmark_eur_cents / 100:.2f}  |  Cashbenchmark: EUR {run.cash_benchmark_eur_cents / 100:.2f}",
        f"Gerealiseerd: EUR {run.realized_pnl_eur_cents / 100:.2f}  |  Ongerealiseerd: EUR {run.unrealized_pnl_eur_cents / 100:.2f}",
        f"Cumulatieve kosten: EUR {run.cumulative_costs_eur_cents / 100:.2f}",
        f"Regime: {run.regime or 'n.v.t.'}  |  Topkandidaat: {run.top_candidate or 'n.v.t.'}  |  Confidence: {run.confidence if run.confidence is not None else 'n.v.t.'}",
        f"Datastatus: {run.data_status}  |  Sheetstatus: {run.sheet_status}",
        f"Toelichting: {run.explanation or ''}",
    ]
    if run.contradiction:
        lines.append(f"Belangrijkste contradictie: {run.contradiction}")
    if run.error_message:
        lines.append(f"Fout: {run.error_message}")
    return "\n".join(lines)

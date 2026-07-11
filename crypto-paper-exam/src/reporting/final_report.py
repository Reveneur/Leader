"""End-of-exam final report (spec section 25). Every figure here is
reconstructed purely from persisted data — hourly_runs, positions, orders,
wallet_snapshots, benchmarks, audit_events — never from live recomputation,
so the report itself is reproducible (spec section 24, criterion 14).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from audit.integrity import run_integrity_checks
from database.models import AuditEvent, HourlyRun, Position, WalletSnapshot
from database.repositories import all_positions, list_hourly_runs


@dataclass
class FinalReport:
    begin_value_eur: Decimal
    end_value_eur: Decimal
    absolute_result_eur: Decimal
    result_pct: Decimal
    btc_benchmark_eur: Decimal
    cash_benchmark_eur: Decimal
    technical_shadow_eur: Decimal
    catalyst_shadow_eur: Decimal
    max_drawdown_pct: Decimal
    total_costs_eur: Decimal
    trade_count: int
    win_rate_pct: Decimal
    avg_win_eur: Decimal
    avg_loss_eur: Decimal
    profit_factor: Decimal | None
    avg_hold_duration_hours: Decimal
    best_trade_eur: Decimal
    worst_trade_eur: Decimal
    cash_hours: int
    hold_hours: int
    buy_decisions: int
    sell_decisions: int
    data_incidents: int
    sheet_errors: int
    rule_violations: int
    correct_count: int
    wrong_count: int
    unresolved_count: int
    grade: str
    reliability_conclusion: str
    profitability_conclusion: str


def _closed_positions(session: Session) -> list[Position]:
    return [p for p in all_positions(session) if p.status == "CLOSED"]


def grade_exam(
    result_pct: Decimal,
    beats_btc: bool,
    max_drawdown_pct: Decimal,
    trade_count: int,
    integrity_clean: bool,
    rule_violations: int,
) -> str:
    if not integrity_clean or rule_violations > 0:
        return "F"
    if result_pct < 0:
        return "D"
    if result_pct == 0 or trade_count == 0:
        return "C"
    if beats_btc and max_drawdown_pct <= 12:
        return "A"
    return "B"


def compute_final_report(session: Session, initial_cash_eur: Decimal) -> FinalReport:
    runs = list_hourly_runs(session)
    positions = _closed_positions(session)

    snapshots = session.execute(select(WalletSnapshot).order_by(WalletSnapshot.timestamp.asc())).scalars().all()
    last_snapshot = snapshots[-1] if snapshots else None
    end_value = Decimal(last_snapshot.equity_eur_cents) / 100 if last_snapshot else initial_cash_eur

    last_run = runs[-1] if runs else None
    btc_benchmark = Decimal(last_run.btc_benchmark_eur_cents) / 100 if last_run else initial_cash_eur
    cash_benchmark = Decimal(last_run.cash_benchmark_eur_cents) / 100 if last_run else initial_cash_eur

    from database.repositories import latest_benchmark

    bench = latest_benchmark(session)
    technical_shadow = Decimal(bench.technical_shadow_value_eur_cents) / 100 if bench else initial_cash_eur
    catalyst_shadow = Decimal(bench.catalyst_shadow_value_eur_cents) / 100 if bench else initial_cash_eur

    max_drawdown = max((s.drawdown_pct for s in snapshots), default=Decimal("0"))
    total_costs = Decimal(last_snapshot.cumulative_costs_eur_cents) / 100 if last_snapshot else Decimal("0")

    trade_pnls = [Decimal(p.realized_pnl_eur_cents) / 100 for p in positions]
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]

    win_rate = (Decimal(len(wins)) / Decimal(len(trade_pnls)) * 100) if trade_pnls else Decimal("0")
    avg_win = (sum(wins) / len(wins)) if wins else Decimal("0")
    avg_loss = (sum(losses) / len(losses)) if losses else Decimal("0")
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
    durations = [p.duration_seconds for p in positions if p.duration_seconds is not None]
    avg_hold_hours = (Decimal(sum(durations)) / len(durations) / 3600) if durations else Decimal("0")
    best_trade = max(trade_pnls) if trade_pnls else Decimal("0")
    worst_trade = min(trade_pnls) if trade_pnls else Decimal("0")

    cash_hours = sum(1 for r in runs if r.action == "CASH")
    hold_hours = sum(1 for r in runs if r.action == "HOLD")
    buy_decisions = sum(1 for r in runs if r.action == "BUY")
    sell_decisions = sum(1 for r in runs if r.action == "SELL")
    data_incidents = sum(1 for r in runs if r.data_status not in ("OK",))
    sheet_errors = sum(1 for r in runs if r.sheet_status not in ("OK",))

    critical_events = session.execute(
        select(AuditEvent).where(AuditEvent.severity.in_(("ERROR", "CRITICAL")))
    ).scalars().all()
    rule_violations = len(critical_events)

    correct = sum(1 for p in positions if p.classification == "CORRECT")
    wrong = sum(1 for p in positions if p.classification == "WRONG")
    unresolved = sum(1 for p in positions if p.classification == "UNRESOLVED")

    result_pct = ((end_value - initial_cash_eur) / initial_cash_eur * 100) if initial_cash_eur else Decimal("0")
    beats_btc = end_value > btc_benchmark

    integrity = run_integrity_checks(session)

    grade = grade_exam(
        result_pct=result_pct,
        beats_btc=beats_btc,
        max_drawdown_pct=max_drawdown,
        trade_count=len(positions),
        integrity_clean=integrity.is_clean,
        rule_violations=rule_violations,
    )

    reliability_conclusion = (
        "Operationeel betrouwbaar: geen ontbrekende uren, geen dubbele mutaties, alle kosten verwerkt."
        if integrity.is_clean
        else f"Operationele integriteitsproblemen gevonden: {len(integrity.findings)} bevinding(en)."
    )
    profitability_conclusion = (
        f"Resultaat {result_pct:.2f}% over {len(positions)} afgesloten trade(s); "
        f"{'versloeg' if beats_btc else 'versloeg niet'} de BTC buy-and-hold benchmark."
    )

    return FinalReport(
        begin_value_eur=initial_cash_eur,
        end_value_eur=end_value,
        absolute_result_eur=end_value - initial_cash_eur,
        result_pct=result_pct,
        btc_benchmark_eur=btc_benchmark,
        cash_benchmark_eur=cash_benchmark,
        technical_shadow_eur=technical_shadow,
        catalyst_shadow_eur=catalyst_shadow,
        max_drawdown_pct=max_drawdown,
        total_costs_eur=total_costs,
        trade_count=len(positions),
        win_rate_pct=win_rate,
        avg_win_eur=avg_win,
        avg_loss_eur=avg_loss,
        profit_factor=profit_factor,
        avg_hold_duration_hours=avg_hold_hours,
        best_trade_eur=best_trade,
        worst_trade_eur=worst_trade,
        cash_hours=cash_hours,
        hold_hours=hold_hours,
        buy_decisions=buy_decisions,
        sell_decisions=sell_decisions,
        data_incidents=data_incidents,
        sheet_errors=sheet_errors,
        rule_violations=rule_violations,
        correct_count=correct,
        wrong_count=wrong,
        unresolved_count=unresolved,
        grade=grade,
        reliability_conclusion=reliability_conclusion,
        profitability_conclusion=profitability_conclusion,
    )


def render_final_report(report: FinalReport) -> str:
    pf = f"{report.profit_factor:.2f}" if report.profit_factor is not None else "n.v.t. (geen verliestrades)"
    return (
        "=== Exam V1 — Eindrapport ===\n"
        f"Beginwaarde: EUR {report.begin_value_eur:.2f}\n"
        f"Eindwaarde: EUR {report.end_value_eur:.2f}\n"
        f"Absoluut resultaat: EUR {report.absolute_result_eur:.2f}\n"
        f"Procentueel resultaat: {report.result_pct:.2f}%\n"
        f"BTC-benchmark: EUR {report.btc_benchmark_eur:.2f}\n"
        f"Cashbenchmark: EUR {report.cash_benchmark_eur:.2f}\n"
        f"Technisch schaduwresultaat: EUR {report.technical_shadow_eur:.2f}\n"
        f"Catalyst-schaduwresultaat: EUR {report.catalyst_shadow_eur:.2f}\n"
        f"Maximale drawdown: {report.max_drawdown_pct:.2f}%\n"
        f"Totale kosten: EUR {report.total_costs_eur:.2f}\n"
        f"Aantal transacties: {report.trade_count}\n"
        f"Winstpercentage: {report.win_rate_pct:.2f}%\n"
        f"Gemiddelde winst: EUR {report.avg_win_eur:.2f}  |  Gemiddeld verlies: EUR {report.avg_loss_eur:.2f}\n"
        f"Profit factor: {pf}\n"
        f"Gemiddelde houdduur: {report.avg_hold_duration_hours:.1f} uur\n"
        f"Beste trade: EUR {report.best_trade_eur:.2f}  |  Slechtste trade: EUR {report.worst_trade_eur:.2f}\n"
        f"CASH-uren: {report.cash_hours}  |  HOLD-uren: {report.hold_hours}\n"
        f"BUY-beslissingen: {report.buy_decisions}  |  SELL-beslissingen: {report.sell_decisions}\n"
        f"Datastoringen: {report.data_incidents}  |  Sheet-fouten: {report.sheet_errors}\n"
        f"Overtreden regels: {report.rule_violations}\n"
        f"Signaalattributie — CORRECT: {report.correct_count}  WRONG: {report.wrong_count}  UNRESOLVED: {report.unresolved_count}\n"
        f"\nConclusie (betrouwbaarheid): {report.reliability_conclusion}\n"
        f"Conclusie (winstgevendheid): {report.profitability_conclusion}\n"
        f"\nEindbeoordeling: {report.grade}\n"
    )

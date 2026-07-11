"""Daily rollup over hourly_runs (spec section 21's daily_report.py)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from database.models import HourlyRun


@dataclass
class DailySummary:
    date: dt.date
    hours_logged: int
    buy_count: int
    sell_count: int
    hold_count: int
    cash_count: int
    end_of_day_equity_cents: int
    end_of_day_btc_benchmark_cents: int
    errors: int


def summarize_day(runs: list[HourlyRun], date: dt.date) -> DailySummary:
    day_runs = sorted(
        (r for r in runs if r.scheduled_timestamp.date() == date),
        key=lambda r: r.scheduled_timestamp,
    )
    if not day_runs:
        return DailySummary(date, 0, 0, 0, 0, 0, 0, 0, 0)

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0, "CASH": 0}
    errors = 0
    for run in day_runs:
        counts[run.action] = counts.get(run.action, 0) + 1
        if run.error_message:
            errors += 1

    last = day_runs[-1]
    return DailySummary(
        date=date,
        hours_logged=len(day_runs),
        buy_count=counts.get("BUY", 0),
        sell_count=counts.get("SELL", 0),
        hold_count=counts.get("HOLD", 0),
        cash_count=counts.get("CASH", 0),
        end_of_day_equity_cents=last.equity_eur_cents,
        end_of_day_btc_benchmark_cents=last.btc_benchmark_eur_cents,
        errors=errors,
    )


def render_daily_report(summary: DailySummary) -> str:
    return (
        f"Dagrapport {summary.date.isoformat()}\n"
        f"Uren gelogd: {summary.hours_logged}\n"
        f"BUY: {summary.buy_count}  SELL: {summary.sell_count}  "
        f"HOLD: {summary.hold_count}  CASH: {summary.cash_count}\n"
        f"Walletwaarde einde dag: EUR {summary.end_of_day_equity_cents / 100:.2f}\n"
        f"BTC-benchmark einde dag: EUR {summary.end_of_day_btc_benchmark_cents / 100:.2f}\n"
        f"Fouten: {summary.errors}"
    )

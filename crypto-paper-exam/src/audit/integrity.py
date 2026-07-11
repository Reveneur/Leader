"""Post-hoc integrity checks over the persisted exam data (spec section 23,
"Audittests", and section 24 acceptance criteria). Run via
scripts/verify_integrity.py at any time — including as the input to the
final report's "operational reliability" conclusion (section 25).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from database.repositories import list_hourly_runs, all_positions, orders_for_run


@dataclass
class Finding:
    check: str
    severity: str  # INFO, WARNING, ERROR, CRITICAL
    description: str


@dataclass
class IntegrityReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, check: str, severity: str, description: str) -> None:
        self.findings.append(Finding(check, severity, description))

    @property
    def is_clean(self) -> bool:
        return not any(f.severity in ("ERROR", "CRITICAL") for f in self.findings)


def check_no_missing_hours(
    session: Session, start: dt.datetime, end: dt.datetime, report: IntegrityReport
) -> None:
    runs = list_hourly_runs(session)
    scheduled = {r.scheduled_timestamp.replace(minute=0, second=0, microsecond=0) for r in runs}
    cursor = start.replace(minute=0, second=0, microsecond=0)
    missing = []
    while cursor <= end:
        if cursor not in scheduled:
            missing.append(cursor)
        cursor += dt.timedelta(hours=1)
    if missing:
        report.add(
            "no_missing_hours",
            "ERROR",
            f"{len(missing)} hourly run(s) missing: {[m.isoformat() for m in missing]}",
        )


def check_runs_completed(session: Session, report: IntegrityReport) -> None:
    for run in list_hourly_runs(session):
        if run.started_at is not None and run.completed_at is None:
            report.add(
                "runs_completed",
                "ERROR",
                f"run {run.run_id} started but never completed (crashed mid-run?)",
            )


def check_position_chronology(session: Session, report: IntegrityReport) -> None:
    for position in all_positions(session):
        if position.closed_at is not None and position.closed_at < position.opened_at:
            report.add(
                "position_chronology",
                "CRITICAL",
                f"position {position.id} closed_at before opened_at",
            )
        if position.status == "CLOSED" and position.closed_at is None:
            report.add(
                "position_chronology",
                "ERROR",
                f"position {position.id} marked CLOSED but has no closed_at",
            )


def check_orders_have_costs(session: Session, report: IntegrityReport) -> None:
    for run in list_hourly_runs(session):
        for order in orders_for_run(session, run.run_id):
            if order.status == "FILLED" and (order.fee_eur_cents is None or order.slippage_eur_cents is None):
                report.add(
                    "orders_have_costs",
                    "CRITICAL",
                    f"order {order.id} (run {run.run_id}) filled without recorded fee/slippage",
                )


def check_no_duplicate_runs(session: Session, report: IntegrityReport) -> None:
    runs = list_hourly_runs(session)
    seen: dict[dt.datetime, str] = {}
    for run in runs:
        key = run.scheduled_timestamp
        if key in seen and seen[key] != run.run_id:
            report.add(
                "no_duplicate_runs",
                "CRITICAL",
                f"scheduled hour {key.isoformat()} has multiple run_ids: {seen[key]}, {run.run_id}",
            )
        seen[key] = run.run_id


def run_integrity_checks(
    session: Session,
    exam_start: dt.datetime | None = None,
    exam_end: dt.datetime | None = None,
) -> IntegrityReport:
    report = IntegrityReport()
    if exam_start is not None and exam_end is not None:
        check_no_missing_hours(session, exam_start, exam_end, report)
    check_runs_completed(session, report)
    check_position_chronology(session, report)
    check_orders_have_costs(session, report)
    check_no_duplicate_runs(session, report)
    return report

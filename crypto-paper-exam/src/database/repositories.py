"""Thin, explicit data-access functions. Every function takes an open
SQLAlchemy Session (see database.connection.session_scope) so callers control
the transaction boundary — a wallet mutation and its hourly_run row must
commit atomically or not at all.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    AuditEvent,
    Benchmark,
    Candle,
    ConfigFreeze,
    EngineState,
    HourlyRun,
    Order,
    Position,
    SignalScore,
    WalletSnapshot,
)


# --- hourly_runs -----------------------------------------------------------

def get_hourly_run(session: Session, run_id: str) -> HourlyRun | None:
    return session.get(HourlyRun, run_id)


def run_exists(session: Session, run_id: str) -> bool:
    return get_hourly_run(session, run_id) is not None


def run_completed(session: Session, run_id: str) -> bool:
    run = get_hourly_run(session, run_id)
    return run is not None and run.completed_at is not None


def latest_hourly_run(session: Session) -> HourlyRun | None:
    stmt = select(HourlyRun).order_by(HourlyRun.scheduled_timestamp.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def list_hourly_runs(session: Session, limit: int | None = None) -> list[HourlyRun]:
    stmt = select(HourlyRun).order_by(HourlyRun.scheduled_timestamp.asc())
    if limit:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def upsert_hourly_run(session: Session, run: HourlyRun) -> HourlyRun:
    existing = session.get(HourlyRun, run.run_id)
    if existing is None:
        session.add(run)
        return run
    for column in HourlyRun.__table__.columns.keys():
        if column == "run_id":
            continue
        setattr(existing, column, getattr(run, column))
    return existing


# --- wallet_snapshots --------------------------------------------------------

def add_wallet_snapshot(session: Session, snapshot: WalletSnapshot) -> WalletSnapshot:
    session.add(snapshot)
    return snapshot


def latest_wallet_snapshot(session: Session) -> WalletSnapshot | None:
    stmt = select(WalletSnapshot).order_by(WalletSnapshot.timestamp.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def peak_equity_cents(session: Session) -> int:
    stmt = select(WalletSnapshot.equity_eur_cents).order_by(
        WalletSnapshot.equity_eur_cents.desc()
    ).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result or 0


# --- positions ---------------------------------------------------------------

def add_position(session: Session, position: Position) -> Position:
    session.add(position)
    session.flush()
    return position


def get_position(session: Session, position_id: int) -> Position | None:
    return session.get(Position, position_id)


def open_positions(session: Session) -> list[Position]:
    stmt = select(Position).where(Position.status == "OPEN")
    return list(session.execute(stmt).scalars().all())


def closed_positions(session: Session, since: dt.datetime | None = None) -> list[Position]:
    stmt = select(Position).where(Position.status == "CLOSED")
    if since is not None:
        stmt = stmt.where(Position.closed_at >= since)
    return list(session.execute(stmt).scalars().all())


def all_positions(session: Session) -> list[Position]:
    return list(session.execute(select(Position)).scalars().all())


# --- orders --------------------------------------------------------------

def add_order(session: Session, order: Order) -> Order:
    session.add(order)
    session.flush()
    return order


def orders_for_run(session: Session, run_id: str) -> list[Order]:
    stmt = select(Order).where(Order.run_id == run_id)
    return list(session.execute(stmt).scalars().all())


# --- signal_scores ---------------------------------------------------------

def add_signal_score(session: Session, score: SignalScore) -> SignalScore:
    session.add(score)
    return score


def signal_scores_for_run(session: Session, run_id: str) -> list[SignalScore]:
    stmt = select(SignalScore).where(SignalScore.run_id == run_id)
    return list(session.execute(stmt).scalars().all())


# --- candles ---------------------------------------------------------------

def upsert_candle(session: Session, candle: Candle) -> Candle:
    stmt = select(Candle).where(
        Candle.market == candle.market,
        Candle.interval == candle.interval,
        Candle.timestamp == candle.timestamp,
        Candle.source == candle.source,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        existing.open, existing.high, existing.low = candle.open, candle.high, candle.low
        existing.close, existing.volume = candle.close, candle.volume
        return existing
    session.add(candle)
    return candle


def candles_between(
    session: Session,
    market: str,
    interval: str,
    start: dt.datetime,
    end: dt.datetime,
) -> list[Candle]:
    stmt = (
        select(Candle)
        .where(
            Candle.market == market,
            Candle.interval == interval,
            Candle.timestamp >= start,
            Candle.timestamp <= end,
        )
        .order_by(Candle.timestamp.asc())
    )
    return list(session.execute(stmt).scalars().all())


def latest_candle(session: Session, market: str, interval: str) -> Candle | None:
    stmt = (
        select(Candle)
        .where(Candle.market == market, Candle.interval == interval)
        .order_by(Candle.timestamp.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


# --- benchmarks --------------------------------------------------------------

def add_benchmark(session: Session, benchmark: Benchmark) -> Benchmark:
    session.add(benchmark)
    return benchmark


def latest_benchmark(session: Session) -> Benchmark | None:
    stmt = select(Benchmark).order_by(Benchmark.timestamp.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


# --- audit_events ------------------------------------------------------------

def add_audit_event(session: Session, event: AuditEvent) -> AuditEvent:
    session.add(event)
    return event


def audit_events_for_run(session: Session, run_id: str) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.run_id == run_id)
    return list(session.execute(stmt).scalars().all())


# --- config_freeze -----------------------------------------------------------

def active_config_freeze(session: Session) -> ConfigFreeze | None:
    stmt = (
        select(ConfigFreeze)
        .where(ConfigFreeze.active.is_(True))
        .order_by(ConfigFreeze.frozen_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def add_config_freeze(session: Session, freeze: ConfigFreeze) -> ConfigFreeze:
    session.add(freeze)
    return freeze


# --- engine_state ------------------------------------------------------------

def get_engine_state(session: Session, key: str) -> str | None:
    row = session.get(EngineState, key)
    return row.value if row is not None else None


def set_engine_state(session: Session, key: str, value: str) -> EngineState:
    row = session.get(EngineState, key)
    if row is None:
        row = EngineState(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    return row

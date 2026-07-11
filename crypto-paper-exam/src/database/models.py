"""SQLAlchemy ORM models — the authoritative data store for Exam V1.

Money is stored as integer eurocents (never float) so wallet arithmetic is
exact. Crypto units, prices, and percentages are stored via PreciseDecimal
(exact text, not SQLAlchemy's generic Numeric — see that class for why) so
nothing in the ledger ever round-trips through a float.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PreciseDecimal(TypeDecorator):
    """Stores Decimal values as exact text rather than SQLAlchemy's generic
    Numeric type, which on SQLite binds Decimal through a float conversion
    (`to_float`) and silently corrupts precision on the way in — the exact
    float noise this project's ledger must never have (spec section 5.3:
    "Berekeningen moeten intern met voldoende decimalen worden uitgevoerd").
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:
        if value is None:
            return None
        return format(Decimal(value), "f")

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


UNITS = PreciseDecimal()
PRICE = PreciseDecimal()
PCT = PreciseDecimal()


class UTCDateTime(TypeDecorator):
    """Stores datetimes as naive UTC (SQLite has no real tz-aware storage —
    DateTime(timezone=True) alone silently round-trips to naive and would
    otherwise make every closed_at-opened_at duration calculation crash
    with "can't subtract offset-naive and offset-aware datetimes" the
    moment an object is re-read from the DB within the same session).
    Every datetime that reaches this type must be timezone-aware; it comes
    back out timezone-aware (UTC) too, so application code never has to
    think about the storage detail.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime {value!r} passed where a timezone-aware UTC datetime is required")
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=dt.timezone.utc)


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class HourlyRun(Base):
    """One authoritative row per scheduled hour. run_id is the idempotency key."""

    __tablename__ = "hourly_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scheduled_timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    started_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    strategy_version: Mapped[str] = mapped_column(String(32))

    action: Mapped[str] = mapped_column(String(16))  # BUY, SELL, HOLD, CASH
    top_candidate: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[Decimal | None] = mapped_column(PCT)
    regime: Mapped[str | None] = mapped_column(String(16))
    contradiction: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)

    data_status: Mapped[str] = mapped_column(String(16), default="OK")
    sheet_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    error_message: Mapped[str | None] = mapped_column(Text)

    cash_eur_cents: Mapped[int] = mapped_column(Integer)
    asset: Mapped[str | None] = mapped_column(String(32))
    units: Mapped[Decimal | None] = mapped_column(UNITS)
    position_value_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    equity_eur_cents: Mapped[int] = mapped_column(Integer)
    btc_benchmark_eur_cents: Mapped[int] = mapped_column(Integer)
    cash_benchmark_eur_cents: Mapped[int] = mapped_column(Integer)
    realized_pnl_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    unrealized_pnl_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    cumulative_costs_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    core_scores_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class WalletSnapshot(Base):
    __tablename__ = "wallet_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64))  # soft reference to hourly_runs.run_id, not a hard FK: some tables (esp. Order/Position) may legitimately be written before the parent hourly_runs row is finalized within a run
    timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    cash_eur_cents: Mapped[int] = mapped_column(Integer)
    holdings_value_eur_cents: Mapped[int] = mapped_column(Integer)
    equity_eur_cents: Mapped[int] = mapped_column(Integer)
    realized_pnl_eur_cents: Mapped[int] = mapped_column(Integer)
    unrealized_pnl_eur_cents: Mapped[int] = mapped_column(Integer)
    cumulative_costs_eur_cents: Mapped[int] = mapped_column(Integer)
    peak_equity_eur_cents: Mapped[int] = mapped_column(Integer)
    drawdown_pct: Mapped[Decimal] = mapped_column(PCT)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # OPEN, CLOSED
    strategy_version: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    closed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())

    entry_price: Mapped[Decimal] = mapped_column(PRICE)
    entry_units: Mapped[Decimal] = mapped_column(UNITS)
    gross_spend_eur_cents: Mapped[int] = mapped_column(Integer)
    entry_fee_eur_cents: Mapped[int] = mapped_column(Integer)
    entry_slippage_eur_cents: Mapped[int] = mapped_column(Integer)
    entry_spread_pct: Mapped[Decimal | None] = mapped_column(PCT)
    entry_order_type: Mapped[str] = mapped_column(String(16), default="TAKER")

    stop_price: Mapped[Decimal] = mapped_column(PRICE)
    target_1: Mapped[Decimal | None] = mapped_column(PRICE)
    target_2: Mapped[Decimal | None] = mapped_column(PRICE)
    trailing_rule: Mapped[str | None] = mapped_column(Text)

    remaining_units: Mapped[Decimal] = mapped_column(UNITS)
    current_value_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    realized_pnl_eur_cents: Mapped[int] = mapped_column(Integer, default=0)
    unrealized_pnl_eur_cents: Mapped[int] = mapped_column(Integer, default=0)

    regime_at_entry: Mapped[str | None] = mapped_column(String(16))
    scores_json: Mapped[str | None] = mapped_column(Text)
    contradictions_json: Mapped[str | None] = mapped_column(Text)
    missing_data_json: Mapped[str | None] = mapped_column(Text)
    catalyst: Mapped[str | None] = mapped_column(Text)
    onchain_confirmation: Mapped[str | None] = mapped_column(Text)
    thesis: Mapped[str | None] = mapped_column(Text)
    expected_hold_period: Mapped[str | None] = mapped_column(String(64))
    max_eur_risk_cents: Mapped[int | None] = mapped_column(Integer)
    expected_gross_profit_eur_cents: Mapped[int | None] = mapped_column(Integer)
    expected_net_profit_eur_cents: Mapped[int | None] = mapped_column(Integer)
    net_reward_risk: Mapped[Decimal | None] = mapped_column(PCT)
    confidence: Mapped[Decimal | None] = mapped_column(PCT)
    invalidation_criterion: Mapped[str | None] = mapped_column(Text)
    sources_json: Mapped[str | None] = mapped_column(Text)

    sell_reason: Mapped[str | None] = mapped_column(Text)
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    exit_spread_pct: Mapped[Decimal | None] = mapped_column(PCT)
    exit_slippage_eur_cents: Mapped[int | None] = mapped_column(Integer)
    exit_fee_eur_cents: Mapped[int | None] = mapped_column(Integer)
    net_proceeds_eur_cents: Mapped[int | None] = mapped_column(Integer)
    result_pct: Mapped[Decimal | None] = mapped_column(PCT)
    mfe_pct: Mapped[Decimal | None] = mapped_column(PCT)  # max favorable excursion
    mae_pct: Mapped[Decimal | None] = mapped_column(PCT)  # max adverse excursion
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    correct_signals_json: Mapped[str | None] = mapped_column(Text)
    wrong_signals_json: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str | None] = mapped_column(String(16))  # CORRECT/WRONG/UNRESOLVED


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64))  # soft reference to hourly_runs.run_id, not a hard FK: some tables (esp. Order/Position) may legitimately be written before the parent hourly_runs row is finalized within a run
    position_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("positions.id"))
    side: Mapped[str] = mapped_column(String(8))  # BUY, SELL
    order_type: Mapped[str] = mapped_column(String(16))  # MARKET, LIMIT
    requested_price: Mapped[Decimal | None] = mapped_column(PRICE)
    executed_price: Mapped[Decimal | None] = mapped_column(PRICE)
    units: Mapped[Decimal] = mapped_column(UNITS)
    gross_value_eur_cents: Mapped[int] = mapped_column(Integer)
    fee_eur_cents: Mapped[int] = mapped_column(Integer)
    slippage_eur_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # FILLED, PARTIAL, REJECTED
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    filled_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())


class SignalScore(Base):
    __tablename__ = "signal_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64))  # soft reference to hourly_runs.run_id, not a hard FK: some tables (esp. Order/Position) may legitimately be written before the parent hourly_runs row is finalized within a run
    asset: Mapped[str] = mapped_column(String(32))

    regime_fit: Mapped[int] = mapped_column(Integer)
    residual_strength: Mapped[int] = mapped_column(Integer)
    breakout_quality: Mapped[int] = mapped_column(Integer)
    volume_quality: Mapped[int] = mapped_column(Integer)
    microstructure_liquidity: Mapped[int] = mapped_column(Integer)
    catalyst_credibility: Mapped[int] = mapped_column(Integer)
    onchain_confirmation: Mapped[int] = mapped_column(Integer)
    crowding_quality: Mapped[int] = mapped_column(Integer)
    execution_quality: Mapped[int] = mapped_column(Integer)
    adversarial_confidence: Mapped[int] = mapped_column(Integer)

    overall_score: Mapped[Decimal] = mapped_column(PCT)
    eligible: Mapped[bool] = mapped_column(Boolean)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16))
    interval: Mapped[str] = mapped_column(String(8))  # 1m, 15m, 1h, 4h
    timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[Decimal] = mapped_column(UNITS)
    source: Mapped[str] = mapped_column(String(32), default="bitvavo")


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64))  # soft reference to hourly_runs.run_id, not a hard FK: some tables (esp. Order/Position) may legitimately be written before the parent hourly_runs row is finalized within a run
    timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    cash_value_eur_cents: Mapped[int] = mapped_column(Integer)
    btc_value_eur_cents: Mapped[int] = mapped_column(Integer)
    technical_shadow_value_eur_cents: Mapped[int] = mapped_column(Integer)
    catalyst_shadow_value_eur_cents: Mapped[int] = mapped_column(Integer)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))  # INFO, WARNING, ERROR, CRITICAL
    description: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)


class ConfigFreeze(Base):
    """Records the hash of config/exam_v1.yaml at exam initialization."""

    __tablename__ = "config_freeze"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_version: Mapped[str] = mapped_column(String(32))
    config_hash: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text)
    frozen_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EngineState(Base):
    """Small generic key/value store for cross-run engine state that is not
    itself a per-hour fact — e.g. the BTC-benchmark unit count established
    at exam start (spec section 16.2), or shadow-strategy running balances
    (section 16.3/16.4). Values are stored as text and parsed by the caller
    (Decimal via str, never float) to keep the same no-float discipline as
    the rest of the ledger.
    """

    __tablename__ = "engine_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

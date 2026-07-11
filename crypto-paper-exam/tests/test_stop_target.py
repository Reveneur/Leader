import datetime as dt
from decimal import Decimal

from database.models import Candle, Position
from execution.stop_target_engine import evaluate_intrahour

BASE_TS = dt.datetime(2026, 7, 11, 14, 0, tzinfo=dt.timezone.utc)


def make_position(**overrides) -> Position:
    defaults = dict(
        asset="SOL",
        market="SOL-EUR",
        status="OPEN",
        strategy_version="Exam V1",
        opened_at=BASE_TS,
        entry_price=Decimal("100"),
        entry_units=Decimal("1"),
        gross_spend_eur_cents=10000,
        entry_fee_eur_cents=25,
        entry_slippage_eur_cents=10,
        stop_price=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("120"),
        trailing_rule=None,
        remaining_units=Decimal("1"),
    )
    defaults.update(overrides)
    return Position(**defaults)


def candle(minute: int, o, h, l, c) -> Candle:
    return Candle(
        market="SOL-EUR",
        interval="1m",
        timestamp=BASE_TS + dt.timedelta(minutes=minute),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal("1000"),
        source="bitvavo",
    )


def test_only_stop_hit():
    position = make_position()
    candles = [candle(0, 100, 101, 96, 100), candle(1, 100, 102, 94, 95)]
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "STOP"
    assert result.event.trigger_price == Decimal("95")


def test_only_target_hit():
    position = make_position()
    candles = [candle(0, 100, 105, 99, 104), candle(1, 104, 111, 103, 110)]
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "TARGET_1"


def test_stop_before_target_across_candles():
    position = make_position()
    candles = [
        candle(0, 100, 101, 94, 95),  # stop hit first
        candle(1, 95, 115, 95, 112),  # would have hit target later
    ]
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "STOP"
    assert result.event.candle_timestamp == candles[0].timestamp


def test_target_before_stop_across_candles():
    position = make_position()
    candles = [
        candle(0, 100, 111, 99, 110),  # target hit first
        candle(1, 110, 111, 90, 92),  # would have hit stop later
    ]
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "TARGET_1"
    assert result.event.candle_timestamp == candles[0].timestamp


def test_stop_and_target_same_candle_stop_wins():
    position = make_position()
    candles = [candle(0, 100, 115, 90, 105)]  # touches both stop (95) and target_1 (110)
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "STOP"


def test_neither_hit_returns_no_event():
    position = make_position()
    candles = [candle(0, 100, 105, 97, 103), candle(1, 103, 106, 98, 104)]
    result = evaluate_intrahour(position, candles)
    assert result.event is None
    assert result.mfe_pct > 0


def test_trailing_stop_activates_and_triggers():
    position = make_position(stop_price=Decimal("90"), target_1=Decimal("200"), trailing_rule='{"trail_pct": "2.0"}')
    candles = [
        candle(0, 100, 120, 99, 118),  # peak 120 -> trailing stop = 117.6
        candle(1, 118, 119, 116, 117),  # low 116 breaches trailing stop
    ]
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "TRAILING_STOP"
    assert result.event.trigger_price == Decimal("120") * Decimal("0.98")


def test_gap_through_stop_fills_at_open_not_stop_price():
    position = make_position(stop_price=Decimal("95"))
    candles = [candle(0, 90, 91, 88, 89)]  # opens below stop already
    result = evaluate_intrahour(position, candles)
    assert result.event.kind == "STOP"
    assert result.event.fill_price == Decimal("90")  # worse than stop_price, not favorable

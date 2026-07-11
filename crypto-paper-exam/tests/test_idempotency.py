import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from database.connection import session_scope
from database.repositories import list_hourly_runs
from scheduler import make_run_id, run_hourly

SCHEDULED = dt.datetime(2026, 7, 11, 9, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def _freeze_config(db_settings):
    from audit.config_freeze import freeze_config

    with session_scope(db_settings) as session:
        freeze_config(session, db_settings.strategy_config_path)


@pytest.fixture()
def offline_client():
    """A BitvavoClient stand-in whose HTTP calls always fail, forcing the
    scheduler down its documented degraded-data path (spec section 17)
    instead of hitting the real network in tests.
    """
    client = MagicMock()
    client.get_ticker_book.side_effect = RuntimeError("no network in tests")
    client.get_ticker_24h.side_effect = RuntimeError("no network in tests")
    client.get_candles.side_effect = RuntimeError("no network in tests")
    client.close = MagicMock()
    return client


def test_run_id_is_deterministic_per_scheduled_hour():
    assert make_run_id(SCHEDULED) == "exam-v1-2026-07-11T09:00:00+00:00"
    assert make_run_id(SCHEDULED) == make_run_id(SCHEDULED)


def test_double_run_does_not_duplicate_hourly_row(db_settings, offline_client):
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        first = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)
        second = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    assert first.already_completed is False
    assert second.already_completed is True
    assert first.run.run_id == second.run.run_id

    with session_scope(db_settings) as session:
        runs = list_hourly_runs(session)
    assert len(runs) == 1


def test_double_run_does_not_duplicate_wallet_snapshot(db_settings, offline_client):
    from database.repositories import list_hourly_runs as _lr  # noqa: F401
    from database.models import WalletSnapshot
    from sqlalchemy import select

    with patch("scheduler.fetch_market_snapshot", return_value=None):
        run_hourly(SCHEDULED, settings=db_settings, client=offline_client)
        run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    with session_scope(db_settings) as session:
        snapshots = session.execute(select(WalletSnapshot)).scalars().all()
    assert len(snapshots) == 1


def test_run_with_missing_market_data_settles_on_cash_not_a_crash(db_settings, offline_client):
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        outcome = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    assert outcome.run.action == "CASH"
    assert outcome.run.data_status == "DEGRADED"
    assert outcome.run.completed_at is not None


def test_different_hours_produce_different_run_ids(db_settings, offline_client):
    later = SCHEDULED + dt.timedelta(hours=1)
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        first = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)
        second = run_hourly(later, settings=db_settings, client=offline_client)

    assert first.run.run_id != second.run.run_id
    with session_scope(db_settings) as session:
        runs = list_hourly_runs(session)
    assert len(runs) == 2


def test_config_tamper_forces_cash_and_records_error(db_settings, offline_client):
    text = db_settings.strategy_config_path.read_text()
    tampered = text.replace("max_positions: 2", "max_positions: 5")
    db_settings.strategy_config_path.write_text(tampered)
    try:
        with patch("scheduler.fetch_market_snapshot", return_value=None):
            outcome = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)
        assert outcome.run.action == "CASH"
        assert outcome.run.data_status == "CONFIG_ERROR"
        assert outcome.run.error_message is not None
    finally:
        db_settings.strategy_config_path.write_text(text)

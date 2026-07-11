import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from audit.config_freeze import freeze_config
from audit.integrity import run_integrity_checks
from database.connection import session_scope
from reporting.final_report import compute_final_report
from reporting.hourly_report import render_hourly_report
from scheduler import run_hourly

SCHEDULED = dt.datetime(2026, 7, 11, 9, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def offline_client():
    client = MagicMock()
    client.get_ticker_book.side_effect = RuntimeError("no network in tests")
    client.get_ticker_24h.side_effect = RuntimeError("no network in tests")
    client.get_candles.side_effect = RuntimeError("no network in tests")
    client.close = MagicMock()
    return client


@pytest.fixture(autouse=True)
def _freeze_config(db_settings):
    with session_scope(db_settings) as session:
        freeze_config(session, db_settings.strategy_config_path)


def test_integrity_clean_after_normal_run(db_settings, offline_client):
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    with session_scope(db_settings) as session:
        report = run_integrity_checks(session)
    assert report.is_clean


def test_integrity_flags_missing_hours(db_settings, offline_client):
    from audit.integrity import IntegrityReport, check_no_missing_hours

    # Only run the 09:00 hour; 08:00 and 10:00 are left missing.
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    report = IntegrityReport()
    with session_scope(db_settings) as session:
        check_no_missing_hours(
            session,
            SCHEDULED - dt.timedelta(hours=1),
            SCHEDULED + dt.timedelta(hours=1),
            report,
        )

    assert any(f.check == "no_missing_hours" for f in report.findings)


def test_final_report_reconstructs_from_persisted_data(db_settings, offline_client):
    from decimal import Decimal

    with patch("scheduler.fetch_market_snapshot", return_value=None):
        run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    with session_scope(db_settings) as session:
        report = compute_final_report(session, Decimal("100.00"))

    assert report.begin_value_eur == Decimal("100.00")
    assert report.end_value_eur == Decimal("100.00")
    assert report.trade_count == 0
    assert report.grade in ("A", "B", "C", "D", "F")


def test_hourly_report_renders_readable_text(db_settings, offline_client):
    with patch("scheduler.fetch_market_snapshot", return_value=None):
        outcome = run_hourly(SCHEDULED, settings=db_settings, client=offline_client)

    text = render_hourly_report(outcome.run)
    assert "CASH" in text
    assert outcome.run.run_id in text

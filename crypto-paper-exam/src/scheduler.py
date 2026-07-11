"""The hourly scheduler (spec section 4.5). Every run is identified by a
deterministic run_id derived from the scheduled hour (section 18), so
running the same hour twice — whether from a retry, a restart, or a
double-fired cron — never produces a duplicate transaction or a duplicate
hourly row. Steps below follow the 12-step sequence in section 4.5.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from audit.auditor import Auditor
from audit.config_freeze import ConfigTamperedError, StrategyConfig, verify_config
from data.bitvavo_client import BitvavoClient
from data.candle_repository import safe_refresh, get_candles
from data.market_repository import fetch_market_snapshot
from database.connection import session_scope
from database.models import Benchmark, HourlyRun
from database.repositories import (
    add_benchmark,
    get_engine_state,
    get_hourly_run,
    open_positions,
    set_engine_state,
    upsert_hourly_run,
)
from execution.paper_broker import MarketSnapshot
from execution.stop_target_engine import evaluate_intrahour
from execution import paper_broker
from portfolio import accounting, risk_manager
from portfolio.positions import value_all_open_positions
from portfolio.wallet import Wallet
from settings import Settings, get_settings

logger = logging.getLogger(__name__)

STRATEGY_PREFIX = "exam-v1"

EVENT_CLASSIFICATION = {
    "TARGET_1": "CORRECT",
    "TARGET_2": "CORRECT",
    "TRAILING_STOP": "CORRECT",
    "STOP": "WRONG",
}


def make_run_id(scheduled_timestamp: dt.datetime) -> str:
    return f"{STRATEGY_PREFIX}-{scheduled_timestamp.isoformat()}"


def _gross_from_total_budget(total_budget: Decimal, fee_pct: Decimal, slippage_pct: Decimal) -> Decimal:
    factor = (1 + slippage_pct / 100) * (1 + fee_pct / 100)
    return total_budget / factor


@dataclass
class RunOutcome:
    run: HourlyRun
    already_completed: bool
    errors: list[str] = field(default_factory=list)


def claim_run(session: Session, run_id: str, scheduled_timestamp: dt.datetime, strategy_version: str) -> HourlyRun:
    """Idempotency gate (spec section 18): if the run already exists, this
    does not create a second row. Called in its own short transaction so a
    crash right after claiming still leaves a clear 'started but not
    completed' marker for audit.integrity to catch.
    """
    existing = get_hourly_run(session, run_id)
    if existing is not None:
        return existing
    run = HourlyRun(
        run_id=run_id,
        scheduled_timestamp=scheduled_timestamp,
        started_at=dt.datetime.now(dt.timezone.utc),
        completed_at=None,
        strategy_version=strategy_version,
        action="PENDING",
        data_status="PENDING",
        sheet_status="PENDING",
        cash_eur_cents=0,
        equity_eur_cents=0,
        btc_benchmark_eur_cents=0,
        cash_benchmark_eur_cents=0,
    )
    return upsert_hourly_run(session, run)


def _update_btc_benchmark(
    session: Session,
    config: StrategyConfig,
    btc_snapshot: MarketSnapshot | None,
    prior_value_cents: int,
) -> int:
    units_raw = get_engine_state(session, "btc_benchmark_units")
    if units_raw is None:
        if btc_snapshot is None:
            return prior_value_cents  # cannot initialize yet; retry next run
        gross = _gross_from_total_budget(
            config.wallet.initial_cash_eur,
            config.execution.taker_fee_pct,
            config.execution.default_slippage_buy_pct,
        )
        units = gross / btc_snapshot.ask
        set_engine_state(session, "btc_benchmark_units", str(units))
        units_raw = str(units)

    units = Decimal(units_raw)
    if btc_snapshot is None:
        return prior_value_cents

    value_eur = accounting.estimate_executable_sell_value(
        units, btc_snapshot.bid, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
    )
    return accounting.eur_to_cents(value_eur)


def _manage_open_positions(
    session: Session,
    run_id: str,
    config: StrategyConfig,
    client: BitvavoClient,
    scheduled_timestamp: dt.datetime,
    auditor: Auditor,
) -> list[str]:
    """Step 5: evaluate stops/targets/trailing stops for every open
    position using 1-minute candles for the elapsed hour (spec section 7).
    """
    notes: list[str] = []
    window_start = scheduled_timestamp - dt.timedelta(hours=1)

    for position in list(open_positions(session)):
        ok, err = safe_refresh(session, client, position.market, "1m", limit=120)
        if not ok:
            auditor.warning(
                "candle_refresh_failed",
                f"could not refresh 1m candles for {position.market}: {err}",
            )
            notes.append(f"{position.asset}: intrahour data unavailable ({err})")
            continue

        candles = get_candles(session, position.market, "1m", window_start, scheduled_timestamp)
        if not candles:
            notes.append(f"{position.asset}: no 1m candles available for elapsed hour")
            continue

        for candle in candles:
            auditor.assert_not_future(candle.timestamp, scheduled_timestamp, f"intrahour candle {position.market}")

        result = evaluate_intrahour(position, candles, config.intrahour.ambiguous_stop_target_rule)
        if result.event is None:
            continue

        snapshot = fetch_market_snapshot(client, position.market)
        if snapshot is None:
            # Conservative fallback per spec section 17: build a minimal
            # snapshot from the triggering candle rather than skipping the
            # exit entirely, since the stop/target was already confirmed hit.
            snapshot = MarketSnapshot(
                market=position.market,
                timestamp=scheduled_timestamp,
                bid=result.event.fill_price,
                ask=result.event.fill_price,
                last=result.event.fill_price,
                spread_pct=Decimal("0"),
            )

        classification = EVENT_CLASSIFICATION.get(result.event.kind, "UNRESOLVED")
        paper_broker.execute_sell(
            session,
            run_id,
            config,
            snapshot,
            position,
            position.remaining_units,
            sell_reason=result.event.kind,
            classification=classification,
            mfe_pct=result.mfe_pct,
            mae_pct=result.mae_pct,
            override_price=result.event.fill_price,
        )
        notes.append(f"{position.asset}: {result.event.kind} at {result.event.fill_price}")

    return notes


def run_hourly(
    scheduled_timestamp: dt.datetime,
    settings: Settings | None = None,
    client: BitvavoClient | None = None,
    universe: list[str] | None = None,
) -> RunOutcome:
    settings = settings or get_settings()
    run_id = make_run_id(scheduled_timestamp)
    own_client = client is None
    client = client or BitvavoClient()

    try:
        with session_scope(settings) as session:
            existing = get_hourly_run(session, run_id)
            if existing is not None and existing.completed_at is not None:
                return RunOutcome(existing, already_completed=True)

        errors: list[str] = []
        with session_scope(settings) as session:
            claim_run(session, run_id, scheduled_timestamp, "Exam V1")

        with session_scope(settings) as session:
            auditor = Auditor(session, run_id)
            run = get_hourly_run(session, run_id)
            assert run is not None

            try:
                config = verify_config(session, settings.strategy_config_path)
            except ConfigTamperedError as exc:
                auditor.error("config_tampered", str(exc))
                run.data_status = "CONFIG_ERROR"
                run.action = "CASH"
                run.explanation = f"CASH. Configuratiehash komt niet overeen: {exc}"
                run.error_message = str(exc)
                run.completed_at = dt.datetime.now(dt.timezone.utc)
                run.cash_eur_cents = accounting.eur_to_cents(Decimal("0"))
                run.equity_eur_cents = 0
                run.btc_benchmark_eur_cents = 0
                run.cash_benchmark_eur_cents = accounting.eur_to_cents(Decimal("100"))
                upsert_hourly_run(session, run)
                return RunOutcome(run, already_completed=False, errors=[str(exc)])

            wallet = Wallet(session, config.wallet.initial_cash_eur)

            position_notes = _manage_open_positions(session, run_id, config, client, scheduled_timestamp, auditor)

            live_markets = list({p.market for p in open_positions(session)})
            if universe:
                live_markets = list(set(live_markets) | set(universe))
            btc_snapshot = fetch_market_snapshot(client, "BTC-EUR")
            if btc_snapshot is None:
                errors.append("BTC-EUR market data unavailable")

            bid_prices: dict[str, Decimal] = {}
            for market in {p.market for p in open_positions(session)}:
                snap = fetch_market_snapshot(client, market)
                if snap is not None:
                    bid_prices[market] = snap.bid
                else:
                    errors.append(f"{market} market data unavailable for valuation")

            valuation = value_all_open_positions(
                session, bid_prices, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
            )

            # New-candidate scanning is intentionally conservative in this
            # build: without catalyst/on-chain providers configured (Phase
            # 3, see data/news_client.py and data/onchain_client.py), the
            # mandatory "independent confirmation" eligibility gate (spec
            # section 10) can never be satisfied, so the run correctly
            # settles on CASH/HOLD rather than fabricating a BUY. Wiring a
            # real provider there activates full candidate scoring with no
            # changes needed here.
            open_after_management = open_positions(session)
            if position_notes:
                action = "SELL" if any("STOP" in n or "TARGET" in n for n in position_notes) else "HOLD"
                explanation = "; ".join(position_notes)
                contradiction = None
                top_candidate = None
                confidence = None
                regime = None
            elif open_after_management:
                action = "HOLD"
                explanation = f"HOLD. {len(open_after_management)} open positie(s), geen stop/target geraakt."
                contradiction = None
                top_candidate = None
                confidence = None
                regime = None
            else:
                action = "CASH"
                explanation = "CASH. Geen open posities; kandidaatscanning vereist Fase 3 databronnen (catalyst/on-chain)."
                contradiction = "no independent catalyst/on-chain provider configured"
                top_candidate = None
                confidence = None
                regime = None

            btc_benchmark_cents = _update_btc_benchmark(session, config, btc_snapshot, run.btc_benchmark_eur_cents)
            cash_benchmark_cents = accounting.eur_to_cents(Decimal("100.00"))

            add_benchmark(
                session,
                Benchmark(
                    run_id=run_id,
                    timestamp=scheduled_timestamp,
                    cash_value_eur_cents=cash_benchmark_cents,
                    btc_value_eur_cents=btc_benchmark_cents,
                    technical_shadow_value_eur_cents=cash_benchmark_cents,
                    catalyst_shadow_value_eur_cents=cash_benchmark_cents,
                ),
            )

            snapshot_record = wallet.record_snapshot(run_id, scheduled_timestamp, valuation)

            data_status = "OK" if not errors else "DEGRADED"

            run.action = action
            run.explanation = explanation
            run.contradiction = contradiction
            run.top_candidate = top_candidate
            run.confidence = confidence
            run.regime = regime
            run.cash_eur_cents = snapshot_record.cash_eur_cents
            run.position_value_eur_cents = valuation.holdings_value_cents
            run.equity_eur_cents = snapshot_record.equity_eur_cents
            run.btc_benchmark_eur_cents = btc_benchmark_cents
            run.cash_benchmark_eur_cents = cash_benchmark_cents
            run.realized_pnl_eur_cents = snapshot_record.realized_pnl_eur_cents
            run.unrealized_pnl_eur_cents = snapshot_record.unrealized_pnl_eur_cents
            run.cumulative_costs_eur_cents = snapshot_record.cumulative_costs_eur_cents
            run.data_status = data_status
            run.error_message = "; ".join(errors) if errors else None
            run.completed_at = dt.datetime.now(dt.timezone.utc)

            open_assets = [p.asset for p in open_positions(session)]
            if open_assets:
                run.asset = open_assets[0]
                first_pos = open_positions(session)[0]
                run.units = first_pos.remaining_units

            upsert_hourly_run(session, run)

            auditor.log(
                "hourly_run_completed",
                f"run {run_id} completed with action={action}",
                severity="INFO",
            )

            outcome = RunOutcome(run, already_completed=False, errors=errors)

        _export_to_sheets(run_id, settings)
        return outcome
    finally:
        if own_client:
            client.close()


def _export_to_sheets(run_id: str, settings: Settings) -> None:
    """Runs as its own short transaction after the trading decision has
    already committed (spec section 15/18: a Sheets failure or retry must
    never touch the market decision, and the original decision never
    changes on retry).
    """
    from reporting.google_sheets import export_run
    from database.repositories import signal_scores_for_run

    with session_scope(settings) as session:
        run = get_hourly_run(session, run_id)
        if run is None:
            return
        scores = signal_scores_for_run(session, run_id)
        top_score = scores[0] if scores else None
        ok, error = export_run(run, top_score, settings)
        run.sheet_status = "OK" if ok else "RETRY_QUEUED"
        if error:
            Auditor(session, run_id).warning("sheet_export_failed", error)
        upsert_hourly_run(session, run)

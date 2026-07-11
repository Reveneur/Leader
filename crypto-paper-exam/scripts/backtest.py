#!/usr/bin/env python3
"""Technical-only backtest against real historical BTC/USD data.

THIS IS NOT EXAM V1. It reuses Exam V1's accounting, execution, and risk
engine exactly as-is (same fee/slippage model, same wallet ledger, same
stop/target reconstruction, same position-sizing and drawdown rules), but
differs from the live engine in ways that matter and are called out
explicitly rather than glossed over:

  - Single asset (BTC/USD). residual_strength normally compares an asset's
    return against BTC/ETH; with only one asset there is nothing to compare
    against, so it is fixed at a neutral pass-through value (7/10) instead
    of being computed or faked as "measured."
  - No order-book data. Historical OHLCV has no bid/ask/depth, so spread
    and liquidity are fixed, documented assumptions for a highly liquid
    BTC/USD pair (0.05% spread, a flat liquidity score) — not measurements.
  - No catalyst or on-chain data. Those two components are excluded from
    this mode's eligibility rule entirely rather than defaulted to zero
    and silently dragging the score down, or defaulted to a passing value
    and silently faking confirmation that doesn't exist.
  - Its own eligibility rule (`technical_eligibility` below): technical
    scores only, net reward:risk >= 2:1. This is deliberately NOT Exam
    V1's real 10-component/75-point gate (strategy.scoring), which
    requires independent catalyst/on-chain confirmation this mode cannot
    supply. Passing this rule proves nothing about Exam V1 eligibility.

Data source: ff137/bitstamp-btcusd-minute-data on GitHub — real Bitstamp
BTC/USD 1-minute trade-derived OHLCV, updated daily. See
src/data/historical_dataset.py.

What a green run here proves: that this specific set of technical rules,
mechanically applied with realistic costs, would have made or lost money
over this specific historical window. It does NOT prove general edge —
see the "what can you prove" discussion this script's caller had before
building it: no out-of-sample validation, no statistical significance
testing, and thresholds here were hand-picked, not fitted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from audit.config_freeze import StrategyConfig, load_strategy_config  # noqa: E402
from data.historical_dataset import HistoricalCandle, fetch_btc_usd_1m, load_1m_candles, resample  # noqa: E402
from database.connection import init_db, session_scope  # noqa: E402
from database.models import Candle, HourlyRun  # noqa: E402
from database.repositories import closed_positions, open_positions, peak_equity_cents, upsert_hourly_run  # noqa: E402
from execution.paper_broker import (  # noqa: E402
    InsufficientCashError,
    MarketSnapshot,
    PositionPlan,
    execute_buy,
    execute_sell,
)
from execution.stop_target_engine import evaluate_intrahour  # noqa: E402
from portfolio import accounting, risk_manager  # noqa: E402
from portfolio.positions import value_all_open_positions  # noqa: E402
from portfolio.wallet import Wallet  # noqa: E402
from reporting.final_report import compute_final_report, render_final_report  # noqa: E402
from settings import REPO_ROOT, Settings  # noqa: E402
from strategy import breakout as breakout_mod  # noqa: E402
from strategy import regime as regime_mod  # noqa: E402
from strategy import scoring as scoring_mod  # noqa: E402
from strategy.adversarial import RiskFlags, adversarial_review  # noqa: E402

MARKET = "BTC-USD"
ASSET = "BTC"
STRATEGY_VERSION = "Technical-Only Backtest v1"
ASSUMED_SPREAD_PCT = Decimal("0.05")  # documented assumption, not measured — see module docstring
MICROSTRUCTURE_SCORE = 8  # documented assumption, not measured — see module docstring
RESIDUAL_STRENGTH_NEUTRAL = 7  # not computable single-asset — see module docstring

WARMUP_HOURS = 100
LOOKBACK = 20
RESISTANCE_LOOKBACK = 48


def make_run_id(ts: dt.datetime) -> str:
    return f"backtest-btc-{ts.isoformat()}"


def technical_eligibility(
    scores: scoring_mod.ComponentScores,
    net_rr: Decimal,
    config: StrategyConfig,
    breakout_min: int | None = None,
) -> tuple[bool, list[str]]:
    """A deliberately separate rule from Exam V1's real eligibility gate
    (strategy.scoring.evaluate_eligibility) — see module docstring.

    breakout_min overrides config.eligibility.breakout_min when given. This
    exists because, on real 13-month BTC/USD hourly data, the spec-faithful
    threshold of 7 produces *zero* qualifying setups: breakout.py's
    "retested" bonus path structurally tops out at 6 once its distance term
    is capped by the narrow (<=1%) retest band (0.99 distance + 3 volume +
    3 retest = 6.99, truncated to 6 by int()), and the non-retested path
    needs a raw single-hour move of >=4% above a 48h high with >=2x volume,
    which never once occurred in this window. That's a real, reportable
    finding on its own — see the two runs this script's README section
    describes (threshold=7: 0 trades; threshold=6: below).
    """
    reasons = []
    effective_breakout_min = breakout_min if breakout_min is not None else config.eligibility.breakout_min
    if scores.regime_fit < config.eligibility.regime_fit_min:
        reasons.append(f"regime_fit {scores.regime_fit}")
    if scores.breakout_quality < effective_breakout_min:
        reasons.append(f"breakout_quality {scores.breakout_quality}")
    if scores.volume_quality < config.eligibility.volume_min:
        reasons.append(f"volume_quality {scores.volume_quality}")
    if scores.microstructure_liquidity < config.eligibility.liquidity_execution_min:
        reasons.append("microstructure_liquidity")
    if scores.execution_quality < config.eligibility.liquidity_execution_min:
        reasons.append(f"execution_quality {scores.execution_quality}")
    if scores.adversarial_confidence < config.eligibility.adversarial_min:
        reasons.append(f"adversarial_confidence {scores.adversarial_confidence}")
    if net_rr < config.eligibility.net_reward_risk_min:
        reasons.append(f"net_reward_risk {net_rr:.2f}")
    return (not reasons), reasons


def net_pct_estimates(
    entry: Decimal, stop: Decimal, target: Decimal, config: StrategyConfig
) -> tuple[Decimal, Decimal, Decimal]:
    """Percentage-based net reward/risk, reusing the exact same cost
    formulas real trades use (portfolio.accounting), so this estimate
    matches what the ledger will actually do — not an approximation with
    its own drift.
    """
    notional = Decimal("100")
    total_cost, _, _ = accounting.apply_buy_costs(
        notional, config.execution.taker_fee_pct, config.execution.default_slippage_buy_pct
    )

    gross_at_target = notional * (target / entry)
    net_at_target, _, _ = accounting.apply_sell_costs(
        gross_at_target, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
    )
    net_reward_pct = (net_at_target - total_cost) / total_cost * 100

    gross_at_stop = notional * (stop / entry)
    net_at_stop, _, _ = accounting.apply_sell_costs(
        gross_at_stop, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
    )
    net_risk_pct = (total_cost - net_at_stop) / total_cost * 100

    net_rr = net_reward_pct / net_risk_pct if net_risk_pct > 0 else Decimal("0")
    return net_reward_pct, net_risk_pct, net_rr


def gross_from_total_budget(total_budget: Decimal, fee_pct: Decimal, slippage_pct: Decimal) -> Decimal:
    """Mirrors scheduler.py's BTC-benchmark init: how much can be spent
    gross so that gross+slippage+fee equals the full budget.
    """
    factor = (1 + slippage_pct / 100) * (1 + fee_pct / 100)
    return total_budget / factor


def run_backtest(
    settings: Settings,
    csv_path: Path,
    start: dt.datetime | None,
    end: dt.datetime | None,
    breakout_min: int | None = None,
) -> None:
    if breakout_min is not None:
        print(
            f"NOTE: using a relaxed breakout_quality threshold of {breakout_min} "
            f"(spec default is 7). This is a labeled demo variant, not Exam V1's real gate."
        )
    config = load_strategy_config(settings.strategy_config_path)
    init_db(settings)

    print(f"Loading 1-minute BTC/USD candles from {csv_path} ...")
    candles_1m = load_1m_candles(csv_path, start=start, end=end)
    print(f"Loaded {len(candles_1m)} 1-minute candles: {candles_1m[0].timestamp} .. {candles_1m[-1].timestamp}")

    candles_1h = resample(candles_1m, 60)
    candles_15m = resample(candles_1m, 15)
    candles_4h = resample(candles_1m, 240)
    print(f"Resampled to {len(candles_1h)} hourly candles.")

    if len(candles_1h) < WARMUP_HOURS + 10:
        print("Not enough data for a meaningful backtest after warmup. Widen --start/--end.")
        return

    closes_1h = [c.close for c in candles_1h]
    highs_1h = [c.high for c in candles_1h]
    volumes_1h = [c.volume for c in candles_1h]
    closes_15m = [(c.timestamp, c.close) for c in candles_15m]
    closes_4h = [(c.timestamp, c.close) for c in candles_4h]

    by_hour: dict[dt.datetime, list[HistoricalCandle]] = defaultdict(list)
    for c in candles_1m:
        by_hour[c.timestamp.replace(minute=0, second=0, microsecond=0)].append(c)

    btc_units: Decimal | None = None
    trades_opened = 0

    with session_scope(settings) as session:
        wallet = Wallet(session, config.wallet.initial_cash_eur)

        for i in range(WARMUP_HOURS, len(candles_1h) - 1):
            last_closed = candles_1h[i]
            fill_candle = candles_1h[i + 1]
            now_ts = fill_candle.timestamp

            if btc_units is None:
                gross = gross_from_total_budget(
                    config.wallet.initial_cash_eur,
                    config.execution.taker_fee_pct,
                    config.execution.default_slippage_buy_pct,
                )
                btc_units = gross / last_closed.close

            action = "HOLD"
            explanation = ""

            # --- 1. manage any open position using the hour that just closed ---
            for position in open_positions(session):
                if position.market != MARKET:
                    continue
                elapsed_1m = by_hour.get(last_closed.timestamp, [])
                if not elapsed_1m:
                    continue
                candle_objs = [
                    Candle(
                        market=MARKET, interval="1m", timestamp=c.timestamp, open=c.open,
                        high=c.high, low=c.low, close=c.close, volume=c.volume, source="bitstamp-backtest",
                    )
                    for c in elapsed_1m
                ]
                result = evaluate_intrahour(position, candle_objs, config.intrahour.ambiguous_stop_target_rule)
                if result.event is not None:
                    exit_price = result.event.fill_price
                    snapshot = MarketSnapshot(
                        market=MARKET, timestamp=now_ts, bid=exit_price, ask=exit_price,
                        last=exit_price, spread_pct=ASSUMED_SPREAD_PCT,
                    )
                    classification = "CORRECT" if result.event.kind in ("TARGET_1", "TARGET_2", "TRAILING_STOP") else "WRONG"
                    execute_sell(
                        session, make_run_id(now_ts), config, snapshot, position, position.remaining_units,
                        sell_reason=result.event.kind, classification=classification,
                        mfe_pct=result.mfe_pct, mae_pct=result.mae_pct, override_price=exit_price,
                    )
                    action = "SELL"
                    explanation = f"{result.event.kind} at {exit_price:.2f}"

            # --- 2. scan for a new entry if flat ---
            has_open = any(p.market == MARKET for p in open_positions(session))
            if not has_open and action != "SELL":
                series_15m = [c for ts, c in closes_15m if ts <= last_closed.timestamp][-LOOKBACK:]
                series_1h = closes_1h[max(0, i - LOOKBACK + 1) : i + 1]
                series_4h = [c for ts, c in closes_4h if ts <= last_closed.timestamp][-LOOKBACK:]

                if len(series_15m) < LOOKBACK or len(series_1h) < LOOKBACK or len(series_4h) < LOOKBACK:
                    action, explanation = "CASH", "insufficient warmup history"
                else:
                    regime = regime_mod.classify_market_regime(series_15m, series_1h, series_4h)
                    momentum_up = series_1h[-1] > series_1h[-5]
                    regime_fit = regime_mod.regime_fit_score(regime, asset_shows_relative_strength=momentum_up)

                    # Resistance must come from candles strictly BEFORE the one
                    # being evaluated — including last_closed's own high here
                    # would make close <= resistance almost by definition and
                    # breakout_quality_score would always return 0.
                    resistance_window = highs_1h[max(0, i - RESISTANCE_LOOKBACK) : i]
                    resistance = max(resistance_window) if resistance_window else last_closed.close
                    avg_volume = sum(volumes_1h[max(0, i - LOOKBACK) : i]) / LOOKBACK
                    current_volume = last_closed.volume
                    retested = last_closed.close <= resistance * Decimal("1.01")
                    extended_pct = max(Decimal("0"), (last_closed.close - resistance) / resistance * 100) if resistance > 0 else Decimal("0")

                    breakout_quality = breakout_mod.breakout_quality_score(
                        breakout_mod.BreakoutContext(
                            close=last_closed.close, resistance=resistance, avg_volume=avg_volume,
                            current_volume=current_volume, retested=retested, already_extended_pct=extended_pct,
                        )
                    )
                    volume_quality = scoring_mod.volume_quality_score(current_volume, avg_volume)

                    volatility_pct = regime_mod.realized_volatility_pct(series_1h)
                    stop_distance_pct = min(Decimal("8"), max(Decimal("1.5"), volatility_pct * 2))
                    entry_price = fill_candle.open
                    stop_price = entry_price * (1 - stop_distance_pct / 100)
                    # Gross reward:risk is set well above 2:1 on purpose: the
                    # ~0.7% round-trip cost (taker fee + slippage both ways)
                    # is a near-fixed overhead that erodes a tight 2:1 gross
                    # setup down to roughly 1:1 net (verified empirically
                    # against this dataset) — a 4:1 gross target is what it
                    # actually takes to clear the net_reward_risk_min=2.0
                    # gate after realistic costs, not an arbitrary choice.
                    target_1 = entry_price * (1 + 4 * stop_distance_pct / 100)

                    net_reward_pct, net_risk_pct, net_rr = net_pct_estimates(entry_price, stop_price, target_1, config)
                    execution_quality = scoring_mod.execution_quality_score(
                        ASSUMED_SPREAD_PCT, config.liquidity.max_spread_pct,
                        config.execution.default_slippage_buy_pct + config.execution.default_slippage_sell_pct,
                        2 * stop_distance_pct,
                    )

                    flags = RiskFlags(poor_reward_to_risk=net_rr < config.eligibility.net_reward_risk_min)
                    adversarial = adversarial_review(flags, net_rr, config.eligibility.net_reward_risk_min)

                    scores = scoring_mod.ComponentScores(
                        regime_fit=regime_fit,
                        residual_strength=RESIDUAL_STRENGTH_NEUTRAL,
                        breakout_quality=breakout_quality,
                        volume_quality=volume_quality,
                        microstructure_liquidity=MICROSTRUCTURE_SCORE,
                        catalyst_credibility=0,
                        onchain_confirmation=0,
                        crowding_quality=6,
                        execution_quality=execution_quality,
                        adversarial_confidence=adversarial.score,
                    )
                    eligible, reasons = technical_eligibility(scores, net_rr, config, breakout_min=breakout_min)

                    if eligible and not adversarial.veto:
                        peak = peak_equity_cents(session)
                        equity_cents = wallet.cash_cents()
                        drawdown_pct = accounting.compute_drawdown_pct(equity_cents, max(peak, equity_cents))
                        equity_eur = accounting.cents_to_eur(equity_cents)

                        since = now_ts - dt.timedelta(hours=config.loss_pause.window_hours)
                        loss_timestamps = [
                            p.closed_at for p in closed_positions(session, since=since)
                            if p.realized_pnl_eur_cents is not None and p.realized_pnl_eur_cents < 0
                        ]

                        decision, size_eur, max_risk_eur = risk_manager.evaluate_new_position(
                            equity_eur=equity_eur, drawdown_pct=drawdown_pct, open_positions_count=0,
                            candidate_asset=ASSET, open_assets=[], correlations={}, loss_timestamps=loss_timestamps,
                            now=now_ts, overall_score=Decimal(sum(scores.as_dict().values())), net_reward_risk=net_rr,
                            entry_price=entry_price, stop_price=stop_price, config=config.portfolio,
                            loss_pause_losses=config.loss_pause.losses,
                            loss_pause_window_hours=config.loss_pause.window_hours,
                            loss_pause_pause_hours=config.loss_pause.pause_hours,
                        )
                        if decision.allowed and size_eur > 0:
                            plan = PositionPlan(
                                asset=ASSET, strategy_version=STRATEGY_VERSION, stop_price=stop_price,
                                target_1=target_1, target_2=None, trailing_rule=None, regime_at_entry=regime,
                                scores=scores.as_dict(), contradictions=reasons,
                                missing_data=["catalyst", "onchain", "orderbook_depth"], catalyst=None,
                                onchain_confirmation=None,
                                thesis=f"Technical breakout above {resistance:.2f} in {regime} regime, volume {current_volume:.2f} vs avg {avg_volume:.2f}.",
                                expected_hold_period="hours",
                                max_eur_risk_cents=accounting.eur_to_cents(max_risk_eur),
                                expected_gross_profit_eur_cents=accounting.eur_to_cents(size_eur * (target_1 - entry_price) / entry_price),
                                expected_net_profit_eur_cents=accounting.eur_to_cents(size_eur * net_reward_pct / 100),
                                net_reward_risk=net_rr, confidence=Decimal(sum(scores.as_dict().values())),
                                invalidation_criterion=f"close back below {stop_price:.2f}",
                                sources=["bitstamp-backtest (ff137/bitstamp-btcusd-minute-data)"],
                            )
                            snapshot = MarketSnapshot(
                                market=MARKET, timestamp=now_ts, bid=entry_price, ask=entry_price,
                                last=entry_price, spread_pct=ASSUMED_SPREAD_PCT,
                            )
                            try:
                                execute_buy(session, make_run_id(now_ts), config, snapshot, size_eur, equity_eur, plan)
                                action, explanation = "BUY", plan.thesis
                                trades_opened += 1
                            except InsufficientCashError as exc:
                                action, explanation = "CASH", f"insufficient cash: {exc}"
                        else:
                            action = "CASH"
                            explanation = decision.reason or "risk gate declined"
                    else:
                        action = "CASH"
                        explanation = f"technical gate failed: {', '.join(reasons)}" if reasons else "adversarial veto"
            elif has_open and action != "SELL":
                action, explanation = "HOLD", "open position unchanged"

            # --- 3. wallet snapshot + hourly row (no silent hours, matches live engine) ---
            valuation = value_all_open_positions(
                session, {MARKET: last_closed.close}, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
            )
            snapshot_row = wallet.record_snapshot(make_run_id(now_ts), now_ts, valuation)
            btc_bench_value = accounting.estimate_executable_sell_value(
                btc_units, last_closed.close, config.execution.taker_fee_pct, config.execution.default_slippage_sell_pct
            )

            run = HourlyRun(
                run_id=make_run_id(now_ts), scheduled_timestamp=now_ts, started_at=now_ts, completed_at=now_ts,
                strategy_version=STRATEGY_VERSION, action=action, explanation=explanation, regime=None,
                data_status="OK", sheet_status="N/A", cash_eur_cents=snapshot_row.cash_eur_cents,
                asset=ASSET if action in ("BUY", "HOLD") else None,
                position_value_eur_cents=valuation.holdings_value_cents, equity_eur_cents=snapshot_row.equity_eur_cents,
                btc_benchmark_eur_cents=accounting.eur_to_cents(btc_bench_value),
                cash_benchmark_eur_cents=accounting.eur_to_cents(Decimal("100.00")),
                realized_pnl_eur_cents=snapshot_row.realized_pnl_eur_cents,
                unrealized_pnl_eur_cents=snapshot_row.unrealized_pnl_eur_cents,
                cumulative_costs_eur_cents=snapshot_row.cumulative_costs_eur_cents,
            )
            upsert_hourly_run(session, run)

            if (i - WARMUP_HOURS) % 2000 == 0:
                print(f"  {now_ts.date()}  equity=EUR{snapshot_row.equity_eur_cents/100:.2f}  btc_bench=EUR{accounting.eur_to_cents(btc_bench_value)/100:.2f}  trades={trades_opened}")

        print(f"\nBacktest loop complete. {trades_opened} position(s) opened.")
        report = compute_final_report(session, config.wallet.initial_cash_eur)

    print("\n" + render_final_report(report))
    print(
        "NOTE: technical_shadow/catalyst_shadow figures above are not meaningful here — "
        "this backtest IS the technical-only strategy, it does not run one as a shadow "
        "against something else. Ignore those two lines."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=str, default=str(REPO_ROOT / "data" / "backtest_btc.sqlite"), help="Backtest SQLite path (separate from the live exam DB).")
    parser.add_argument("--cache", type=str, default=str(REPO_ROOT / "data" / "backtest_cache" / "btcusd_bitstamp_1min_latest.csv"), help="Local cache path for the downloaded dataset.")
    parser.add_argument("--refresh-data", action="store_true", help="Re-download the dataset even if a cached copy exists.")
    parser.add_argument("--start", type=str, default=None, help="ISO start timestamp (default: earliest available).")
    parser.add_argument("--end", type=str, default=None, help="ISO end timestamp (default: latest available).")
    parser.add_argument("--days", type=int, default=None, help="Shortcut: only use the most recent N days of data.")
    parser.add_argument(
        "--breakout-min",
        type=int,
        default=None,
        help="Override the breakout_quality eligibility threshold (spec default: 7). "
        "See technical_eligibility()'s docstring for why the default produces zero trades on this dataset.",
    )
    args = parser.parse_args()

    settings = Settings(database_path=Path(args.db))

    cache_path = Path(args.cache)
    csv_path = fetch_btc_usd_1m(cache_path, force_refresh=args.refresh_data)

    start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc) if args.start else None
    end = dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc) if args.end else None
    if args.days is not None:
        end = end or dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(days=args.days)

    if Path(args.db).exists():
        print(f"NOTE: {args.db} already exists; re-running will hit idempotency guards on repeated run_ids. "
              f"Delete it first for a clean re-run.")

    run_backtest(settings, csv_path, start, end, breakout_min=args.breakout_min)


if __name__ == "__main__":
    main()

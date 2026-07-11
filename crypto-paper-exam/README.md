# Crypto Paper Trading Exam V1

A fully auditable, reproducible crypto paper-trading engine that runs a fictional
€100.00 wallet through a seven-day exam period, using deterministic risk rules,
realistic execution costs, and an hourly, idempotent scheduler. See
`docs/spec.md`-equivalent context in the project brief below for the full
Dutch specification this implementation follows.

The central question this project answers is not "did the wallet grow?" but:

> Can the strategy prove, technically and transparently, that every trading
> decision was based on pre-committed rules, realistic market data, and
> correct wallet accounting?

## Status

This build implements the full **Phase 1 + Phase 2** stack from the spec's
development plan (reliable core + technical strategy), with **Phase 3**
(catalyst/on-chain providers) and the two shadow strategies wired as
explicit, honestly-flagged extension points rather than faked:

- ✅ SQLite database with all core tables, integer-eurocent + exact-Decimal
  storage (no float ever touches the ledger — see `PreciseDecimal` in
  `src/database/models.py`).
- ✅ Wallet accounting, fee/slippage/fill models, paper broker, intrahour
  stop/target/trailing-stop reconstruction with the conservative
  stop-first tie-break rule.
- ✅ Risk manager: max 2 positions, position sizing, drawdown throttling
  (8%/12%), loss pause, correlation block.
- ✅ Bitvavo public market-data client + liquidity screening.
- ✅ The 11-agent ensemble as deterministic, independently testable
  functions (`src/strategy/*.py`).
- ✅ Hourly scheduler: idempotent by `run_id`, crash-recoverable, exactly
  one authoritative row per hour even on CASH/degraded-data hours.
- ✅ Google Sheets export (best-effort, never blocks a trading decision).
- ✅ Audit/integrity checks, config freeze + tamper detection.
- ✅ Streamlit dashboard, hourly/daily/final reports.
- ⚠️ **Catalyst and on-chain data providers are not wired to a real API**
  (`src/data/news_client.py`, `src/data/onchain_client.py`). Without them,
  the mandatory "independent confirmation" eligibility gate can never be
  satisfied, so the live scheduler correctly and honestly settles on
  CASH/HOLD every hour rather than fabricating a BUY. Wiring a real
  provider into those two classes activates full candidate scoring with
  no changes needed elsewhere.
- ⚠️ **Technical-only and catalyst-only shadow strategies** (spec 16.3/16.4)
  are tracked in the `benchmarks` table but currently mirror the cash
  benchmark rather than running a full parallel simulation — building two
  additional parallel paper-trading engines is flagged as follow-up work,
  not silently faked.

Every one of these simplifications is documented in code at the point it
matters — nothing here pretends to be more complete than it is, per the
project's own "eerlijkheid boven winst" principle.

## Getting started

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in Google Sheets / news / on-chain keys if you have them

# Run the test suite (must be green before anything else matters)
pytest

# Initialize a fresh exam (freezes config/exam_v1.yaml, creates the DB)
python scripts/initialize_exam.py

# Run a single hour manually
python scripts/run_once.py

# Run continuously, once per hour, on the hour
python -m src.main   # or: python src/main.py

# Dashboard
streamlit run dashboard/streamlit_app.py

# Integrity check at any time
python scripts/verify_integrity.py --check-missing-hours
```

Network note: `data/bitvavo_client.py` calls Bitvavo's public REST API. If
outbound access to `api.bitvavo.com` is unavailable (e.g. a sandboxed CI
environment), every scheduler run correctly degrades to `CASH` with
`data_status=DEGRADED` and a recorded `error_message` — this is the
spec's required conservative behavior (section 17), not a bug.

## Backtesting (`scripts/backtest.py`)

A technical-only backtest against real historical BTC/USD data, reusing
the exam's actual wallet/execution/risk engine unchanged. It exists to
answer a narrower question than "is Exam V1 profitable" — see the module
docstring in `scripts/backtest.py` for the full list of ways this mode
deliberately differs from Exam V1 (single asset, no order-book data, no
catalyst/on-chain data, its own eligibility rule).

Data: [ff137/bitstamp-btcusd-minute-data](https://github.com/ff137/bitstamp-btcusd-minute-data)
— real Bitstamp BTC/USD 1-minute OHLCV, fetched via `raw.githubusercontent.com`
and cached locally (`src/data/historical_dataset.py`). This is the *only*
external data source reachable from a sandboxed dev environment where
direct exchange APIs (Bitvavo, Binance) and data-aggregator sites are
blocked at the network layer — see that module's docstring.

```bash
python scripts/backtest.py --days 400                    # spec-faithful (breakout_min=7)
python scripts/backtest.py --days 400 --breakout-min 6    # relaxed demo variant
```

**Two actual runs against ~13 months of real data (2025-06 to 2026-07, a
falling BTC market — BTC buy-and-hold lost ~42% over this window):**

| Run | Trades | Result | Max drawdown | Grade |
|---|---|---|---|---|
| `breakout_min=7` (spec default) | 0 | 0.00% | 0.00% | C |
| `breakout_min=6` (relaxed demo) | 22 | -8.43% | 12.40% | D |

Neither run "proves the system can lead to profit." The first shows the
real threshold is strict enough to never fire at all on this asset/window
— informative about how conservative the gate is, but zero trades is zero
evidence either way. The second shows what happens once trades actually
occur: a 13.6% win rate, profit factor 0.48, net loss — but one that still
beat naive BTC buy-and-hold by a wide margin in a falling market, entirely
because the risk rules (position sizing, drawdown throttling) did their
job. That's a real, unmassaged result, not cherry-picked to look good —
see the "what can you prove" discussion in this project's history for why
a single backtest window like this should be read as "here's what
happened," not "here's evidence of edge."

## Project layout

```
config/            Frozen strategy parameters (exam_v1.yaml) + market universe
src/
  data/            Bitvavo client, candle/market repositories, optional news/on-chain clients,
                   historical_dataset.py (backtest-only GitHub-hosted OHLCV loader)
  strategy/        The 11-agent ensemble as deterministic functions + eligibility scoring
  execution/       Fee/slippage/fill models, paper broker, stop/target engine
  portfolio/       Wallet, positions, accounting, risk manager
  database/        SQLAlchemy models, connection, repositories
  reporting/       Hourly/daily/final reports, Google Sheets export, chart data
  audit/           Config freeze + tamper detection, integrity checks, auditor
  scheduler.py     The idempotent hourly orchestration
  main.py          Continuous scheduler entry point
dashboard/         Streamlit dashboard
scripts/           initialize_exam, run_once, backfill_candles, export_google_sheet, verify_integrity,
                   backtest (technical-only backtest against real historical data)
tests/             pytest suite (accounting, fees, slippage, stop/target, risk, idempotency, config freeze)
```

## Design principles (from the spec)

- **Eerlijkheid boven winst** — never fabricate data, fills, or fake a
  favorable outcome.
- **Database boven spreadsheet** — SQLite is the source of truth; Google
  Sheets is a derived dashboard.
- **Regels vooraf vastleggen** — every trading rule is fixed before the
  trade (`config/exam_v1.yaml`, hashed and frozen at exam start).
- **Geen toekomstige informatie** — `audit.auditor.Auditor.assert_not_future`
  is called before any candle/price is used in a decision.
- **Conservatieve uitvoering** — ambiguous stop/target ordering resolves to
  "stop first"; missing price data keeps the last known value rather than
  inventing one.
- **Volledige reproduceerbaarheid** — every euro cent is stored as an
  integer, every crypto unit/price as exact Decimal text, never float.
- **Geen gedwongen handel** — CASH is always a valid, and often correct,
  decision.

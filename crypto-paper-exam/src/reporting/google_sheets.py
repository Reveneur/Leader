"""Google Sheets export (spec section 15). The database remains
authoritative; this module only pushes a derived row. Every function here
is designed to never raise into the scheduler — a Sheets failure must never
block or duplicate a trading decision (spec section 15's error-handling
paragraph, section 17).
"""
from __future__ import annotations

from database.models import HourlyRun, SignalScore
from settings import Settings

COLUMNS = [
    "Tijdstip",
    "Strategieversie",
    "Actie",
    "Cash",
    "Asset",
    "Units",
    "Positiewaarde",
    "Walletwaarde",
    "BTC-benchmark",
    "Cashbenchmark",
    "Gerealiseerd resultaat",
    "Ongerealiseerd resultaat",
    "Totale kosten",
    "Topkandidaat",
    "Confidence",
    "Marktregime",
    "Regime score",
    "Residual-strengthscore",
    "Breakoutscore",
    "Volumescore",
    "Liquiditeitsscore",
    "Catalystscore",
    "On-chainscore",
    "Crowdingscore",
    "Executionscore",
    "Adversarial score",
    "Belangrijkste contradictie",
    "Korte toelichting",
    "Datastatus",
    "Run-ID",
]


def _cents_to_str(cents: int) -> str:
    return f"{cents / 100:.2f}"


def build_row(run: HourlyRun, top_score: SignalScore | None) -> list[str]:
    scores = top_score
    return [
        run.scheduled_timestamp.isoformat(),
        run.strategy_version,
        run.action,
        _cents_to_str(run.cash_eur_cents),
        run.asset or "",
        str(run.units) if run.units is not None else "",
        _cents_to_str(run.position_value_eur_cents),
        _cents_to_str(run.equity_eur_cents),
        _cents_to_str(run.btc_benchmark_eur_cents),
        _cents_to_str(run.cash_benchmark_eur_cents),
        _cents_to_str(run.realized_pnl_eur_cents),
        _cents_to_str(run.unrealized_pnl_eur_cents),
        _cents_to_str(run.cumulative_costs_eur_cents),
        run.top_candidate or "",
        str(run.confidence) if run.confidence is not None else "",
        run.regime or "",
        str(scores.regime_fit) if scores else "",
        str(scores.residual_strength) if scores else "",
        str(scores.breakout_quality) if scores else "",
        str(scores.volume_quality) if scores else "",
        str(scores.microstructure_liquidity) if scores else "",
        str(scores.catalyst_credibility) if scores else "",
        str(scores.onchain_confirmation) if scores else "",
        str(scores.crowding_quality) if scores else "",
        str(scores.execution_quality) if scores else "",
        str(scores.adversarial_confidence) if scores else "",
        run.contradiction or "",
        run.explanation or "",
        run.data_status,
        run.run_id,
    ]


def is_configured(settings: Settings) -> bool:
    return bool(settings.google_sheets_credentials_path and settings.google_sheets_spreadsheet_id)


def export_run(run: HourlyRun, top_score: SignalScore | None, settings: Settings) -> tuple[bool, str | None]:
    """Never raises. Returns (ok, error_message). A unique run_id in the
    last column lets a retry safely re-append without ever producing a
    true duplicate decision — dedup-by-run_id is left to the sheet-side
    export script (scripts/export_google_sheet.py) which checks existing
    Run-ID values before appending.
    """
    if not is_configured(settings):
        return False, "Google Sheets not configured (no credentials/spreadsheet id); export skipped"

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        return False, f"gspread not installed: {exc}"

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(settings.google_sheets_credentials_path, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(settings.google_sheets_spreadsheet_id)
        worksheet = sheet.worksheet(settings.google_sheets_worksheet_name)

        existing_run_ids = set(worksheet.col_values(len(COLUMNS)))
        if run.run_id in existing_run_ids:
            return True, None  # already exported; treat as success (idempotent)

        if not existing_run_ids:
            worksheet.append_row(COLUMNS)

        worksheet.append_row(build_row(run, top_score))
        return True, None
    except Exception as exc:  # noqa: BLE001 - any Sheets failure must degrade, not propagate
        return False, str(exc)

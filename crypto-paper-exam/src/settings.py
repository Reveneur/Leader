"""Environment-derived settings. Strategy parameters live in config/exam_v1.yaml
(see strategy.config_freeze), not here — this module only holds deployment
concerns: file paths, credentials, timezone.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bitvavo_api_key: str = ""
    bitvavo_api_secret: str = ""

    database_path: Path = REPO_ROOT / "data" / "exam_v1.sqlite"

    google_sheets_credentials_path: str = ""
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet_name: str = "Walletlog"

    news_api_key: str = ""
    onchain_api_key: str = ""

    exam_timezone: str = "Europe/Amsterdam"

    strategy_config_path: Path = REPO_ROOT / "config" / "exam_v1.yaml"
    markets_config_path: Path = REPO_ROOT / "config" / "markets.yaml"

    @property
    def database_url(self) -> str:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.database_path}"


def get_settings() -> Settings:
    return Settings()

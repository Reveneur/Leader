from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from database.connection import init_db, reset_engine_for_tests, session_scope  # noqa: E402
from database.migrations import drop_schema  # noqa: E402
from settings import REPO_ROOT, Settings  # noqa: E402

REAL_STRATEGY_CONFIG = REPO_ROOT / "config" / "exam_v1.yaml"


@pytest.fixture()
def db_settings(tmp_path, monkeypatch) -> Settings:
    """Every test gets an isolated DB *and* an isolated copy of the strategy
    config, so tests that freeze/tamper with config never touch the real
    repo file at config/exam_v1.yaml.
    """
    reset_engine_for_tests()
    config_copy = tmp_path / "exam_v1.yaml"
    shutil.copy(REAL_STRATEGY_CONFIG, config_copy)
    settings = Settings(database_path=tmp_path / "test_exam.sqlite", strategy_config_path=config_copy)
    init_db(settings)
    yield settings
    drop_schema()
    reset_engine_for_tests()


@pytest.fixture()
def session(db_settings):
    with session_scope(db_settings) as s:
        yield s

import shutil
from pathlib import Path

import pytest

from audit.config_freeze import ConfigTamperedError, freeze_config, load_strategy_config, verify_config

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "exam_v1.yaml"


@pytest.fixture()
def config_copy(tmp_path) -> Path:
    dest = tmp_path / "exam_v1.yaml"
    shutil.copy(REAL_CONFIG, dest)
    return dest


def test_load_strategy_config_parses_real_file():
    config = load_strategy_config(REAL_CONFIG)
    assert config.strategy_version == "Exam V1"
    assert config.wallet.initial_cash_eur == 100
    assert config.portfolio.max_positions == 2


def test_freeze_then_verify_succeeds(session, config_copy):
    freeze_config(session, config_copy)
    session.flush()
    verified = verify_config(session, config_copy)
    assert verified.strategy_version == "Exam V1"


def test_verify_without_freeze_raises(session, config_copy):
    with pytest.raises(ConfigTamperedError):
        verify_config(session, config_copy)


def test_tampered_config_is_detected(session, config_copy):
    freeze_config(session, config_copy)
    session.flush()

    text = config_copy.read_text()
    tampered = text.replace("max_positions: 2", "max_positions: 5")
    config_copy.write_text(tampered)

    with pytest.raises(ConfigTamperedError):
        verify_config(session, config_copy)


def test_unrelated_whitespace_change_is_also_detected(session, config_copy):
    """Even a byte-for-byte formatting change must be caught — the hash is
    over the raw file, not a semantic diff, by design (spec section 19).
    """
    freeze_config(session, config_copy)
    session.flush()

    config_copy.write_text(config_copy.read_text() + "\n")
    with pytest.raises(ConfigTamperedError):
        verify_config(session, config_copy)

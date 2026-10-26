from pathlib import Path

import pytest

from agent.config import Settings


def test_data_dir_default_points_into_user_data() -> None:
    settings = Settings(_env_file=None)
    assert settings.data_dir.name == "agent"
    assert settings.data_dir.is_absolute()


def test_data_dir_override(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.data_dir == tmp_path


def test_data_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.data_dir == tmp_path.resolve()


def test_settings_hold_no_model_fields() -> None:
    """Model/provider settings live in model_config.json, never in Settings."""
    settings = Settings(_env_file=None)
    for gone in (
        "provider",
        "model_name",
        "model_plan",
        "model_code",
        "model_summarize",
        "ollama_base_url",
        "ollama_num_ctx",
        "ollama_keep_alive",
        "validate_model_on_init",
    ):
        assert not hasattr(settings, gone)

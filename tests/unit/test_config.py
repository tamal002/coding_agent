from pathlib import Path

import pytest

from agent.config import ConfigError, Settings, get_model_name


def test_defaults_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MODEL_NAME",
        "MODEL_PLAN",
        "MODEL_CODE",
        "MODEL_SUMMARIZE",
        "OLLAMA_BASE_URL",
        "OLLAMA_NUM_CTX",
        "OLLAMA_KEEP_ALIVE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    assert settings.model_name == ""
    assert settings.model_plan == ""
    assert settings.model_code == ""
    assert settings.model_summarize == ""
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.ollama_num_ctx == 8192
    assert settings.ollama_keep_alive == "30m"


def test_data_dir_override(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.data_dir == tmp_path


def test_data_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.data_dir == tmp_path.resolve()


def test_num_ctx_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
    settings = Settings(_env_file=None)
    assert settings.ollama_num_ctx == 4096


def test_empty_model_name_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, model_name="", model_plan="")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    with pytest.raises(ConfigError) as exc:
        get_model_name("plan")
    assert "No model selected" in str(exc.value)


def test_empty_root_model_name_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, model_name="")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    with pytest.raises(ConfigError) as exc:
        get_model_name(None)
    assert "MODEL_NAME" in str(exc.value)

from pathlib import Path

import pytest

from agent.config import ConfigError, Settings
from agent.infra import paths
from agent.modelconfig import resolver, store


def _unset_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MODEL_NAME", "MODEL_PLAN", "MODEL_CODE", "MODEL_SUMMARIZE"):
        monkeypatch.delenv(name, raising=False)


def _select(tmp_path: Path, *, role: str | None = None) -> Settings:
    """Build a saved selection backed by a temp data dir."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, "ollama", "big")
    store.add_model(config, "ollama", "small")
    store.set_general(config, "ollama", "big")
    if role is not None:
        store.set_role(config, role, "ollama", "small")
    store.save_config(config, paths.config_file(settings))
    return settings


def test_env_role_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Role env override wins over the JSON store, and is always provider ollama."""
    _unset_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_PLAN", "planner")
    settings = _select(tmp_path, role="plan")

    resolved = resolver.resolve_model("plan", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "planner")
    assert resolved.source == "env"


def test_role_env_falls_back_to_general_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MODEL_PLAN", raising=False)
    monkeypatch.setenv("MODEL_NAME", "shared")
    settings = Settings(_env_file=None, data_dir=tmp_path)

    resolved = resolver.resolve_model("code", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "shared")
    assert resolved.source == "env"


def test_role_selection_wins_over_general(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _unset_model_env(monkeypatch)
    settings = _select(tmp_path, role="plan")

    resolved = resolver.resolve_model("plan", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "small")
    assert resolved.source == "config"


def test_role_absent_inherits_general(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _unset_model_env(monkeypatch)
    settings = _select(tmp_path)

    resolved = resolver.resolve_model("code", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "big")
    assert resolved.source == "config"


def test_local_model_name_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("MODEL_NAME", "qwen")
    settings = Settings(_env_file=None, data_dir=tmp_path)

    resolved = resolver.resolve_model(None, settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "qwen")


def test_nothing_set_raises_naming_the_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _unset_model_env(monkeypatch)
    settings = Settings(_env_file=None, data_dir=tmp_path)

    with pytest.raises(ConfigError, match="No model selected") as role_err:
        resolver.resolve_model("plan", settings)
    assert "model use plan" in str(role_err.value)

    with pytest.raises(ConfigError, match="No model selected") as root_err:
        resolver.resolve_model(None, settings)
    assert "MODEL_NAME" in str(root_err.value)


def test_unknown_role_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown role"):
        resolver.resolve_model("bogus")


def test_non_ollama_selection_is_stored_but_refused_at_runtime(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, "openai", "gpt-4o")
    store.set_general(config, "openai", "gpt-4o")
    store.save_config(config, paths.config_file(settings))

    resolved = resolver.resolve_model(None, settings)
    assert resolved.provider == "openai"  # stored, resolvable...

    with pytest.raises(ConfigError, match="runtime currently supports only"):
        resolver.ensure_runtime_provider(resolved.provider)  # ...but not runnable yet

import json
from pathlib import Path
from typing import Any

import pytest

from agent.config import ConfigError, Settings
from agent.infra import paths
from agent.modelconfig import resolver, store


def _select(
    tmp_path: Path,
    *,
    role: str | None = None,
    provider: str = "ollama",
    model_id: str | None = None,
    general_model: str | None = None,
    base_url: str | None = None,
    params: dict[str, Any] | None = None,
) -> Settings:
    """Build a saved selection backed by a temp data dir."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, provider, general_model or "big", base_url=base_url)
    if role is not None:
        store.add_model(config, provider, model_id or "small")
        store.set_role(config, role, provider, model_id or "small")
    store.set_general(config, provider, general_model or "big")
    if params:
        entry = config.providers[provider]
        for item in entry.models:
            if item.id == (model_id or "small"):
                item.params = params
    store.save_config(config, paths.config_file(settings))
    return settings


def test_role_selection_wins_over_general(tmp_path: Path) -> None:
    settings = _select(tmp_path, role="plan")

    resolved = resolver.resolve_model("plan", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "small")
    assert resolved.source == "config"


def test_role_absent_inherits_general(tmp_path: Path) -> None:
    settings = _select(tmp_path)

    resolved = resolver.resolve_model("code", settings)
    assert (resolved.provider, resolved.model_id) == ("ollama", "big")
    assert resolved.source == "config"


def test_resolve_none_returns_general(tmp_path: Path) -> None:
    settings = _select(tmp_path)

    resolved = resolver.resolve_model(None, settings)
    assert resolved.model_id == "big"


def test_nothing_set_raises_naming_the_fix(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)

    with pytest.raises(ConfigError, match="No model selected") as role_err:
        resolver.resolve_model("plan", settings)
    assert "model use plan" in str(role_err.value)
    assert "MODEL_NAME" not in str(role_err.value)  # .env is not part of the chain

    with pytest.raises(ConfigError, match="No model selected") as root_err:
        resolver.resolve_model(None, settings)
    assert "model add" in str(root_err.value)


def test_unknown_role_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown role"):
        resolver.resolve_model("bogus")


def test_keyed_provider_resolves_with_mapping(tmp_path: Path) -> None:
    """A saved non-Ollama model resolves with its LangChain provider string."""
    settings = _select(tmp_path, general_model="gpt-4o", provider="openai")

    resolved = resolver.resolve_model(None, settings)
    assert resolved.provider == "openai"
    assert resolved.langchain_provider == "openai"
    assert resolved.model_id == "gpt-4o"


def test_custom_maps_to_openai_gateway(tmp_path: Path) -> None:
    """A "custom" provider is an OpenAI-compatible endpoint at the saved URL."""
    settings = _select(
        tmp_path,
        provider="custom",
        general_model="my-model",
        base_url="https://api.example.com/v1",
    )

    resolved = resolver.resolve_model(None, settings)
    assert resolved.langchain_provider == "openai"
    assert resolved.base_url == "https://api.example.com/v1"


def test_params_are_carried_into_the_result(tmp_path: Path) -> None:
    """Per-model params are forwarded as the advanced override pocket."""
    settings = _select(tmp_path, role="plan", params={"num_ctx": 8192})

    resolved = resolver.resolve_model("plan", settings)
    assert resolved.params == {"num_ctx": 8192}


def test_selection_pointing_at_removed_model_raises(tmp_path: Path) -> None:
    """A hand-edited JSON pointing at a missing model fails loudly."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, "ollama", "real")
    store.set_general(config, "ollama", "real")
    store.save_config(config, paths.config_file(settings))

    # hand-edit the file: keep the selection but delete the model it names
    path = paths.config_file(settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["selection"]["general"]["model_id"] = "ghost"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ConfigError, match="is not saved"):
        resolver.resolve_model(None, settings)

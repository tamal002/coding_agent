"""Tests for the model door: factory hook, generic provider builds, refusals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama

import agent.llm.provider as provider
from agent.config import ConfigError, Settings
from agent.infra import paths
from agent.llm import get_model, set_model_factory
from agent.modelconfig import store
from tests.fakes import ScriptedChatModel


@pytest.fixture(autouse=True)
def clean_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts and ends with the real model path (no factory)."""
    monkeypatch.setattr(provider, "_factory", None)


def _save_selection(
    tmp_path: Path,
    provider_name: str,
    model_id: str,
    *,
    base_url: str | None = None,
    params: dict[str, Any] | None = None,
) -> Settings:
    """Save one model as the general selection in a temp model_config.json."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, provider_name, model_id, base_url=base_url)
    store.set_general(config, provider_name, model_id)
    if params:
        config.providers[provider_name].models[0].params = params
    store.save_config(config, paths.config_file(settings))
    return settings


def _capture_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace init_chat_model and record every build call (no packages needed)."""
    recorded: dict[str, Any] = {}

    def fake_init(model_id: str, model_provider: str, **kwargs: Any) -> Any:
        recorded["model_id"] = model_id
        recorded["model_provider"] = model_provider
        recorded.update(kwargs)
        return ScriptedChatModel(responses=[])

    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init)
    return recorded


def test_factory_hook_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_model must hand back whatever the injected factory builds."""
    fake = ScriptedChatModel(responses=[])
    monkeypatch.setattr(provider, "_factory", lambda role: fake)
    assert provider.get_model("plan") is fake


def test_factory_model_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scripted model answers `.invoke` with the scripted text."""
    set_model_factory(
        lambda role: ScriptedChatModel(
            responses=[AIMessage(content="hello from the fake")]
        )
    )
    model = get_model("plan")
    reply = model.invoke([HumanMessage(content="hi")])
    assert reply.content == "hello from the fake"


def test_real_path_builds_ollama_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A saved Ollama selection builds a real ChatOllama (no network)."""
    settings = _save_selection(tmp_path, "ollama", "test-model")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)

    model = provider.get_model(None)
    assert isinstance(model, ChatOllama)
    assert model.model == "test-model"


def test_params_are_forwarded_to_init_chat_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The per-model params pocket reaches the unified builder verbatim."""
    settings = _save_selection(
        tmp_path, "ollama", "big-model", params={"num_ctx": 8192}
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)

    model = provider.get_model(None)
    assert isinstance(model, ChatOllama)
    assert model.num_ctx == 8192  # the user's saved param, not code's


def test_keyed_provider_gets_its_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A keyed provider's API key comes from the keyring into api_key."""
    settings = _save_selection(tmp_path, "openai", "gpt-4o")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "agent.llm.provider.secrets.get_api_key", lambda name: "sk-test-123"
    )
    recorded = _capture_init(monkeypatch)

    model = provider.get_model(None)
    assert isinstance(model, ScriptedChatModel)  # returned from the captured call
    assert recorded["model_id"] == "gpt-4o"
    assert recorded["model_provider"] == "openai"
    assert recorded["api_key"] == "sk-test-123"


def test_keyed_provider_without_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A keyed provider with no stored key raises ConfigError naming the fix."""
    settings = _save_selection(tmp_path, "anthropic", "claude-3")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "agent.llm.provider.secrets.get_api_key", lambda name: None
    )
    _capture_init(monkeypatch)

    with pytest.raises(ConfigError, match="agent model add"):
        provider.get_model(None)


def test_custom_maps_to_openai_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A "custom" provider builds through the openai integration at its URL."""
    settings = _save_selection(
        tmp_path,
        "custom",
        "my-model",
        base_url="https://api.example.com/v1",
        params={"temperature": 0},
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "agent.llm.provider.secrets.get_api_key", lambda name: "sk-custom"
    )
    recorded = _capture_init(monkeypatch)

    provider.get_model(None)
    assert recorded["model_provider"] == "openai"
    assert recorded["base_url"] == "https://api.example.com/v1"
    assert recorded["temperature"] == 0
    assert recorded["api_key"] == "sk-custom"


def test_missing_integration_package_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the provider package installed, the door names the fix."""
    settings = _save_selection(tmp_path, "openai", "gpt-4o")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "agent.llm.provider.secrets.get_api_key", lambda name: "sk-test"
    )
    # langchain-openai is not installed in this project, so the real build path
    # fails with ImportError; init_chat_model is NOT captured here.
    with pytest.raises(ConfigError) as exc:
        provider.get_model(None)
    assert "langchain-openai" in str(exc.value)


def test_no_model_selected_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty store -> ConfigError pointing at the model commands."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    with pytest.raises(ConfigError) as exc:
        provider.get_model(None)
    assert "agent model" in str(exc.value)

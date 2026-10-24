"""Tests for the model door: factory hook, real Ollama build, and refusals."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama

import agent.llm.provider as provider
from agent.config import ConfigError, Settings
from agent.llm import get_model, set_model_factory
from tests.fakes import ScriptedChatModel


@pytest.fixture(autouse=True)
def clean_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts and ends with the real model path (no factory)."""
    monkeypatch.setattr(provider, "_factory", None)


def _fake_settings(tmp_path, **overrides: object) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


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
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Without a factory, get_model builds a real ChatOllama (no network)."""
    settings = _fake_settings(
        tmp_path, model_name="test-model", ollama_base_url="http://127.0.0.1:9"
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    model = provider.get_model(None)
    assert isinstance(model, ChatOllama)
    assert model.model == "test-model"
    # An unreachable port must not fail while only building the object.
    assert str(model.base_url) == "http://127.0.0.1:9"


def test_role_env_wins_over_general(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """MODEL_PLAN overrides MODEL_NAME for the plan role."""
    settings = _fake_settings(tmp_path, model_name="general-m", model_plan="planner-m")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    model = provider.get_model("plan")
    assert isinstance(model, ChatOllama)
    assert model.model == "planner-m"


def test_general_falls_back_when_role_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """MODEL_NAME is used when the role has no specific env model."""
    settings = _fake_settings(tmp_path, model_name="general-m", model_plan="")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    model = provider.get_model("code")
    assert isinstance(model, ChatOllama)
    assert model.model == "general-m"


def test_no_model_selected_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """No env model and an empty store -> ConfigError naming the fix."""
    settings = _fake_settings(tmp_path, model_name="")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    with pytest.raises(ConfigError) as exc:
        provider.get_model(None)
    assert "MODEL_NAME" in str(exc.value) or "agent model use" in str(exc.value)

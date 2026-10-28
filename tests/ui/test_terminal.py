"""Tests for the plain terminal session (`agent` with no sub-command).

The session reads task lines from stdin; the CLI test runner feeds that
stdin directly, so a whole session (banner, run, exit) is testable
without a real server.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

import agent.llm.provider as provider
from agent.cli import app
from agent.config import Settings

REPLY = "hello there"

runner = CliRunner()


def _save_selection(
    tmp_path: Path,
    provider_name: str,
    model_id: str,
) -> Settings:
    """Save one model as the general selection in a temp model_config.json."""
    from agent.infra import paths
    from agent.modelconfig import store

    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, provider_name, model_id)
    store.set_general(config, provider_name, model_id)
    store.save_config(config, paths.config_file(settings))
    return settings


@contextmanager
def _scripted_session(settings: Settings, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Patch settings lookups + scripted model for the session under test."""
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    def factory(role: Any) -> Any:
        from tests.fakes import ScriptedChatModel

        return ScriptedChatModel(responses=[AIMessage(content=REPLY)])

    provider.set_model_factory(factory)
    yield
    provider.set_model_factory(None)


def test_session_streams_reply_then_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _save_selection(tmp_path, "ollama", "test-model")
    with _scripted_session(settings, monkeypatch):
        result = runner.invoke(app, [], input="say hi\nexit\n")

    assert result.exit_code == 0
    assert "◆ agent" in result.stdout  # the banner opens the session
    assert "> " in result.stdout  # the prompt
    assert REPLY in result.stdout
    assert "⏺ thinking" in result.stdout
    assert "run finished: done" in result.stdout
    assert "session ended." in result.stdout


def test_session_skips_blank_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _save_selection(tmp_path, "ollama", "test-model")
    with _scripted_session(settings, monkeypatch):
        result = runner.invoke(app, [], input="\n\nexit\n")

    assert result.exit_code == 0
    assert REPLY not in result.stdout  # no run happened
    assert "session ended." in result.stdout


def test_session_eof_closes_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdin ending without 'exit' still closes the session cleanly."""
    settings = _save_selection(tmp_path, "ollama", "test-model")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    result = runner.invoke(app, [], input="")

    assert result.exit_code == 0
    assert "session ended." in result.stdout

"""Tests for `agent run` (JSON Lines, plain rendering, flags) and `agent probe`.

No real server is used: the model door gets the scripted fake via the
factory hook, and the unreachable-endpoint test points the saved base URL
at a closed local port so the probe fails fast and for real.
"""

from __future__ import annotations

import json
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
    *,
    base_url: str | None = None,
) -> Settings:
    """Save one model as the general selection in a temp model_config.json."""
    from agent.infra import paths
    from agent.modelconfig import store

    settings = Settings(_env_file=None, data_dir=tmp_path)
    config = store.empty_config()
    store.add_model(config, provider_name, model_id, base_url=base_url)
    store.set_general(config, provider_name, model_id)
    store.save_config(config, paths.config_file(settings))
    return settings


def _stderr(result: Any) -> str:
    """The runner's stderr, or '' on click versions that mix the streams."""
    try:
        return result.stderr
    except (ValueError, AttributeError):
        return ""


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Temp model selection + scripted factory + patched settings lookups."""
    settings = _save_selection(tmp_path, "ollama", "test-model")
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    def factory(role: Any) -> Any:
        from tests.fakes import ScriptedChatModel

        return ScriptedChatModel(responses=[AIMessage(content=REPLY)])

    provider.set_model_factory(factory)
    yield settings
    provider.set_model_factory(None)


# --- run --json --------------------------------------------------------------


def test_run_json_prints_valid_json_lines(cli_env: Settings) -> None:
    result = runner.invoke(app, ["run", "say hi", "--json"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "stdout must hold the JSON Lines stream"
    events = [json.loads(line) for line in lines]
    assert [event["kind"] for event in events] == [
        "node_entered",
        "text_delta",
        "run_finished",
    ]
    deltas = [event for event in events if event["kind"] == "text_delta"]
    assert "".join(event["text"] for event in deltas) == REPLY
    finished = events[-1]
    assert finished["status"] == "done"
    assert finished["summary"] == REPLY


# --- run --plain -------------------------------------------------------------


def test_run_plain_renders_reply_and_header(cli_env: Settings) -> None:
    result = runner.invoke(app, ["run", "say hi"])

    assert result.exit_code == 0, result.output
    assert REPLY in result.stdout
    assert "⏺ thinking" in result.stdout  # calm action bullet, not the raw node name
    assert "run finished: done" in result.stdout
    # The compact head line is part of plain output.
    assert "mode: ephemeral" in result.stdout
    assert f"project: {Path.cwd().resolve()}" in result.stdout  # cwd default


# --- flag validation ----------------------------------------------------------


def test_plain_and_json_are_exclusive(cli_env: Settings) -> None:
    result = runner.invoke(app, ["run", "hi", "--plain", "--json"])

    assert result.exit_code != 0
    assert "--plain and --json are mutually exclusive" in (
        result.output + _stderr(result)
    )


def test_persist_and_no_persist_are_exclusive(cli_env: Settings) -> None:
    result = runner.invoke(app, ["run", "hi", "--persist", "--no-persist"])

    assert result.exit_code != 0
    assert "mutually exclusive" in (result.output + _stderr(result))


def test_persist_flag_is_reported_in_the_header(cli_env: Settings) -> None:
    result = runner.invoke(app, ["run", "hi", "--persist"])

    assert result.exit_code == 0
    assert "mode: persistent" in result.stdout


# --- project resolution --------------------------------------------------------


def test_project_flag_beats_source_dir(
    cli_env: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = tmp_path / "from_settings"
    flag_project = tmp_path / "from_flag"
    source_project.mkdir()
    flag_project.mkdir()
    monkeypatch.setattr(cli_env, "source_dir", source_project)

    result = runner.invoke(app, ["run", "hi", "--project", str(flag_project)])

    assert result.exit_code == 0
    assert f"project: {flag_project}" in result.stdout
    assert "from_settings" not in result.stdout


def test_source_dir_used_when_no_flag(
    cli_env: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = tmp_path / "from_settings"
    source_project.mkdir()
    monkeypatch.setattr(cli_env, "source_dir", source_project)

    result = runner.invoke(app, ["run", "hi"])

    assert result.exit_code == 0
    assert f"project: {source_project}" in result.stdout


def test_cwd_is_the_default_project(
    cli_env: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing configured -> the current directory is the project, like real agents."""
    default_project = tmp_path / "here"
    default_project.mkdir()
    monkeypatch.chdir(default_project)

    result = runner.invoke(app, ["run", "hi"])

    assert result.exit_code == 0
    assert f"project: {default_project}" in result.stdout


def test_missing_project_dir_is_an_error(cli_env: Settings, tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "hi", "--project", str(tmp_path / "ghost")])

    assert result.exit_code == 2
    assert "project path does not exist" in (result.output + _stderr(result))


# --- probe gating --------------------------------------------------------------


def test_unreachable_endpoint_fails_run_before_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead endpoint stops the run before any event or TUI starts."""

    settings = _save_selection(
        tmp_path,
        "ollama",
        "test-model",
        base_url="http://127.0.0.1:1",  # tcpmux: nothing listens there
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    result = runner.invoke(app, ["run", "hi", "--json"])

    assert result.exit_code == 1
    stderr = _stderr(result)
    assert "unreachable" in stderr
    assert "agent model list" in stderr
    assert result.stdout.strip() == "", "no events may print before the probe passes"


def test_probe_command_reports_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _save_selection(
        tmp_path, "ollama", "test-model", base_url="http://127.0.0.1:1"
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    result = runner.invoke(app, ["probe"])

    assert result.exit_code == 1
    assert "unreachable" in (result.output + _stderr(result))


def test_tui_root_stays_shut_on_unreachable_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`agent` with no sub-command must exit before opening the TUI."""
    settings = _save_selection(
        tmp_path, "ollama", "test-model", base_url="http://127.0.0.1:1"
    )
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    result = runner.invoke(app, [])

    assert result.exit_code == 1
    stderr = _stderr(result)
    assert "unreachable" in stderr
    assert "agent model list" in stderr


def test_unselected_model_fails_with_actionable_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty model config yields the ConfigError fix, not a traceback."""
    settings = Settings(_env_file=None, data_dir=tmp_path)  # no saved models
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.cli.get_settings", lambda: settings)

    result = runner.invoke(app, ["run", "hi"])

    assert result.exit_code == 1
    combined = result.output + _stderr(result)
    assert "agent model" in combined.lower()
    assert "Traceback" not in combined

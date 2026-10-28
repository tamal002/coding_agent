"""The ``agent`` command: the terminal session root, and ``agent run``.

- ``agent`` (no sub-command): show the banner and run the terminal
  session (task lines from stdin) after the model probe passes.
- ``agent run TASK [--plain|--json] [--project PATH] [--persist|--no-persist]``:
  one-shot run through the shared graph stream, printed as it happens.
- ``agent model ...``: the Phase-1.5 model commands (see cli_model.py).
- ``agent probe``: run the reachability check on its own.

This module imports no rich/textual directly (plain text only).
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent.cli_model import app as model_app
from agent.config import ConfigError, Settings, get_settings
from agent.ui.terminal import print_header, stream_task

app = typer.Typer(help="Local-first coding agent built on LangGraph.")
app.add_typer(
    model_app,
    name="model",
    help="Models per provider; keys live in the OS keyring.",
)


# --- shared small resolvers --------------------------------------------------


def _resolve_project(project: Path | None, settings: Settings) -> Path:
    """Pick the project root: ``--project`` beats SOURCE_DIR beats the cwd.

    Like real coding agents, an unconfigured ``agent`` simply works on the
    current directory. A supplied or configured value that does not exist
    is an error.
    """
    chosen = project if project is not None else settings.source_dir
    if chosen is None:
        chosen = Path.cwd()
    resolved = Path(chosen).expanduser().resolve()
    if not resolved.is_dir():
        raise typer.BadParameter(f"project path does not exist: {resolved}")
    return resolved


def _resolve_persist(persist: bool, no_persist: bool, settings: Settings) -> bool:
    """One-shot persistence: flags win over the config preference (default off)."""
    if persist and no_persist:
        raise typer.BadParameter("--persist and --no-persist are mutually exclusive")
    if persist or no_persist:
        return persist
    return settings.persist


def _probe_model() -> tuple[bool, str]:
    """Build the general model and probe its endpoint (cheap, no generation).

    A ``ConfigError`` (no model saved, missing key, missing integration
    package) already names the fix, so it counts as "not reachable" with
    its own message.
    """
    from agent.llm.provider import get_model
    from agent.llm.reach import probe_model_connection

    try:
        model = get_model(None)
    except ConfigError as exc:
        return False, str(exc)
    result = probe_model_connection(model)
    return result.ok, result.detail


def _exit_with_probe_failure(detail: str) -> None:
    """Echo the actionable reason and stop with a nonzero exit code."""
    typer.echo(detail, err=True)
    raise typer.Exit(1)


# --- commands ----------------------------------------------------------------


@app.callback(invoke_without_command=True)
def root(
    context: typer.Context,
    persist: bool = typer.Option(
        False, "--persist", help="Persistent session (Phase 8 wires it; report only)."
    ),
    no_persist: bool = typer.Option(
        False, "--no-persist", help="Ephemeral session."
    ),
    project: Path | None = typer.Option(
        None, "--project", help="Project directory (overrides SOURCE_DIR)."
    ),
) -> None:
    """`agent` with no sub-command starts the terminal session (after the probe)."""
    if context.invoked_subcommand is not None:
        return  # sub-commands do their own setup
    settings = get_settings()
    try:
        chosen_project = _resolve_project(project, settings)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    chosen_persist = _resolve_persist(persist, no_persist, settings)

    ok, detail = _probe_model()
    if not ok:
        _exit_with_probe_failure(detail)
    from agent.ui.terminal import run_terminal

    run_terminal(chosen_project, chosen_persist)


@app.command("run")
def run(
    task: str = typer.Argument(..., help="The task text for the agent."),
    plain: bool | None = typer.Option(
        None, "--plain", help="Readable progress (the default format)."
    ),
    json_mode: bool = typer.Option(False, "--json", help="One JSON line per event."),
    project: Path | None = typer.Option(
        None, "--project", help="Project directory (overrides SOURCE_DIR)."
    ),
    persist: bool = typer.Option(
        False, "--persist", help="Persistent run (Phase 8 wires it; report only)."
    ),
    no_persist: bool = typer.Option(False, "--no-persist", help="Ephemeral run."),
) -> None:
    """Run one task and stream typed events to the terminal."""
    # plain defaults to None so that "--json" alone is not a conflict.
    if plain and json_mode:
        raise typer.BadParameter("--plain and --json are mutually exclusive")

    settings = get_settings()
    try:
        chosen_project = _resolve_project(project, settings)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    chosen_persist = _resolve_persist(persist, no_persist, settings)

    ok, detail = _probe_model()
    if not ok:
        _exit_with_probe_failure(detail)

    print_header(chosen_project, chosen_persist, json_mode)
    stream_task(task, json_mode)


@app.command("probe")
def probe() -> None:
    """Probe the configured model's endpoint and print the result on its own."""
    ok, detail = _probe_model()
    typer.echo(detail)
    if not ok:
        raise typer.Exit(1)


def main() -> None:
    """Call this to run the CLI directly."""
    app()


if __name__ == "__main__":
    main()

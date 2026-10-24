"""The ``agent`` command.

Right now it only has the ``model`` sub-commands; task/plan/TUI commands are
added in later phases. Typer builds ``agent --help`` from this file
automatically.
"""

import typer

from agent.cli_model import app as model_app

app = typer.Typer(help="Local-first coding agent built on LangGraph.")
app.add_typer(model_app, name="model", help="Models per provider; keys live in the OS keyring.")


@app.callback()
def callback() -> None:
    """Called for every ``agent ...`` run; the sub-commands do the real work."""


def main() -> None:
    """Call this to run the CLI directly (`uv run src/agent/cli.py`)."""
    app()


if __name__ == "__main__":
    main()

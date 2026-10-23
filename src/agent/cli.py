"""Console entrypoint for the agent CLI (placeholder until later phases)."""

import typer

from agent.cli_model import app as model_app

app = typer.Typer(help="Local-first coding agent built on LangGraph.")
app.add_typer(model_app, name="model", help="Models per provider; keys live in the OS keyring.")


@app.callback()
def callback() -> None:
    """Placeholder entrypoint; commands are added in later phases."""


def main() -> None:
    """Entry point for direct execution (`uv run src/agent/cli.py`)."""
    app()


if __name__ == "__main__":
    main()

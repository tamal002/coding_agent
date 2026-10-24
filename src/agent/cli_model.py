"""The ``agent model`` sub-commands: add, list, use and remove saved models.

`add` asks the user step by step (provider → model → API key if needed).
Model choices are saved to ``model_config.json``; API keys go to the OS
keyring, never to a file.
"""

from __future__ import annotations

from collections.abc import Sequence

import typer
from rich.console import Console

from agent.config import get_settings
from agent.infra import paths
from agent.modelconfig import secrets, store

app = typer.Typer(
    help="Add, list, select and remove models per provider. "
    "Keys are stored in the OS keyring, never on disk."
)
console = Console()

# Providers that need an API key (Ollama does not need one).
_NEEDS_KEY = frozenset({"openai", "anthropic", "deepseek", "custom"})


def _load() -> store.ModelConfig:
    """Read the model config file for now."""
    return store.load_config(paths.config_file(get_settings()))


def _save(config: store.ModelConfig) -> None:
    """Write the model config file back to disk."""
    store.save_config(config, paths.config_file(get_settings()))


# to show the saved models to user
def _prompt_choice(label: str, options: Sequence[str]) -> int:
    """Show a numbered menu and return the chosen option's number (0-based).

    Keeps asking until the user types a valid number. Pressing Enter picks
    option 1.
    """
    console.print(f"[bold cyan]{label}[/bold cyan]")
    for index, option in enumerate(options, start=1):
        console.print(f"  [green]{index}.[/green] {option}")
    while True:
        raw = typer.prompt("Choose", default="1").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        console.print(f"[red]Enter a number between 1 and {len(options)}.[/red]")


# asks for the base URL for a custom provider, keeps asking until it starts with http(s)://
def _prompt_base_url() -> str:
    """Ask for the base URL and keep asking until it starts with http(s)://."""
    while True:
        url = str(typer.prompt("Base URL (OpenAI-compatible)")).strip()
        if url.startswith(("http://", "https://")):
            return url
        console.print("[red]Base URL must start with http:// or https://[/red]")


# asks for the API key for a provider, shows whether one is already stored, and saves it to the OS keyring if the user types one
def _maybe_prompt_key(provider: str) -> None:
    """Offer to save the provider's API key (skipped for Ollama).

    First shows whether a key already exists ("already stored" / "not set").
    If the user types one, it is saved to the OS keyring; pressing Enter
    with nothing typed keeps things as they are.
    """
    current = secrets.get_api_key(provider)
    status = "already stored" if current else "not set"
    console.print(f"API key for {provider}: {status} (keyring / {secrets.key_env_var(provider)})")
    if provider == "ollama":
        return
    if typer.confirm("Enter an API key now?", default=True):
        api_key = typer.prompt("API key", hide_input=True, default="")
        if api_key:
            secrets.set_api_key(provider, api_key)
            console.print(f"[green]Key stored in the OS keyring for {provider}.[/green]")


# defining 'add' command 
@app.command("add")
def add() -> None:
    """Add a provider + model. If the same model is saved twice, nothing is added.

    Asks: which provider, the model id, and the API key (only for non-Ollama
    providers). Custom providers also ask for a base URL.
    """
    try:
        config = _load()
        provider = store.WIZARD_PROVIDERS[_prompt_choice("Provider", store.WIZARD_PROVIDERS)]
        base_url = _prompt_base_url() if provider == "custom" else None
        model_id = typer.prompt("Model ID").strip()
        while not model_id:
            model_id = typer.prompt("Model ID (required)").strip()

        added = store.add_model(config, provider, model_id, base_url)
        if not added:
            console.print(
                f"[yellow]{provider}/{model_id} is already saved - nothing added.[/yellow]"
            )
        _maybe_prompt_key(provider)
        _save(config)
        console.print(f"[green]Saved {model_id} for {provider}.[/green]")
    except (store.ConfigFormatError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


# defining 'list' command
@app.command("list")
def list_models() -> None:
    """Show all saved models and which model each role actually uses.

    The first part groups models by provider; "★" marks the general model.
    The second part shows: an overridden role ("✎ override") or a role that
    uses the general model ("↳ inherits general").
    """
    config = _load()
    if not config.providers:
        console.print("[yellow]No models saved yet. Run 'agent model add'.[/yellow]")
        return

    console.rule("Providers & models")
    general = config.selection.general
    for provider, entry in config.providers.items():
        header = f"[bold]{provider}[/bold]"
        if entry.base_url:
            header += f"  ({entry.base_url})"
        console.print(header)
        for model in entry.models:
            selected = (
                general is not None
                and general.provider == provider
                and general.model_id == model.id
            )
            marker = "[bold green]★ [/bold green]" if selected else "  "
            runtime_note = (
                ""
                if provider in store.SUPPORTED_RUNTIME_PROVIDERS
                else "  (saved - runtime: ollama-only for now)"
            )
            console.print(f"{marker}{model.id}{runtime_note}")

    console.rule("Effective use by mode")
    for role in ("general", *store.ROLE_NAMES):
        ref = config.selection.general if role == "general" else config.selection.roles.get(role)
        if role == "general":
            label = f"{ref.provider}/{ref.model_id}" if ref else "(not set)"
            console.print(f"general    {label}")
        elif ref is not None:
            console.print(f"{role:<10} {ref.provider}/{ref.model_id}   [cyan]✎ override[/cyan]")
        elif config.selection.general is not None:
            g = config.selection.general
            console.print(f"{role:<10} {g.provider}/{g.model_id}   [dim]↳ inherits general[/dim]")
        else:
            console.print(f"{role:<10} (not set)")
    if general is None:
        console.print("[yellow]No general model selected - run 'agent model use'.[/yellow]")


# defining 'use' command
@app.command("use")
def use(
    role: str | None = typer.Argument(
        None, help="general (default) | plan | code | summarize"
    ),
    unset: bool = typer.Option(
        False, "--unset", help="Remove a role override (falls back to general)."
    ),
) -> None:
    """Pick the model to use: the general one, or one for a specific role.

    Without a role (or with "general"): sets the default model.
    With a role (plan/code/summarize): sets that role's override.
    With ``--unset``: removes a role's override, so it uses the general
    model again. Only already-saved models can be picked.
    """
    try:
        config = _load()
        if unset:
            if role not in store.ROLE_NAMES:
                raise typer.BadParameter("--unset needs a role: plan|code|summarize")
            store.unset_role(config, role)
            _save(config)
            console.print(f"[green]'{role}' now inherits the general model.[/green]")
            return

        if role is not None and role != "general" and role not in store.ROLE_NAMES:
            raise typer.BadParameter("role must be general, plan, code or summarize")

        saved: list[tuple[str, str]] = [
            (provider, model.id)
            for provider, entry in config.providers.items()
            for model in entry.models
        ]
        if not saved:
            console.print("[yellow]No models saved yet. Run 'agent model add'.[/yellow]")
            raise typer.Exit(1)
        index = _prompt_choice("Model", [f"{provider}/{model_id}" for provider, model_id in saved])
        provider, model_id = saved[index]

        if role is None or role == "general":
            store.set_general(config, provider, model_id)
            _save(config)
            console.print(f"[green]General model set: {provider}/{model_id}.[/green]")
        else:
            store.set_role(config, role, provider, model_id)
            _save(config)
            console.print(f"[green]{role} override set: {provider}/{model_id}.[/green]")
    except (store.ConfigFormatError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


# defining 'remove' command
@app.command("remove")
def remove() -> None:
    """Delete a saved model. Any selection that used it is cleared too.

    If a provider ends up with no models left, offers to also delete its
    stored API key from the keyring.
    """
    try:
        config = _load()
        saved: list[tuple[str, str]] = [
            (provider, model.id)
            for provider, entry in config.providers.items()
            for model in entry.models
        ]
        if not saved:
            console.print("[yellow]Nothing to remove - no models are saved.[/yellow]")
            return
        index = _prompt_choice("Remove", [f"{provider}/{model_id}" for provider, model_id in saved])
        provider, model_id = saved[index]

        if store.remove_model(config, provider, model_id):
            _save(config)
            console.print(f"[green]Removed {provider}/{model_id}.[/green]")
            if provider not in config.providers and provider in _NEEDS_KEY:
                if typer.confirm(
                    "That provider has no models left. Remove its stored API key?",
                    default=False,
                ):
                    secrets.clear_api_key(provider)
                    console.print(f"[green]Key removed for {provider}.[/green]")
        else:
            console.print("[yellow]Model not found.[/yellow]")
    except (store.ConfigFormatError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

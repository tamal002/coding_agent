"""Decide which model runs a given role — never by guessing.

The check order (first match wins):

1. Env vars: ``MODEL_PLAN`` / ``MODEL_CODE`` / ``MODEL_SUMMARIZE``, then
   ``MODEL_NAME`` (these are always Ollama models)
2. The role's own selection from ``model_config.json``
3. The general model from ``model_config.json``
4. If nothing is found, raise ``ConfigError`` and explain exactly what to do
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent import config as config_module
from agent.config import ConfigError
from agent.infra import paths
from agent.modelconfig import store

if TYPE_CHECKING:  # pragma: no cover
    from agent.config import Settings
    from agent.modelconfig.store import ModelRef


@dataclass(frozen=True)
class ResolvedModel:
    """The final answer to "which model runs this role?".

    ``provider`` is the backend, e.g. "ollama" (env choices are always Ollama).
    ``model_id`` is the exact model name to use — never invented here.
    ``source`` records where the choice came from: "env" or "config".
    """

    provider: str
    model_id: str
    source: str  # "env" | "config"


def _settings(settings: Settings | None) -> Settings:
    """Return the settings to read env values from.

    Tests pass their own settings here (with a temp data dir);
    normal runs use the one cached settings instance.
    """
    if settings is not None:
        return settings
    return config_module.get_settings()


def _require_known_role(role: str | None) -> None:
    """Check the role name is plan / code / summarize (or None = general).

    Any other name raises ``ValueError``, so a typo can never pick a wrong
    model by accident.
    """
    if role is not None and role not in store.ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {store.ROLE_NAMES}")


def _from_env(role: str | None, settings: Settings) -> ResolvedModel | None:
    """Try to find the model in env vars / .env (step 1).

    For a role, read its own env field first (e.g. ``MODEL_PLAN`` for plan).
    If that is empty, fall back to ``MODEL_NAME``. Any model found here is
    treated as an Ollama model, because env model names are local.

    Returns ``None`` when nothing relevant is set at this layer.
    """
    if role == "plan":
        role_value = settings.model_plan
    elif role == "code":
        role_value = settings.model_code
    elif role == "summarize":
        role_value = settings.model_summarize
    else:
        role_value = ""
    if role_value:
        return ResolvedModel(provider="ollama", model_id=role_value, source="env")
    if settings.model_name:
        return ResolvedModel(provider="ollama", model_id=settings.model_name, source="env")
    return None


def _from_config(role: str | None, settings: Settings) -> ResolvedModel | None:
    """Try to find the model in model_config.json (steps 2-3).

    Asks the store which model the role uses: the role's own override first,
    otherwise the general model. Returns ``None`` when nothing is selected.
    """
    config = store.load_config(paths.config_file(settings))
    ref: ModelRef | None = store.effective_model(config, role)
    if ref is None:
        return None
    return ResolvedModel(provider=ref.provider, model_id=ref.model_id, source="config")


def resolve_model(
    role: str | None = None,
    settings: Settings | None = None,
) -> ResolvedModel:
    """Return the model for the role — or raise ``ConfigError`` with the fix.

    Order: env first, then the role's selection, then the general model.
    ``role`` is None for the general model, or plan/code/summarize.

    Raises:
        ValueError: for an unknown role name.
        ConfigError: when no model is selected anywhere. The message says
            exactly what to run or set — a model is never invented.
    """
    _require_known_role(role)
    active = _settings(settings)

    from_env = _from_env(role, active)
    if from_env is not None:
        return from_env

    from_config = _from_config(role, active)
    if from_config is not None:
        return from_config

    if role is None:
        raise ConfigError(
            "No model selected. Run 'agent model add' and 'agent model use', "
            "or set MODEL_NAME in .env."
        )
    raise ConfigError(
        f"No model selected for role {role!r} and no general model set. "
        f"Run 'agent model use' (general) or 'agent model use {role}', "
        f"or set MODEL_{role.upper()} / MODEL_NAME in .env."
    )


def ensure_runtime_provider(provider: str) -> None:
    """Refuse providers the agent cannot run yet (only Ollama works now).

    Other providers may be saved in the JSON file, but the agent cannot talk
    to them yet. Instead of silently sending their model names to the local
    Ollama server, this raises a clear ``ConfigError``.
    """
    if provider not in store.SUPPORTED_RUNTIME_PROVIDERS:
        raise ConfigError(
            f"Provider {provider!r} is saved but the runtime currently supports only "
            f"{store.SUPPORTED_RUNTIME_PROVIDERS} (multi-provider phase pending). "
            "Select an Ollama model with 'agent model use'."
        )

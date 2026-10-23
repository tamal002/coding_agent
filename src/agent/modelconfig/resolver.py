"""Resolve which model runs a given role — never by guessing.

Chain (highest wins):

1. Env overrides ``MODEL_{ROLE}`` / ``MODEL_NAME`` — always provider ``ollama``
2. ``selection.roles[role]`` from ``model_config.json``
3. ``selection.general`` from ``model_config.json``
4. ``ConfigError`` naming the exact missing step
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
    """The model a role resolved to, plus where the choice came from."""

    provider: str
    model_id: str
    source: str  # "env" | "config"


def _settings(settings: Settings | None) -> Settings:
    if settings is not None:
        return settings
    return config_module.get_settings()


def _require_known_role(role: str | None) -> None:
    if role is not None and role not in store.ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {store.ROLE_NAMES}")


def _from_env(role: str | None, settings: Settings) -> ResolvedModel | None:
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
    config = store.load_config(paths.config_file(settings))
    ref: ModelRef | None = store.effective_model(config, role)
    if ref is None:
        return None
    return ResolvedModel(provider=ref.provider, model_id=ref.model_id, source="config")


def resolve_model(
    role: str | None = None,
    settings: Settings | None = None,
) -> ResolvedModel:
    """Resolve the model for a role or raise ``ConfigError``. Never invents one."""
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
    """Refuse providers the current runtime cannot execute (Ollama-only)."""
    if provider not in store.SUPPORTED_RUNTIME_PROVIDERS:
        raise ConfigError(
            f"Provider {provider!r} is saved but the runtime currently supports only "
            f"{store.SUPPORTED_RUNTIME_PROVIDERS} (multi-provider phase pending). "
            "Select an Ollama model with 'agent model use'."
        )

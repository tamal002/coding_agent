"""Decide which model runs a given role — never by guessing.

``model_config.json`` is the single source of truth; ``.env`` carries no
model settings at all. The check order (first match wins):

1. The role's own selection from ``model_config.json``
   (``plan`` / ``code`` / ``summarize``)
2. The general model from ``model_config.json``
3. If nothing is found, raise ``ConfigError`` and explain exactly what to do

The result carries everything ``provider.py`` needs to build the model
generically: the provider name, the ``model_provider`` string expected by
LangChain's ``init_chat_model``, optional saved base URL, and per-model
params forwarded as kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent import config as config_module
from agent.config import ConfigError
from agent.infra import paths
from agent.modelconfig import store

if TYPE_CHECKING:  # pragma: no cover
    from agent.config import Settings


@dataclass(frozen=True)
class ResolvedModel:
    """The final answer to "which model runs this role?".

    ``provider`` is the saved provider name ("ollama", "openai", "custom").
    ``langchain_provider`` is the string ``init_chat_model`` expects
    ("custom" maps to "openai" at the saved base URL). ``base_url`` and
    ``params`` come from the saved provider/model entry and are forwarded
    when set. ``source`` records where the choice came from (today always
    "config").
    """

    provider: str
    langchain_provider: str
    model_id: str
    base_url: str | None
    params: dict[str, Any] = field(default_factory=dict)
    source: str = "config"


def _settings(settings: Settings | None) -> Settings:
    """Return the settings that resolve the data directory.

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


def _from_config(role: str | None, settings: Settings) -> ResolvedModel:
    """Read the role's (or general) selection from model_config.json.

    The role's own override comes first; otherwise the general model.
    Raises ``ConfigError`` when nothing is selected, and also when the
    selection points at a provider/model that is not saved (a hand-edited
    JSON must fail loudly, not invent anything).
    """
    config = store.load_config(paths.config_file(settings))
    ref = store.effective_model(config, role)
    if ref is None:
        if role is None:
            raise ConfigError(
                "No model selected. Run 'agent model add' to save a model, "
                "then 'agent model use' to select it."
            )
        raise ConfigError(
            f"No model selected for role {role!r}. Run 'agent model add' to save "
            f"a model, then 'agent model use {role}' (or 'agent model use' for the "
            "general default)."
        )
    entry = config.providers.get(ref.provider)
    model_entry = next(
        (m for m in entry.models if m.id == ref.model_id), None
    ) if entry is not None else None
    if entry is None or model_entry is None:
        raise ConfigError(
            f"model_config.json selects {ref.provider}/{ref.model_id}, but that model "
            "is not saved. Re-add it with 'agent model add' or select another with "
            "'agent model use'."
        )
    return ResolvedModel(
        provider=ref.provider,
        langchain_provider=store.LANGCHAIN_PROVIDERS[ref.provider],
        model_id=ref.model_id,
        base_url=entry.base_url,
        params=dict(model_entry.params),
    )


def resolve_model(
    role: str | None = None,
    settings: Settings | None = None,
) -> ResolvedModel:
    """Return the model for the role — or raise ``ConfigError`` with the fix.

    The role's own selection wins; without it the general model is used.
    ``role`` is None for the general model, or plan/code/summarize.

    Raises:
        ValueError: for an unknown role name.
        ConfigError: when no model is selected. The message says exactly
            what to run — a model is never invented.
    """
    _require_known_role(role)
    return _from_config(role, _settings(settings))

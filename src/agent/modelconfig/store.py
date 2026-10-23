"""Provider-keyed model selection store (``model_config.json``).

The JSON file holds preferences only — model ids, per-provider base urls and
role selections. API keys never live here; they go to the OS keyring (see
:mod:`agent.modelconfig.secrets`).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

ROLE_NAMES: tuple[str, ...] = ("plan", "code", "summarize")
WIZARD_PROVIDERS: tuple[str, ...] = ("ollama", "openai", "anthropic", "deepseek", "custom")
SUPPORTED_RUNTIME_PROVIDERS: tuple[str, ...] = ("ollama",)
_CONFIG_VERSION = 1


class ConfigFormatError(Exception):
    """Raised when ``model_config.json`` cannot be parsed or is a bad version."""


# The following classes are used to represent the structure of the model configuration JSON file. They are designed to be compatible with Pydantic for validation and serialization.

class ModelEntry(BaseModel):
    """One user-selected model for one provider."""

    id: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model id must not be blank")
        return value.strip()


class ProviderEntry(BaseModel):
    """Saved models for one provider plus an optional base url."""

    base_url: str | None = None
    models: list[ModelEntry] = Field(default_factory=list)


class ModelRef(BaseModel):
    """A selection: which provider supplies which model id."""

    provider: str
    model_id: str


class Selection(BaseModel):
    """Current selection: one general model plus optional per-role overrides."""

    general: ModelRef | None = None
    roles: dict[str, ModelRef] = Field(default_factory=dict)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, value: dict[str, ModelRef]) -> dict[str, ModelRef]:
        for role in value:
            if role not in ROLE_NAMES:
                raise ValueError(
                    f"unknown role {role!r}; expected one of {ROLE_NAMES}"
                )
        return value


class ModelConfig(BaseModel):
    """Root document of ``model_config.json``."""

    version: int = _CONFIG_VERSION
    providers: dict[str, ProviderEntry] = Field(default_factory=dict)
    selection: Selection = Field(default_factory=Selection)


def empty_config() -> ModelConfig:
    """Return a fresh, empty configuration."""
    return ModelConfig()


# Utility functions for loading, saving, and manipulating the model configuration.

def load_config(path: Path) -> ModelConfig:
    """Load the config file, or return an empty config when it does not exist."""
    if not path.exists():
        return empty_config()
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigFormatError(f"{path}: invalid JSON ({exc})") from exc
    if data.get("version") != _CONFIG_VERSION:
        raise ConfigFormatError(
            f"{path}: unsupported config version {data.get('version')!r}; "
            f"expected {_CONFIG_VERSION}"
        )
    return ModelConfig.model_validate(data)


def save_config(config: ModelConfig, path: Path) -> None:
    """Atomically write the config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".model_config", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fp:
            json.dump(config.model_dump(), fp, indent=2)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def add_model(
    config: ModelConfig,
    provider: str,
    model_id: str,
    base_url: str | None = None,
) -> bool:
    """Add a model for a provider. Returns ``False`` when it already exists.

    Dedup is on the ``(provider, model_id)`` pair — the same id may exist under
    two providers. ``base_url`` is only stored for OpenAI-compatible providers
    (e.g. ``custom``) and updates an existing entry.
    """
    entry = config.providers.setdefault(provider, ProviderEntry())
    if base_url:
        entry.base_url = base_url
    if any(item.id == model_id for item in entry.models):
        return False
    entry.models.append(ModelEntry(id=model_id))
    return True


def remove_model(config: ModelConfig, provider: str, model_id: str) -> bool:
    """Remove a model and any selection referencing it. Returns ``False`` when absent."""
    entry = config.providers.get(provider)
    if entry is None:
        return False
    remaining = [item for item in entry.models if item.id != model_id]
    if len(remaining) == len(entry.models):
        return False
    entry.models = remaining

    selection = config.selection
    if (
        selection.general is not None
        and selection.general.provider == provider
        and selection.general.model_id == model_id
    ):
        selection.general = None
    for role in list(selection.roles):
        ref = selection.roles[role]
        if ref.provider == provider and ref.model_id == model_id:
            del selection.roles[role]

    if not entry.models:
        del config.providers[provider]
    return True


def _require_saved(config: ModelConfig, provider: str, model_id: str) -> None:
    entry = config.providers.get(provider)
    if entry is None or all(item.id != model_id for item in entry.models):
        raise ValueError(f"{provider}/{model_id} is not saved; run 'agent model add' first.")


def set_general(config: ModelConfig, provider: str, model_id: str) -> None:
    """Set the general model used by every role without an override."""
    _require_saved(config, provider, model_id)
    config.selection.general = ModelRef(provider=provider, model_id=model_id)


def set_role(config: ModelConfig, role: str, provider: str, model_id: str) -> None:
    """Set a role override. Roles must be one of ``ROLE_NAMES``."""
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLE_NAMES}")
    _require_saved(config, provider, model_id)
    config.selection.roles[role] = ModelRef(provider=provider, model_id=model_id)


def unset_role(config: ModelConfig, role: str) -> None:
    """Drop a role override so the role inherits the general model again."""
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLE_NAMES}")
    config.selection.roles.pop(role, None)


def effective_model(config: ModelConfig, role: str | None) -> ModelRef | None:
    """Return the model a role effectively uses (override → general → None)."""
    if role is not None:
        ref = config.selection.roles.get(role)
        if ref is not None:
            return ref
    return config.selection.general

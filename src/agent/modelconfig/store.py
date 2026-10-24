"""Store for saved models: reads and writes ``model_config.json``.

The file holds only preferences (providers, models, selections).
API keys are NOT saved here — they go to the OS keyring (see secrets.py).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Role names that can get their own model override.
ROLE_NAMES: tuple[str, ...] = ("plan", "code", "summarize")
# Providers shown in the `agent model add` menu.
WIZARD_PROVIDERS: tuple[str, ...] = ("ollama", "openai", "anthropic", "deepseek", "custom")
# Providers the agent can actually run right now (the rest are saved but refused).
SUPPORTED_RUNTIME_PROVIDERS: tuple[str, ...] = ("ollama",)
# File format version of model_config.json. Bump it when the JSON shape changes.
_CONFIG_VERSION = 1


class ConfigFormatError(Exception):
    """Raised when model_config.json is broken or has an unknown version."""


# The classes below represent the structure of the model configuration JSON file. They are
# designed to be compatible with Pydantic for validation and serialization.

class ModelEntry(BaseModel):
    """One saved model.

    ``id`` is the model name the provider knows, e.g. "qwen2.5-coder:14b".
    ``params`` holds extra provider settings and may be empty.
    """

    id: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        """Reject an empty model id."""
        if not value.strip():
            raise ValueError("model id must not be blank")
        return value.strip()


class ProviderEntry(BaseModel):
    """All saved models of one provider.

    ``base_url`` is needed only for custom (OpenAI-compatible) providers;
    for Ollama the base url comes from .env instead.
    """

    base_url: str | None = None
    models: list[ModelEntry] = Field(default_factory=list)


class ModelRef(BaseModel):
    """A saved choice: which provider gives us which model."""

    provider: str
    model_id: str


class Selection(BaseModel):
    """Which model the user chose to run things with.

    ``general`` is the default model for every role.
    ``roles`` holds models for specific roles only (plan, code, summarize).
    If a role has no entry here, that role uses ``general``.
    """

    general: ModelRef | None = None
    roles: dict[str, ModelRef] = Field(default_factory=dict)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, value: dict[str, ModelRef]) -> dict[str, ModelRef]:
        """Only allow the role names plan, code, summarize."""
        for role in value:
            if role not in ROLE_NAMES:
                raise ValueError(
                    f"unknown role {role!r}; expected one of {ROLE_NAMES}"
                )
        return value


class ModelConfig(BaseModel):
    """The whole model_config.json file — preferences only, never secrets."""

    version: int = _CONFIG_VERSION
    providers: dict[str, ProviderEntry] = Field(default_factory=dict)
    selection: Selection = Field(default_factory=Selection)


def empty_config() -> ModelConfig:
    """Return an empty config — the state when no file exists yet."""
    return ModelConfig()


# Utility functions for loading, saving, and manipulating the model configuration.

def load_config(path: Path) -> ModelConfig:
    """Read the JSON file and return the config as Python objects.

    If the file does not exist, return an empty config (clean first run).
    Raises ConfigFormatError if the JSON is broken or the version is unknown.
    """
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
    """Save the config to the JSON file safely.

    Writes to a temp file first, then replaces the real file with it
    (``os.replace``), so the file is never left half-written.
    Creates the parent folders if needed.
    """
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
    """Add a model under a provider. Returns ``False`` if it already exists.

    The same model name may exist under two different providers.
    ``base_url`` is only stored for custom (OpenAI-compatible) providers,
    and also updates an existing entry.
    """
    entry = config.providers.setdefault(provider, ProviderEntry())
    if base_url:
        entry.base_url = base_url
    if any(item.id == model_id for item in entry.models):
        return False
    entry.models.append(ModelEntry(id=model_id))
    return True


def remove_model(config: ModelConfig, provider: str, model_id: str) -> bool:
    """Remove a model, and clear any selection that was using it.

    Returns ``True`` if the model was removed, ``False`` if it was not found.
    If the provider has no models left, the provider is removed too.
    """
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
    """Check that the model is saved. Raises ``ValueError`` if it is not."""
    entry = config.providers.get(provider)
    if entry is None or all(item.id != model_id for item in entry.models):
        raise ValueError(f"{provider}/{model_id} is not saved; run 'agent model add' first.")


def set_general(config: ModelConfig, provider: str, model_id: str) -> None:
    """Set the default model that every role uses (unless it has its own).

    Raises ``ValueError`` if the model is not saved.
    """
    _require_saved(config, provider, model_id)
    config.selection.general = ModelRef(provider=provider, model_id=model_id)


def set_role(config: ModelConfig, role: str, provider: str, model_id: str) -> None:
    """Set a model for one specific role, e.g. 'plan'.

    Raises ``ValueError`` if the role name is wrong or the model is not saved.
    """
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLE_NAMES}")
    _require_saved(config, provider, model_id)
    config.selection.roles[role] = ModelRef(provider=provider, model_id=model_id)


def unset_role(config: ModelConfig, role: str) -> None:
    """Remove a role override, so that role uses the general model again."""
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLE_NAMES}")
    config.selection.roles.pop(role, None)


def effective_model(config: ModelConfig, role: str | None) -> ModelRef | None:
    """Return the model a role will actually use.

    The role's own override comes first; if it has none, the general model is
    used; ``None`` means nothing is selected at all.
    """
    if role is not None:
        ref = config.selection.roles.get(role)
        if ref is not None:
            return ref
    return config.selection.general

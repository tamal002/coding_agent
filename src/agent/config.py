"""Application configuration and settings."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when a required configuration value is missing."""


def _default_data_dir() -> Path:
    return Path(user_data_dir("agent", "tamal_saha_own")).resolve()


class Settings(BaseSettings):
    """Typed, environment-backed configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # The provider to use for the agent's LLM backend. Currently, only "ollama" is supported.
    provider: Literal["ollama"] = "ollama"

    # General model name; each role below may override it.
    model_name: str = Field(default="")
    # Role-specific overrides: empty means "fall back to model_name".
    model_plan: str = Field(default="")  # planning tasks
    model_code: str = Field(default="")  # coding tasks
    model_summarize: str = Field(default="")  # summarization tasks

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"
    validate_model_on_init: bool = False

    data_dir: Path = Field(
        default_factory=_default_data_dir,
        validation_alias="AGENT_DATA_DIR",
    )

    max_iterations_per_step: int = 25
    max_parallel: int = 4
    tool_timeout_s: int = 120

    max_total_tokens: int = 500_000
    max_wall_minutes: int = 60
    max_cost_usd: float = 5.0

    permission_mode: Literal["ask", "auto-safe", "trusted"] = "ask"
    approval_timeout_s: int = 0


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance; values are read lazily once."""
    return Settings()


def get_model_name(role: str | None = None) -> str:
    """Resolve the model name for a role (env override first, then the wizard
    store), without ever guessing."""
    from agent.modelconfig.resolver import ensure_runtime_provider, resolve_model

    resolved = resolve_model(role)
    ensure_runtime_provider(resolved.provider)
    return resolved.model_id

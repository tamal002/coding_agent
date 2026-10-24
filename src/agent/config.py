"""Application configuration and settings."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when a required setting is missing or wrong.

    The message always says exactly how to fix it (which env var to set, or
    which `agent model` command to run). The code never picks a model by
    itself to hide this error.
    """


def _default_data_dir() -> Path:
    """Return the agent's own storage folder for this OS user.

    Windows:  C:\\Users\\...\\AppData\\Local\\tamal_saha_own\\agent
    Linux:    ~/.local/share/agent
    The folder is only computed here, not created. The ``AGENT_DATA_DIR``
    env var replaces this default path.
    """
    return Path(user_data_dir("agent", "tamal_saha_own")).resolve()


class Settings(BaseSettings):
    """Every agent setting in one place, loaded from .env and env vars.

    Precedence: real environment variables > .env file > defaults below.
    """

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

    # How to reach Ollama.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"
    validate_model_on_init: bool = False

    # The agent's own storage folder (workspaces, artifacts, run logs).
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        validation_alias="AGENT_DATA_DIR",
    )

    # Stop switches so a confused model cannot loop forever.
    max_iterations_per_step: int = 25
    max_parallel: int = 4
    tool_timeout_s: int = 120

    # Whole-session budget stops.
    max_total_tokens: int = 500_000
    max_wall_minutes: int = 60
    max_cost_usd: float = 5.0  # kept for UI parity; local models cost $0

    # Approval behavior: who must approve risky actions, and how long to wait.
    permission_mode: Literal["ask", "auto-safe", "trusted"] = "ask"
    approval_timeout_s: int = 0  # 0 = wait forever for the user's decision


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the agent's settings, built once and then reused everywhere.

    The first call reads .env and env vars; later calls return the same
    object, so settings do not change mid-session.
    """
    return Settings()


def get_model_name(role: str | None = None) -> str:
    """Return the model name the agent must use for the role.

    Env vars (MODEL_PLAN, MODEL_NAME, ...) are checked first, then the saved
    selections in model_config.json. If there is nothing, ``ConfigError`` is
    raised with the exact fix.

    Raises:
        ConfigError: when no model is selected, or the selected provider
            cannot be used yet (only Ollama runs today).
        ValueError: when ``role`` is not plan/code/summarize (or None).
    """
    # Import here to avoid a circular import: resolver imports this module.
    from agent.modelconfig.resolver import ensure_runtime_provider, resolve_model

    resolved = resolve_model(role)
    ensure_runtime_provider(resolved.provider)
    return resolved.model_id

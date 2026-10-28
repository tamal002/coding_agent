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
    """Non-model application settings, loaded from .env and env vars.

    Model selection lives in ``model_config.json`` (resolved by
    ``agent.modelconfig.resolver``); this class never holds model or
    provider settings. Precedence: real environment variables > .env file
    > defaults below.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # The agent's own storage folder (workspaces, artifacts, run logs).
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        validation_alias="AGENT_DATA_DIR",
    )

    # Stop switches so a confused model cannot loop forever.
    # Iterations and wall-clock time bound loopy behavior; parallel fan-out
    # and token counts are deliberately unbounded (the user may want many
    # subagents, and local tokens cost nothing).
    max_iterations_per_step: int = 25
    tool_timeout_s: int = 120

    # Whole-session budget stops.
    max_wall_minutes: int = 60
    max_cost_usd: float = 5.0  # kept for UI parity; local models cost $0

    # Project the agent works on: set via SOURCE_DIR, overridden by
    # --project on `agent run`. Never auto-detected from the current dir.
    source_dir: Path | None = None

    # One-shot run persistence (Phase 8 wires the real checkpointer);
    # --persist/--no-persist override this preference. Default: ephemeral.
    persist: bool = False

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

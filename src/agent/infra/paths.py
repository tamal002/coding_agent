"""Filesystem paths shared across the app."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from agent.config import Settings

_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def data_dir(settings: Settings | None = None) -> Path:
    """Resolve and create the app data directory."""
    from agent.config import get_settings

    path = (settings or get_settings()).data_dir.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_dir(thread_id: str, settings: Settings | None = None) -> Path:
    """Return and create the workspace directory for a thread."""
    _validate_thread_id(thread_id)
    path = data_dir(settings) / "workspaces" / thread_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifacts_dir(thread_id: str, settings: Settings | None = None) -> Path:
    """Return and create the artifact directory for a thread."""
    _validate_thread_id(thread_id)
    path = data_dir(settings) / "artifacts" / thread_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir(settings: Settings | None = None) -> Path:
    """Return and create the directory used to store run logs."""
    path = data_dir(settings) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file(settings: Settings | None = None) -> Path:
    """Return the path of the model-selection config file (not created)."""
    return data_dir(settings) / "model_config.json"


def undo_dir(workspace: Path | str, patch_id: str) -> Path:
    """Return and create the directory for a patch's original content."""
    if not patch_id or any(ch in patch_id for ch in ".\\/"):
        raise ValueError(f"Invalid patch_id: {patch_id!r}")
    path = Path(workspace) / ".agent" / "undo" / patch_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_thread_id(thread_id: str) -> None:
    if not _THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError(
            "thread_id must match '^[A-Za-z0-9_-]{1,64}$', got "
            + repr(thread_id)
        )

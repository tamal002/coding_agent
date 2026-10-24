"""Filesystem paths the agent uses.

Every folder helper creates its folder on first use and is safe to call
many times. Thread-scoped paths check the thread id first, so values like
"../evil" can never sneak into a path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from agent.config import Settings

# A thread id may only contain letters, digits, "_" and "-" (max 64 chars).
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def data_dir(settings: Settings | None = None) -> Path:
    """Return the agent's own storage folder, creating it if it does not exist.

    Everything the agent keeps for itself lives here (workspaces, artifacts,
    run logs, model_config.json).
    """
    from agent.config import get_settings

    path = (settings or get_settings()).data_dir.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_dir(thread_id: str, settings: Settings | None = None) -> Path:
    """Return ``<data_dir>/workspaces/<thread_id>``, creating it if missing.

    This is the agent's scratch space for one session — never the user's
    project. Raises ``ValueError`` for unsafe thread ids.
    """
    _validate_thread_id(thread_id)
    path = data_dir(settings) / "workspaces" / thread_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifacts_dir(thread_id: str, settings: Settings | None = None) -> Path:
    """Return ``<data_dir>/artifacts/<thread_id>``, creating it if missing.

    Home for big payloads (large diffs, long command output) that approval
    prompts point at instead of printing in full. Raises ``ValueError`` for
    unsafe thread ids.
    """
    _validate_thread_id(thread_id)
    path = data_dir(settings) / "artifacts" / thread_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir(settings: Settings | None = None) -> Path:
    """Return ``<data_dir>/runs``, creating it if missing. Session logs live here."""
    path = data_dir(settings) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file(settings: Settings | None = None) -> Path:
    """Return the path of ``model_config.json`` (does not create anything)."""
    return data_dir(settings) / "model_config.json"


def undo_dir(workspace: Path | str, patch_id: str) -> Path:
    """Return ``<workspace>/.agent/undo/<patch_id>``, creating it if missing.

    This folder is inside the USER'S project, so saved backups travel with
    the code. Raises ``ValueError`` for a bad patch_id (empty, or containing
    "." "\\" "/").
    """
    if not patch_id or any(ch in patch_id for ch in ".\\/"):
        raise ValueError(f"Invalid patch_id: {patch_id!r}")
    path = Path(workspace) / ".agent" / "undo" / patch_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_thread_id(thread_id: str) -> None:
    """Raise ``ValueError`` when a thread id is not safe to use in a path."""
    if not _THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError(
            "thread_id must match '^[A-Za-z0-9_-]{1,64}$', got "
            + repr(thread_id)
        )

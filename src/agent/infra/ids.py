"""Short, safe identifiers for runs and threads.

Format follows the locked thread-id convention (characters: letters,
digits, '-' and '_', max 64 chars); the name is stored/attached per
session in later phases (plan section 2.1, rule 9).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

# The one id spelling the whole project uses.
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_thread_id(scope: str) -> str:
    """Return a fresh thread id, e.g. 'tui-20261027-142530-a1b2c3'.

    ``scope`` prefixes the id so interfaces can tell their threads apart
    ("tui", "run", "cli").
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{scope}-{stamp}-{suffix}"


def new_run_id() -> str:
    """Return a fresh, short run id, e.g. 'r-4f9d0a1c3b7e'."""
    return f"r-{uuid.uuid4().hex[:12]}"


def assert_valid_id(value: str) -> str:
    """Check an id against the shared pattern; raises ``ValueError`` if bad.

    Callers that receive ids from outside (config, CLI) use this so a
    broken id can never reach later checkpoint storage.
    """
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"invalid id {value!r}: 1-64 characters of letters, digits, "
            f"'-' and '_' expected ({ID_PATTERN.pattern})"
        )
    return value

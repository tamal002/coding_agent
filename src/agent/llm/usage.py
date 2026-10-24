"""Token and cost accounting for model calls.

Ollama runs locally and costs nothing, so the cost is always
``$0.00 (local)``. ``config/prices.yaml`` is kept empty for a future
per-model price table; until then every model is free.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class UsageTracker:
    """Adds up tokens used by model calls across a session.

    Start a tracker at session start and feed it the ``usage_metadata``
    of every reply; display the running total in the UI or logs.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0  # local models are free

    def record(self, usage: Mapping[str, Any] | None) -> None:
        """Add one reply's token counts.

        Older or thinner payloads may lack some keys; missing keys simply
        count as zero instead of failing the call.
        """
        if not usage:
            return
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens

    def record_from_message(self, message: Any) -> None:
        """Read ``usage_metadata`` off a reply message and record it."""
        self.record(getattr(message, "usage_metadata", None))

    def display(self) -> str:
        """One short line for the status bar, e.g. '13 in / 7 out • $0.00 (local)'."""
        return (
            f"{self.input_tokens:,} in / {self.output_tokens:,} out • "
            "$0.00 (local)"
        )

"""The shared LangGraph state for the agent graph (plan section 2.3).

Deliberately empty for now: later phases add exactly the fields they need
(messages in Phase 7, workspace_path in Phase 5, thread/run ids in Phase 8).
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict):
    """No fields yet; extended phase by phase."""


__all__ = ["AgentState"]

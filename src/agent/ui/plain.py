"""Plain terminal rendering of the agent's typed events.

Imported by ``cli.py`` for ``--plain`` mode. This module must stay
import-free of third-party display libraries: plain strings only.
``None`` from a formatter means "delta text, printed inline".
"""

from __future__ import annotations

import re
from typing import Any

from agent.events.models import (
    AgentEvent,
    ErrorEvent,
    EventBase,
    FileRead,
    InterruptRequested,
    LogEvent,
    NodeEntered,
    PatchApplied,
    PatchProposed,
    PatchRejected,
    RunFinished,
    StepStatus,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolStarted,
)

# Rendering follows the Claude-Code chat pattern: agent actions are
# bullets ("⏺ thinking", "⏺ reading src/x.py") and the result of an
# action is a subordinate line ("⎿ done · 12ms").

# Node names → calm, short action phrases (low-noise wording like
# "thinking", later phases extend the table as nodes arrive).
NODE_VERBS: dict[str, str] = {
    "respond": "thinking",
    "controller": "thinking",
    "plan": "planning",
    "outline": "planning",
    "code": "editing",
    "act": "editing",
    "summarize": "summarizing",
    "verify": "verifying",
}

# Known tool names → calm phrases; unknown tools fall back to "running <tool>".
TOOL_VERBS: dict[str, str] = {
    "read_file": "reading",
    "write_file": "writing",
    "edit_file": "editing",
    "search_files": "searching",
    "grep": "searching",
    "find_files": "searching",
    "run_command": "running",
    "bash": "running",
}

# Args keys whose value names the thing the tool touches (first match
# becomes the displayed target; tools are not built yet, so this stays
# a short generic list).
_TARGET_KEYS = ("path", "file_path", "query", "pattern", "command", "url")


def _node_verb(node: str) -> str:
    """A calm phrase for a node name (phase/number prefixes stripped)."""
    name = re.sub(r"^n\d+[-_]", "", node.lower())
    for key, verb in NODE_VERBS.items():
        if key in name:
            return verb
    return name


def _tool_verb(tool: str) -> str:
    """A calm phrase for a tool name."""
    verb = TOOL_VERBS.get(tool.lower(), "running")
    if verb == "running":
        # bare "running" needs the tool name as its object
        return f"running {tool}"
    return verb


def _tool_target(args: dict[str, Any]) -> str:
    """A short display target from the tool's (already truncated) args."""
    for key in _TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            one_line = " ".join(value.split())
            return one_line if len(one_line) <= 60 else one_line[:57] + "..."
    return ""


def format_plain(event: AgentEvent) -> str | None:
    """Return one display line for most events; ``None`` for inline deltas.

    ``text_delta``/``thinking_delta`` are streamed character-for-character,
    so they do not get their own line here.
    """
    # Text deltas stream inline; nothing to format.
    if isinstance(event, (TextDelta, ThinkingDelta)):
        return None
    if isinstance(event, NodeEntered):
        return f"⏺ {_node_verb(event.node)}"
    if isinstance(event, ToolStarted):
        return f"⏺ {_tool_verb(event.tool)} {_tool_target(event.args)}".rstrip()
    if isinstance(event, ToolFinished):
        outcome = "done" if event.ok else "failed"
        return f"⎿ {outcome} · {event.duration_ms}ms"
    if isinstance(event, FileRead):
        return f"⎿ read {event.lines} lines of {event.path}"
    if isinstance(event, PatchProposed):
        return f"⏺ editing {event.path}"
    if isinstance(event, PatchApplied):
        return f"⎿ applied {event.path}"
    if isinstance(event, PatchRejected):
        return f"⎿ rejected {event.path} ({event.reason})"
    if isinstance(event, LogEvent):
        return f"[{event.level}] {event.message}"
    if isinstance(event, StepStatus):
        return f"step {event.step_id}: {event.status}"
    if isinstance(event, ErrorEvent):
        prefix = "error" if event.error_kind == "fatal" else event.error_kind
        return f"[error:{prefix}] {event.message}"
    if isinstance(event, InterruptRequested):
        return (
            f"interrupt ({event.gate}) — {event.interrupt_kind}: "
            f"approval needed (id {event.interrupt_id})"
        )
    if isinstance(event, RunFinished):
        return f"run finished: {event.status}"
    # Remaining kinds (tool/patch/plan/context/approval/usage/...) render
    # generically until their phases build real presentations.
    return _generic(event)


def _generic(event: EventBase) -> str:
    """A readable one-line fallback for event kinds without a renderer yet."""
    payload = {
        key: value
        for key, value in event.model_dump().items()
        if key not in {"kind", "run_id", "thread_id", "ts", "step_id", "agent"}
    }
    shown = str(payload) if payload else ""
    return f"{event.kind} {shown}".rstrip()

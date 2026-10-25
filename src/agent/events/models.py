"""The typed event contract shared by the runtime and the UI (plan section 2.1).

Every event has the shared fields (kind, run_id, thread_id, ts, step_id,
agent) plus its own payload fields. Each kind is one model class; the
``AgentEvent`` union is what code should parse and pass around, so any
event received can be narrowed by its ``kind``.

Two small renames against the plan table, because the base field ``kind``
is the event's own type tag: the payload ``kind`` of ``interrupt_requested``
is called ``interrupt_kind``, and the payload ``kind`` of ``error`` is
called ``error_kind``.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

# The exact event kinds from the plan; nothing outside this list exists.
EventKind = Literal[
    "node_entered",
    "text_delta",
    "thinking_delta",
    "tool_started",
    "tool_finished",
    "file_read",
    "patch_proposed",
    "patch_applied",
    "patch_rejected",
    "plan_updated",
    "step_status",
    "context_updated",
    "interrupt_requested",
    "approval_resolved",
    "usage",
    "retry",
    "error",
    "run_finished",
    "log",
]


class EventBase(BaseModel):
    """The fields every event carries."""

    model_config = ConfigDict(extra="forbid")

    kind: EventKind
    run_id: str
    thread_id: str
    ts: float = Field(default_factory=time.time)
    step_id: str | None = None
    agent: str | None = None


# --- node / LLM stream events -------------------------------------------


class NodeEntered(EventBase):
    kind: Literal["node_entered"] = "node_entered"
    node: str
    name: str


class TextDelta(EventBase):
    kind: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDelta(EventBase):
    kind: Literal["thinking_delta"] = "thinking_delta"
    text: str


# --- tool events ---------------------------------------------------------


class ToolStarted(EventBase):
    kind: Literal["tool_started"] = "tool_started"
    call_id: str
    tool: str
    args: dict[str, Any]  # already truncated by the sender


class ToolFinished(EventBase):
    kind: Literal["tool_finished"] = "tool_finished"
    call_id: str
    tool: str
    ok: bool
    duration_ms: int
    output_preview: str


class FileRead(EventBase):
    kind: Literal["file_read"] = "file_read"
    path: str
    start: int | None = None
    end: int | None = None
    lines: int  # number of lines read (bounded payload; content stays in tools)


# --- patch events --------------------------------------------------------


class PatchProposed(EventBase):
    kind: Literal["patch_proposed"] = "patch_proposed"
    patch_id: str
    path: str
    diff: str


class PatchApplied(EventBase):
    kind: Literal["patch_applied"] = "patch_applied"
    patch_id: str
    path: str


class PatchRejected(EventBase):
    kind: Literal["patch_rejected"] = "patch_rejected"
    patch_id: str
    path: str
    reason: str


# --- plan / step / context events ---------------------------------------


class PlanUpdated(EventBase):
    kind: Literal["plan_updated"] = "plan_updated"
    plan: dict[str, Any]  # the serialized plan (section 2.2 shape)


class StepStatus(EventBase):
    kind: Literal["step_status"] = "step_status"
    step_id: str
    status: str


class ContextUpdated(EventBase):
    kind: Literal["context_updated"] = "context_updated"
    tokens_used: int
    tokens_window: int
    refs_count: int
    note: str


# --- human gate events ---------------------------------------------------


class InterruptRequested(EventBase):
    # ``kind`` names the event; ``interrupt_kind`` is the payload kind
    # (clarify / plan / tool / blocker) from the plan table.
    kind: Literal["interrupt_requested"] = "interrupt_requested"
    interrupt_id: str  # LangGraph Interrupt.id - the only valid resume key
    gate: Literal["H1", "H2", "H3", "H4"]
    interrupt_kind: Literal["clarify", "plan", "tool", "blocker"]
    payload: dict[str, Any]


class ApprovalResolved(EventBase):
    kind: Literal["approval_resolved"] = "approval_resolved"
    interrupt_id: str
    gate: Literal["H1", "H2", "H3", "H4"]
    decision: dict[str, Any]
    status: Literal["resolved", "rejected", "cancelled"]


# --- usage / recovery / finalization events ------------------------------


class UsageEvent(EventBase):
    kind: Literal["usage"] = "usage"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # always 0.0 for local Ollama


class RetryEvent(EventBase):
    kind: Literal["retry"] = "retry"
    step_id: str
    attempt: int
    max_attempts: int
    reason: str
    next_action: str


class ErrorEvent(EventBase):
    # ``kind`` names the event; ``error_kind`` is the payload kind
    # (transient / context / plan / agent / fatal / verify).
    kind: Literal["error"] = "error"
    error_kind: Literal["transient", "context", "plan", "agent", "fatal", "verify"]
    message: str
    step_id: str | None = None


class RunFinished(EventBase):
    kind: Literal["run_finished"] = "run_finished"
    status: Literal["done", "partial", "aborted"]
    changed_files: list[str]
    summary: str


class LogEvent(EventBase):
    kind: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"]
    message: str


AgentEvent = Annotated[
    NodeEntered
    | TextDelta
    | ThinkingDelta
    | ToolStarted
    | ToolFinished
    | FileRead
    | PatchProposed
    | PatchApplied
    | PatchRejected
    | PlanUpdated
    | StepStatus
    | ContextUpdated
    | InterruptRequested
    | ApprovalResolved
    | UsageEvent
    | RetryEvent
    | ErrorEvent
    | RunFinished
    | LogEvent,
    Field(discriminator="kind"),
]

# One adapter, built once, used by both directions (build in emit.py, parse in mapper.py).
EVENT_ADAPTER: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def parse_event(data: Any) -> AgentEvent:
    """Validate a plain dict (or model dict) as one of the event kinds.

    Raises ``ValidationError`` when the shape does not match the contract;
    the caller decides how to report that.
    """
    return EVENT_ADAPTER.validate_python(data)


__all__ = [
    "ValidationError",
    # base
    "EventBase",
    "AgentEvent",
    "EventKind",
    "parse_event",
    # events
    "NodeEntered",
    "TextDelta",
    "ThinkingDelta",
    "ToolStarted",
    "ToolFinished",
    "FileRead",
    "PatchProposed",
    "PatchApplied",
    "PatchRejected",
    "PlanUpdated",
    "StepStatus",
    "ContextUpdated",
    "InterruptRequested",
    "ApprovalResolved",
    "UsageEvent",
    "RetryEvent",
    "ErrorEvent",
    "RunFinished",
    "LogEvent",
]

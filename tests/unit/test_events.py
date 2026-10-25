"""Tests for the typed event contract (plan section 2.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.events.emit import drain_events, emit, make_event
from agent.events.models import (
    AgentEvent,
    ErrorEvent,
    InterruptRequested,
    LogEvent,
    NodeEntered,
    parse_event,
)

PAYLOADS: dict[str, dict[str, object]] = {
    "node_entered": {"node": "N3", "name": "n3_build_context"},
    "text_delta": {"text": "hello"},
    "thinking_delta": {"text": "reasoning"},
    "tool_started": {"call_id": "c1", "tool": "read_file", "args": {"path": "a.py"}},
    "tool_finished": {
        "call_id": "c1",
        "tool": "read_file",
        "ok": True,
        "duration_ms": 12,
        "output_preview": "...",
    },
    "file_read": {"path": "a.py", "start": 1, "end": 10, "lines": 10},
    "patch_proposed": {"patch_id": "p1", "path": "a.py", "diff": "+x"},
    "patch_applied": {"patch_id": "p1", "path": "a.py"},
    "patch_rejected": {"patch_id": "p1", "path": "a.py", "reason": "user said no"},
    "plan_updated": {"plan": {"steps": []}},
    "step_status": {"status": "done"},
    "context_updated": {
        "tokens_used": 100,
        "tokens_window": 8000,
        "refs_count": 3,
        "note": "",
    },
    "interrupt_requested": {
        "interrupt_id": "i1",
        "gate": "H3",
        "interrupt_kind": "tool",
        "payload": {"tool": "read_file"},
    },
    "approval_resolved": {
        "interrupt_id": "i1",
        "gate": "H3",
        "decision": {"approved": True},
        "status": "resolved",
    },
    "usage": {
        "model": "llama3.1",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.0,
    },
    "retry": {
        "attempt": 2,
        "max_attempts": 3,
        "reason": "timeout",
        "next_action": "wait 1s",
    },
    "error": {"error_kind": "fatal", "message": "boom"},
    "run_finished": {
        "status": "done",
        "changed_files": ["a.py"],
        "summary": "ok",
    },
    "log": {"level": "info", "message": "hi"},
}


ALL_KINDS = [
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


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_kind_builds_and_roundtrips(kind: str) -> None:
    event = make_event(
        kind, PAYLOADS[kind], "run-1", "thread-1", step_id="s", agent="A"
    )
    assert event.kind == kind
    assert event.run_id == "run-1"
    assert event.thread_id == "thread-1"
    assert event.ts > 0
    assert event.step_id == "s"
    assert event.agent == "A"

    # A node emits the dict form through the stream; the consumer parses it back.
    parsed = parse_event(event.model_dump())
    assert parsed.kind == kind


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event({"kind": "mystery", "run_id": "r", "thread_id": "t"})


def test_required_payload_field_is_rejected() -> None:
    data = {"kind": "text_delta", "run_id": "r", "thread_id": "t"}  # no text
    with pytest.raises(ValidationError):
        parse_event(data)


def test_wrong_payload_type_is_rejected() -> None:
    data = {"kind": "text_delta", "run_id": "r", "thread_id": "t", "text": 5}
    with pytest.raises(ValidationError):
        parse_event(data)


def test_interrupt_requested_validates_gate_and_kind() -> None:
    event = InterruptRequested(
        run_id="r",
        thread_id="t",
        interrupt_id="abc123",
        gate="H1",
        interrupt_kind="clarify",
        payload={"question": "which approach?"},
    )
    assert event.interrupt_id == "abc123"
    assert event.gate == "H1"

    with pytest.raises(ValidationError):
        # gate outside H1-H4 is not an event the contract knows
        InterruptRequested(
            run_id="r",
            thread_id="t",
            interrupt_id="abc123",
            gate="H9",
            interrupt_kind="tool",
            payload={},
        )


def test_error_event_can_carry_step_id() -> None:
    event = ErrorEvent(
        run_id="r", thread_id="t", error_kind="transient", message="429", step_id="s2"
    )
    assert event.step_id == "s2"


def test_emit_outside_a_graph_run_fills_the_sink() -> None:
    emit(make_event("log", {"level": "info", "message": "one"}, "r", "t"))
    emit(make_event("log", {"level": "info", "message": "two"}, "r", "t"))

    collected = drain_events()
    logs = [e for e in collected if isinstance(e, LogEvent)]
    assert [e.message for e in logs] == ["one", "two"]
    assert drain_events() == []  # sink is empty after draining


def test_narrowing_by_kind() -> None:
    event: AgentEvent = parse_event(
        {
            "kind": "node_entered",
            "run_id": "r",
            "thread_id": "t",
            "node": "N3",
            "name": "n3_build_context",
        }
    )
    if isinstance(event, NodeEntered):
        assert event.node == "N3"
    else:
        pytest.fail("expected NodeEntered")

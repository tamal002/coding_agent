"""Turn LangGraph stream parts into typed agent events.

The runner walks ``graph.astream(...)`` and hands each stream part here.
Verified against the installed LangGraph (v1.2.16, ``version="v2"``):
each part is a dict with keys ``type`` (``custom`` / ``updates`` /
``messages``), ``ns`` (a tuple; empty at the top graph) and ``data``.

Mappings:
- ``custom``   -> the event the node sent through ``emit`` (validated).
- ``updates``  -> ``interrupt_requested`` for each fresh ``__interrupt__``
                  entry (deduped by ``Interrupt.id`` per run); other state
                  deltas produce nothing here - nodes emit their own
                  ``node_entered`` through ``emit``.
- ``messages`` -> ``text_delta`` for the model's text chunks.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import StreamPart
from pydantic import ValidationError

from agent.events.models import (
    AgentEvent,
    InterruptRequested,
    LogEvent,
    TextDelta,
    parse_event,
)


def map_stream_part(
    part: StreamPart[Any, Any],
    run_id: str,
    thread_id: str,
    seen_interrupt_ids: set[str],
) -> list[AgentEvent]:
    """Map one stream part to zero or more typed events.

    ``seen_interrupt_ids`` holds every ``Interrupt.id`` already reported in
    this run; LangGraph re-announces still-pending interrupts after a
    resume, so repeats are skipped here (plan section 2.1 rule: no
    duplicate pending-approval events).
    """
    part_type = part["type"]
    ns = part["ns"]
    agent = _ns_agent(ns)  # empty tuple -> None

    data = part["data"]
    if part_type == "custom":
        return _map_custom(data, run_id, thread_id, agent)
    if part_type == "updates":
        return _map_updates(data, run_id, thread_id, agent, seen_interrupt_ids)
    if part_type == "messages":
        return _map_messages(data, run_id, thread_id, agent)
    return _warn(
        f"unknown stream part type {part_type!r}", run_id, thread_id
    )


def _ns_agent(ns: tuple[str, ...]) -> str | None:
    """A short label for where a nested event came from ('run_child/kid').

    LangGraph namespace entries look like ``node_name:task_id``; keeping
    only the node name part keeps the label stable while remaining unique
    enough to see that the event came from a nested graph.
    """
    if not ns:
        return None
    return "/".join(str(item).split(":", 1)[0] for item in ns)


def _map_custom(
    data: Any,
    run_id: str,
    thread_id: str,
    agent: str | None,
) -> list[AgentEvent]:
    """Validate a node's own event; unknown shapes become a warning log."""
    try:
        event = parse_event(data) if isinstance(data, dict) else None
    except ValidationError:
        event = None
    if event is None:
        return _warn(
            f"custom stream part is not a known event: {str(data)[:120]}",
            run_id,
            thread_id,
        )
    if agent is not None and event.agent is None:
        # The node did not name its subagent; the namespace tells us where
        # it came from, so keep that context instead of dropping it.
        event = event.model_copy(update={"agent": agent})
    return [event]


def _map_updates(
    data: Any,
    run_id: str,
    thread_id: str,
    agent: str | None,
    seen_interrupt_ids: set[str],
) -> list[AgentEvent]:
    """Report fresh interrupts; other state deltas are internal bookkeeping."""
    if not isinstance(data, dict) or "__interrupt__" not in data:
        return []
    events: list[AgentEvent] = []
    for interrupt_obj in data["__interrupt__"]:
        interrupt_id = getattr(interrupt_obj, "id", None)
        if not interrupt_id or interrupt_id in seen_interrupt_ids:
            continue
        seen_interrupt_ids.add(interrupt_id)
        events.append(
            _interrupt_event(
                interrupt_obj, interrupt_id, run_id, thread_id, agent
            )
        )
    return events


def _interrupt_event(
    interrupt_obj: Any,
    interrupt_id: str,
    run_id: str,
    thread_id: str,
    agent: str | None,
) -> InterruptRequested:
    """Build ``interrupt_requested`` from a LangGraph Interrupt.

    Phase 9's gate nodes pass a dict payload with ``gate`` and
    ``interrupt_kind`` keys. For simple temporary payloads those fields are
    unknown, so the tool-gate defaults are used instead of crashing.
    """
    value = interrupt_obj.value
    payload = value if isinstance(value, dict) else {}
    gate = payload.get("gate", "H3")
    interrupt_kind = payload.get("interrupt_kind", "tool")
    return InterruptRequested(
        run_id=run_id,
        thread_id=thread_id,
        agent=agent,
        interrupt_id=interrupt_id,
        gate=gate,
        interrupt_kind=interrupt_kind,
        payload=payload,
    )


def _map_messages(
    data: Any,
    run_id: str,
    thread_id: str,
    agent: str | None,
) -> list[AgentEvent]:
    """Turn model text chunks into ``text_delta`` events (skipping empties)."""
    if not isinstance(data, tuple) or not data:
        return []
    chunk = data[0]
    text = getattr(chunk, "content", None)
    if not isinstance(text, str) or not text:
        return []
    return [
        TextDelta(
            run_id=run_id,
            thread_id=thread_id,
            agent=agent,
            text=text,
        )
    ]


def _warn(message: str, run_id: str, thread_id: str) -> list[AgentEvent]:
    """A visible warning instead of silently dropping an unmappable part."""
    return [
        LogEvent(
            run_id=run_id,
            thread_id=thread_id,
            level="warning",
            message=message,
        )
    ]

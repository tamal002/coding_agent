"""How nodes and helpers send events.

Building: ``make_event`` is the one place that fills the shared fields
(run_id, thread_id, timestamp, optional step/agent) consistently.

Sending: ``emit`` sends the event to LangGraph's custom stream when the
code runs inside a graph node, and stores it in a simple list otherwise
(so node helpers are still testable outside a run).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from langgraph.config import get_stream_writer

from agent.events.models import AgentEvent, parse_event

# Where events land when there is no graph run around them (tests, scripts,
# small tools). Only ever held in memory, never persisted.
_sink: list[AgentEvent] = []


def make_event(
    kind: str,
    fields: Mapping[str, Any],
    run_id: str,
    thread_id: str,
    step_id: str | None = None,
    agent: str | None = None,
) -> AgentEvent:
    """Build one validated event with the shared fields filled in.

    ``fields`` carries the payload fields for that kind (plan section 2.1).
    Unknown shapes raise ``ValidationError`` here, at the sender, instead
    of producing a broken event downstream.
    """
    data: dict[str, Any] = {
        "kind": kind,
        "run_id": run_id,
        "thread_id": thread_id,
        "ts": time.time(),
        "step_id": step_id,
        "agent": agent,
        **fields,
    }
    return parse_event(data)


def emit(event: AgentEvent) -> None:
    """Send one event.

    Inside a graph run the event goes to the LangGraph custom stream, where
    the runner's mapper turns it back into a typed event. Outside a run it
    goes to the in-memory sink (``drain_events``).

    Does NOT catch LangGraph control-flow exceptions (``GraphInterrupt``,
    ``GraphBubbleUp``); only the expected "no writer outside a run" case is
    handled.
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # get_stream_writer raises RuntimeError when called outside a
        # runnable context; that is the only case handled here.
        _sink.append(event)
        return
    writer(event.model_dump())


def drain_events() -> list[AgentEvent]:
    """Return the sink's collected events and empty it."""
    collected = list(_sink)  # copy out before clearing
    _sink.clear()
    return collected

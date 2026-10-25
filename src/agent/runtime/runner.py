"""Thin consumer of a compiled graph's stream.

Runs the graph and yields typed events (plan section 2.1); no UI code and
no business logic lives here. The caller supplies ``run_id``/``thread_id``
(so a follow-up task in the same thread simply gets a new ``run_id``) and
owns what to do with the yielded events.

Failure behavior:
- ordinary exceptions: one ``error`` (``fatal``) event is yielded, then the
  exception is re-raised so the caller still sees the real failure;
- LangGraph control-flow exceptions (``GraphInterrupt`` and its base
  ``GraphBubbleUp``) pass through untouched;
- ``asyncio.CancelledError`` is a ``BaseException`` and passes through too,
  so cancelling the consuming task ends the stream cleanly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamMode

from agent.events.emit import make_event
from agent.events.mapper import map_stream_part
from agent.events.models import AgentEvent

# Stream setup verified against the installed LangGraph (v1.2.16): with
# version="v2" each part is a dict-like value with keys type / ns / data.
STREAM_MODES: list[StreamMode] = ["custom", "updates", "messages"]
VERSION: Literal["v2"] = "v2"

# The graph parameter values are not needed here; any compiled state graph
# can be streamed. (GraphInterrupt is a subclass of GraphBubbleUp.)
AnyGraph = CompiledStateGraph[Any, Any, Any, Any]


async def run_graph_stream(
    graph: AnyGraph,
    graph_input: Any,
    run_id: str,
    thread_id: str,
    config: RunnableConfig | None = None,
) -> AsyncIterator[AgentEvent]:
    """Yield typed events while the graph runs.

    ``graph_input`` is the initial state dict, or a ``Command`` for resuming
    an interrupted run. ``config`` may carry extra LangGraph settings; by
    default the thread_id is passed so checkpointer-backed graphs can resume.
    """
    stream_config: RunnableConfig = config or {
        "configurable": {"thread_id": thread_id}
    }
    # Interrupt ids already reported in this run; LangGraph re-announces
    # still-pending interrupts after a resume, and repeats must not reach
    # the consumer twice.
    seen_interrupt_ids: set[str] = set()
    try:
        async for part in graph.astream(
            graph_input,
            config=stream_config,
            stream_mode=STREAM_MODES,
            subgraphs=True,
            version=VERSION,
        ):
            for event in map_stream_part(
                part, run_id, thread_id, seen_interrupt_ids
            ):
                yield event
    except GraphBubbleUp:
        # GraphInterrupt is a subclass; control flow belongs to LangGraph.
        raise
    except Exception as exc:
        yield make_event(
            "error",
            {"error_kind": "fatal", "message": str(exc)},
            run_id,
            thread_id,
        )
        raise

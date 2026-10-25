"""Runner tests with small temporary graphs (no real nodes or LLMs).

These graphs use LangGraph's in-memory checkpointer so interrupt/resume can
be exercised; it is test scaffolding only, not an extra persistence layer.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from agent.events.emit import emit, make_event
from agent.events.models import (
    AgentEvent,
    ErrorEvent,
    InterruptRequested,
    LogEvent,
    NodeEntered,
    TextDelta,
)
from agent.runtime.runner import run_graph_stream
from tests.fakes import ScriptedChatModel

RUN = "run-1"
THREAD = "thread-1"


class RunnerState(TypedDict):
    count: int


async def collect_events(stream: Any) -> list[AgentEvent]:
    return [event async for event in stream]


def _two_node_graph() -> CompiledStateGraph:
    def node_a(state: RunnerState) -> RunnerState:
        emit(make_event("node_entered", {"node": "a", "name": "a"}, RUN, THREAD))
        emit(make_event("log", {"level": "info", "message": "a ran"}, RUN, THREAD))
        return {"count": state["count"] + 1}

    def node_b(state: RunnerState) -> RunnerState:
        emit(make_event("node_entered", {"node": "b", "name": "b"}, RUN, THREAD))
        emit(make_event("log", {"level": "info", "message": "b ran"}, RUN, THREAD))
        return {"count": state["count"] + 10}

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    return graph.compile()


async def test_two_node_graph_emits_events_in_order() -> None:
    events = [
        event
        async for event in run_graph_stream(
            _two_node_graph(), {"count": 0}, RUN, THREAD
        )
    ]

    assert [e.kind for e in events] == [
        "node_entered",
        "log",
        "node_entered",
        "log",
    ]
    logs = [e for e in events if isinstance(e, LogEvent)]
    assert [e.message for e in logs] == ["a ran", "b ran"]
    entered = [e for e in events if isinstance(e, NodeEntered)]
    assert [e.node for e in entered] == ["a", "b"]
    # every event carries the run/thread metadata the runner was given
    assert all(e.run_id == RUN and e.thread_id == THREAD for e in events)


async def test_nested_graph_events_keep_their_namespace() -> None:
    class ChildState(TypedDict):
        pass

    def kid(state: ChildState) -> ChildState:
        emit(make_event("log", {"level": "info", "message": "from the child"}, RUN, THREAD))
        return {}

    child: StateGraph = StateGraph(ChildState)
    child.add_node("kid", kid)
    child.add_edge(START, "kid")
    child.add_edge("kid", END)

    parent: StateGraph = StateGraph(RunnerState)
    parent.add_node("child_graph", child.compile())
    parent.add_edge(START, "child_graph")
    parent.add_edge("child_graph", END)

    events = [
        event
        async for event in run_graph_stream(
            parent.compile(), {"count": 0}, RUN, THREAD
        )
    ]

    logs = [e for e in events if isinstance(e, LogEvent)]
    assert [e.message for e in logs] == ["from the child"]
    # the node did not name a subagent, so the namespace label records the
    # nested path (node names without LangGraph's task-id suffixes)
    assert logs[0].agent is not None
    assert logs[0].agent.startswith("child_graph")


async def test_model_text_streams_as_text_delta_events() -> None:
    def chat_node(state: RunnerState) -> RunnerState:
        model = ScriptedChatModel(responses=[AIMessage(content="hello there")])
        model.invoke([HumanMessage(content="hi")])
        return {"count": state["count"] + 1}

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("chat", chat_node)
    graph.add_edge(START, "chat")
    graph.add_edge("chat", END)

    events = [
        event
        async for event in run_graph_stream(
            graph.compile(), {"count": 0}, RUN, THREAD
        )
    ]

    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert "".join(d.text for d in deltas) == "hello there"


def _gate_graph() -> CompiledStateGraph:
    """Two gates that interrupt in the same superstep."""

    def gate_a(state: RunnerState) -> RunnerState:
        return {"count": interrupt({"gate": "H3", "interrupt_kind": "tool", "which": "a"})}

    def gate_b(state: RunnerState) -> RunnerState:
        return {
            "count": interrupt(
                {"gate": "H2", "interrupt_kind": "blocker", "which": "b"}
            )
        }

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("gate_a", gate_a)
    graph.add_node("gate_b", gate_b)
    graph.add_edge(START, "gate_a")
    graph.add_edge(START, "gate_b")
    graph.add_edge("gate_a", END)
    graph.add_edge("gate_b", END)
    # in-memory checkpointer: a test double for Phase 8's Postgres checkpointer
    return graph.compile(checkpointer=InMemorySaver())


async def test_interrupt_events_keep_ids_and_are_not_duplicated_on_resume() -> None:
    graph = _gate_graph()
    config = {"configurable": {"thread_id": THREAD}}

    requests: list[InterruptRequested] = []
    async for event in run_graph_stream(graph, {"count": 0}, RUN, THREAD, config):
        if isinstance(event, InterruptRequested):
            requests.append(event)

    # parallel node order is not fixed, so identify the gates by payload
    assert len(requests) == 2
    by_which = {e.payload["which"]: e for e in requests}
    assert by_which["a"].gate == "H3" and by_which["a"].interrupt_kind == "tool"
    assert by_which["b"].gate == "H2" and by_which["b"].interrupt_kind == "blocker"

    # resume gate_a; gate_b stays pending and LangGraph re-announces it -
    # the seen-set must suppress that duplicate
    resumed = await collect_events(
        run_graph_stream(
            graph,
            Command(resume={by_which["a"].interrupt_id: 42}),
            RUN,
            THREAD,
            config,
        )
    )
    still_pending = [e for e in resumed if isinstance(e, InterruptRequested)]
    assert [e.interrupt_id for e in still_pending] == [
        by_which["b"].interrupt_id
    ]


def _broken_graph() -> CompiledStateGraph:
    def broken(state: RunnerState) -> RunnerState:
        raise ValueError("tool exploded")

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("broken", broken)
    graph.add_edge(START, "broken")
    graph.add_edge("broken", END)
    return graph.compile()


async def test_ordinary_node_failure_is_reported_and_re_raised() -> None:
    graph = _broken_graph()

    events: list[AgentEvent] = []
    with pytest.raises(ValueError, match="tool exploded"):
        async for event in run_graph_stream(graph, {"count": 0}, RUN, THREAD):
            events.append(event)

    errors = [e for e in events if isinstance(e, ErrorEvent)]
    # one fatal error event was yielded before the exception re-raised
    assert [e.error_kind for e in errors] == ["fatal"]
    assert "tool exploded" in errors[0].message
    assert errors[0].run_id == RUN and errors[0].thread_id == THREAD


async def test_control_flow_exceptions_propagate_untouched() -> None:
    def gate(state: RunnerState) -> RunnerState:
        raise GraphBubbleUp("control flow")

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("gate", gate)
    graph.add_edge(START, "gate")
    graph.add_edge("gate", END)

    with pytest.raises(GraphBubbleUp, match="control flow"):
        async for _ in run_graph_stream(
            graph.compile(), {"count": 0}, RUN, THREAD
        ):
            pass


async def test_cancellation_ends_the_stream_cleanly() -> None:
    async def slow_node(state: RunnerState) -> RunnerState:
        emit(make_event("log", {"level": "info", "message": "slow work"}, RUN, THREAD))
        await asyncio.sleep(30)
        return {"count": state["count"] + 1}

    graph: StateGraph = StateGraph(RunnerState)
    graph.add_node("slow", slow_node)
    graph.add_edge(START, "slow")
    graph.add_edge("slow", END)

    task = asyncio.ensure_future(
        collect_events(run_graph_stream(graph.compile(), {"count": 0}, RUN, THREAD))
    )
    await asyncio.sleep(0.2)  # let the first events arrive
    task.cancel()

    results = await asyncio.gather(task, return_exceptions=True)
    # cancellation propagates; it is not swallowed or turned into an event
    assert isinstance(results[0], asyncio.CancelledError)

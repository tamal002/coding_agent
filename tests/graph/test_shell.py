"""Tests for the Phase-4 shell graph (one placeholder node, no real LLMs).

Two things matter here:

1. The shell emits the events the interfaces show (node_entered, text
   deltas from the streamed model reply, run_finished with a summary).
2. Node-emitted events carry the exact run/thread ids the caller passed
   to the runner (via the runner's LangGraph config metadata).
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent.events.models import NodeEntered, RunFinished, TextDelta
from agent.graph import build_graph
from agent.llm import provider
from agent.runtime.runner import run_graph_stream
from tests.fakes import ScriptedChatModel

RUN = "run-shell-1"
THREAD = "thread-shell-1"


@pytest.fixture
def scripted_model(monkeypatch: pytest.MonkeyPatch):
    """Route get_model() to the scripted fake; clear the factory afterwards."""

    def factory(role: Any) -> ScriptedChatModel:
        return ScriptedChatModel(
            responses=[AIMessage(content="hello from the shell")]
        )

    provider.set_model_factory(factory)
    yield factory
    provider.set_model_factory(None)


async def test_shell_streams_reply_and_finishes(scripted_model) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph()
    events = [
        event async for event in run_graph_stream(graph, {"task": "say hi"}, RUN, THREAD)
    ]

    assert [event.kind for event in events] == [
        "node_entered",
        "text_delta",
        "run_finished",
    ]

    entered = events[0]
    assert isinstance(entered, NodeEntered)
    assert entered.node == "N0_respond"

    delta = events[1]
    assert isinstance(delta, TextDelta)
    assert delta.text == "hello from the shell"

    finished = events[2]
    assert isinstance(finished, RunFinished)
    assert finished.status == "done"
    assert finished.summary == "hello from the shell"
    assert finished.changed_files == []


async def test_shell_events_carry_the_run_identity(scripted_model) -> None:  # type: ignore[no-untyped-def]
    """Placeholder node events are stamped with the caller's run/thread ids."""
    graph = build_graph()
    events = [
        event async for event in run_graph_stream(graph, {"task": "hi"}, RUN, THREAD)
    ]

    for event in events:
        assert event.run_id == RUN, f"{event.kind} lost the run id"
        assert event.thread_id == THREAD, f"{event.kind} lost the thread id"

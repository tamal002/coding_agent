"""The Phase-4 temporary graph shell: one placeholder "respond" node.

This is NOT the final agent workflow (the HLD N1..N12 graph arrives in
later phases). It exists to prove the whole path — user input, graph run,
typed events, any interface — with the smallest possible node.

The node streams the configured model's answer (its text flows to the
consumer as ``text_delta`` events through the ``messages`` stream mode)
and finishes the run with a ``run_finished`` event. Later phases replace
the node body; the START -> node -> END shape stays.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.events.emit import current_run_identity, emit, make_event
from agent.llm.provider import get_model


class ShellState(TypedDict):
    """What the temporary shell carries: the user's task text."""

    task: str


# The runner accepts any compiled state graph; the shell is one of them.
AnyGraph = CompiledStateGraph[Any, Any, Any, Any]


# The temporary shell: START -> respond -> END, compiled once per run.
def build_graph() -> AnyGraph:
    """Compile the temporary one-node graph shell."""

    async def respond(state: ShellState) -> dict[str, str]:
        """Placeholder Phase-4 node: stream an answer for the task.

        The configured model's streamed text is captured automatically by
        the runner's ``messages`` stream mode; collected here so the
        ``run_finished`` event can carry a summary.
        """
        run_id, thread_id = current_run_identity()
        model = get_model(None)
        emit(
            make_event(
                "node_entered",
                {"node": "N0_respond", "name": "N0_respond (phase-4 placeholder)"},
                run_id or "unknown",
                thread_id or "unknown",
            )
        )
        reply = ""
        async for chunk in model.astream([HumanMessage(content=state["task"])]):
            text = str(getattr(chunk, "content", ""))
            if text:
                reply += text
        emit(
            make_event(
                "run_finished",
                {"status": "done", "changed_files": [], "summary": reply},
                run_id or "unknown",
                thread_id or "unknown",
            )
        )
        return {"task": state["task"]}

    graph: StateGraph[ShellState] = StateGraph(ShellState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()

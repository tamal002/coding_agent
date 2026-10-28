"""Tests for the plain renderer's Claude-Code-style lines.

Tool and patch events have no phase wiring yet, so the formatter is
tested directly instead of through a run.
"""

from __future__ import annotations

from agent.events.models import (
    NodeEntered,
    PatchApplied,
    PatchProposed,
    PatchRejected,
    ToolFinished,
    ToolStarted,
)
from agent.ui.plain import format_plain


def _base_fields() -> dict[str, str]:
    """The shared EventBase fields every test event needs."""
    return {"run_id": "r1", "thread_id": "t1"}


def test_node_entered_renders_as_an_action_bullet() -> None:
    event = NodeEntered(node="N1_plan", name="plan", **_base_fields())
    assert format_plain(event) == "⏺ planning"


def test_tool_started_shows_verb_and_target() -> None:
    event = ToolStarted(
        tool="read_file", call_id="c1", args={"file_path": "src/agent/graph.py"},
        **_base_fields(),
    )
    assert format_plain(event) == "⏺ reading src/agent/graph.py"


def test_tool_started_without_target_args_renders_verb_only() -> None:
    event = ToolStarted(tool="bash", call_id="c2", args={}, **_base_fields())
    assert format_plain(event) == "⏺ running bash"


def test_tool_finished_renders_a_subordinate_result_line() -> None:
    event = ToolFinished(
        tool="read_file", call_id="c1", ok=True, duration_ms=12,
        output_preview="...", **_base_fields(),
    )
    assert format_plain(event) == "⎿ done · 12ms"


def test_failed_tool_finished_says_failed() -> None:
    event = ToolFinished(
        tool="bash", call_id="c3", ok=False, duration_ms=40,
        output_preview="", **_base_fields(),
    )
    assert format_plain(event) == "⎿ failed · 40ms"


def test_patch_events_render_as_edit_cards() -> None:
    fields = _base_fields()
    proposed = PatchProposed(patch_id="p1", path="a.py", diff="", **fields)
    applied = PatchApplied(patch_id="p1", path="a.py", **fields)
    rejected = PatchRejected(patch_id="p1", path="a.py", reason="no", **fields)

    assert format_plain(proposed) == "⏺ editing a.py"
    assert format_plain(applied) == "⎿ applied a.py"
    assert format_plain(rejected) == "⎿ rejected a.py (no)"

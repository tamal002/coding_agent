"""The plain terminal session: no Textual, only stdin and stdout.

`agent` (no sub-command) prints the calm banner and reads task lines in
a loop; each accepted line runs the shared graph stream and prints the
typed events as plain lines (renderer in plain.py). `agent run TASK`
(cli.py) reuses the same streaming helpers for a one-shot run.

Deliberately linear and calm: monochrome output, one prompt at a time,
a run finishes before the next prompt is read (nothing to queue).
Ctrl+C ends the current process cleanly.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agent.events.models import AgentEvent, TextDelta, ThinkingDelta
from agent.infra.ids import new_run_id, new_thread_id
from agent.modelconfig.resolver import resolve_model
from agent.ui.plain import format_plain

_PROMPT = "> "
_EXIT_WORDS = frozenset({"exit", "quit", "/exit", "/quit"})


# --- shared printing helpers (used by the session and by `agent run`) --------


def print_header(project: Path | None, persist: bool, json_mode: bool) -> None:
    """One compact head line: model, project, execution mode.

    JSON mode must stay valid JSON Lines, so the header goes to stderr
    there; plain mode prints it on stdout.
    """
    try:
        model_id = resolve_model(None).model_id
    except Exception:
        model_id = "(unselected)"  # the probe already gated real runs
    project_label = str(project) if project else "(no project set)"
    mode_label = "persistent" if persist else "ephemeral"
    line = f"model: {model_id}   project: {project_label}   mode: {mode_label}"
    if json_mode:
        print(line, file=sys.stderr)  # stdout must stay valid JSON Lines
    else:
        print(line)


def _print_plain(event: AgentEvent) -> None:
    """Print one line event in readable form (deltas stream inline)."""
    line = format_plain(event)
    if line is not None:
        print(line)


async def _stream_events(task: str, json_mode: bool) -> None:
    """Consume the shell graph's shared event stream, printing as events come."""
    from agent.graph import build_graph
    from agent.runtime.runner import run_graph_stream

    graph = build_graph()
    stream = run_graph_stream(
        graph, {"task": task}, new_run_id(), new_thread_id("run")
    )
    deltas_in_flight = False  # a streaming answer line may still be open
    async for event in stream:
        if json_mode:
            print(json.dumps(event.model_dump()), flush=True)
            continue
        if isinstance(event, (TextDelta, ThinkingDelta)):
            print(event.text, end="", flush=True)
            deltas_in_flight = True
            continue
        if deltas_in_flight:  # close the answer's line before a status line
            print()
            deltas_in_flight = False
        _print_plain(event)
    if deltas_in_flight:
        print()


def stream_task(task: str, json_mode: bool) -> None:
    """Run one task and print its events synchronously (used by `agent run`)."""
    asyncio.run(_stream_events(task, json_mode))


# --- interactive session ------------------------------------------------------


def banner(project: Path | None, persist: bool) -> str:
    """The calm, monochrome start-of-session banner."""
    width = 34

    def row(content: str) -> str:
        return "│ " + content + " " * (width - len(content) - 1) + "│"

    try:
        model_id = resolve_model(None).model_id
    except Exception:
        model_id = "(unselected)"  # the probe already gated real runs
    project_label = str(project) if project else "none set"
    mode_label = "persistent" if persist else "ephemeral"
    return "\n".join(
        [
            "╭" + "─" * width + "╮",
            row("◆ agent"),
            row("a calm local coding agent"),
            "╰" + "─" * width + "╯",
            "",
            f"  model: {model_id}   project: {project_label}   mode: {mode_label}",
            "  ctrl+c cancels the session · type exit to leave",
        ]
    )


async def _session(project: Path | None) -> None:
    """Read task lines until the user exits; each line runs the shared stream."""
    while True:
        try:
            line = await asyncio.to_thread(input, _PROMPT)
        except EOFError:
            break
        task = line.strip()
        if task.lower() in _EXIT_WORDS:
            break
        if not task:
            continue
        print()  # clear separation between the typed line and the output
        await _stream_events(task, json_mode=False)
        print()


def run_terminal(project: Path | None, persist: bool) -> None:
    """Entry point used by the CLI root command (`agent` with no sub-command)."""
    print(banner(project, persist))
    print()
    try:
        asyncio.run(_session(project))
    except KeyboardInterrupt:
        pass
    print("session ended.")

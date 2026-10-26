"""The only test allowed to touch the network: one short real Ollama call.

Skipped unless you ask for it on purpose:

    AGENT_LIVE=1 uv run pytest -m live

Requires a selected model (`agent model use` writes model_config.json) and
a running Ollama server.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage

from agent.config import ConfigError
from agent.llm import get_model
from agent.llm.usage import UsageTracker
from agent.modelconfig.resolver import resolve_model

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("AGENT_LIVE") != "1",
        reason="network test; opt in with AGENT_LIVE=1 and a running Ollama",
    ),
]


def test_live_invoke_and_usage() -> None:
    """One short real exchange against the local Ollama server."""
    resolved = resolve_model(None)  # raises ConfigError if nothing is selected
    model = get_model(None)
    tracker = UsageTracker()

    reply = model.invoke(
        [HumanMessage(content="Reply with the single word: pong")],
        config={"metadata": {"model": resolved.model_id}},
    )
    tracker.record_from_message(reply)
    assert "pong" in reply.content.lower()
    assert tracker.total_tokens > 0
    assert "$0.00 (local)" in tracker.display()


def test_live_stream_is_one_turn() -> None:
    """Streaming yields at least one chunk before finishing."""
    model = get_model(None)
    chunks: list[str] = []
    for chunk in model.stream([HumanMessage(content="Say: ok")]):
        chunks.append(str(chunk.content))
    assert len(chunks) >= 1
    assert "".join(chunks).strip() != ""


def test_live_missing_model_is_loud() -> None:
    """With no selection in model_config.json, the door refuses to guess."""
    if _model_is_selected():
        pytest.skip("a model is selected, so the loud-refusal path cannot be tested")
    with pytest.raises(ConfigError):
        resolve_model(None)


def _model_is_selected() -> bool:
    try:
        resolve_model(None)
    except ConfigError:
        return False
    return True

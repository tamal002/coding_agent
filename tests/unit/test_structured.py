"""Tests for structured output: format fallback, repair, and final refusal.

Every scenario uses ``ScriptedChatModel`` - no test here touches the network.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent.llm import StructuredOutputError, structured_invoke
from tests.fakes import ScriptedChatModel


class Reply(BaseModel):
    """A minimal project-style schema for the tests."""

    answer: str


MESSAGES = [HumanMessage(content="what color?")]


async def test_json_schema_path_returns_validated() -> None:
    model = ScriptedChatModel(
        responses=[AIMessage(content='{"answer": "blue"}')],
        methods=("json_schema",),
    )
    result = await structured_invoke(model, Reply, MESSAGES, role="plan")
    assert isinstance(result, Reply)
    assert result.answer == "blue"
    assert model.call_index == 1


async def test_falls_back_to_function_calling() -> None:
    """Model rejects json_schema binding -> the tool-calling format is used."""
    model = ScriptedChatModel(
        responses=[AIMessage(content='{"answer": "green"}')],
        methods=("function_calling",),
    )
    result = await structured_invoke(model, Reply, MESSAGES)
    assert isinstance(result, Reply)
    assert result.answer == "green"
    assert model.call_index == 1


async def test_one_repair_call_succeeds() -> None:
    """First reply invalid -> one plain repair call -> valid reply."""
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="not json at all"),
            AIMessage(content='{"answer": "fixed"}'),
        ]
    )
    result = await structured_invoke(model, Reply, MESSAGES)
    assert result.answer == "fixed"
    assert model.call_index == 2  # original + repair, never a third


async def test_repair_handles_markdown_fences() -> None:
    """A reply wrapped in ```json fences still parses."""
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="garbage"),
            AIMessage(content='```json\n{"answer": "unfenced"}\n```'),
        ]
    )
    result = await structured_invoke(model, Reply, MESSAGES)
    assert result.answer == "unfenced"


async def test_both_methods_rejected_raises_typed_error() -> None:
    """No structured format supported at all -> StructuredOutputError."""
    model = ScriptedChatModel(responses=[], methods=())
    with pytest.raises(StructuredOutputError) as exc:
        await structured_invoke(model, Reply, MESSAGES, role="code")
    assert "code" in str(exc.value)
    assert model.call_index == 0  # refusal happens at binding, no calls made


async def test_failed_repair_raises_typed_error() -> None:
    """Original + one repair both invalid -> give up with the typed error."""
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="bad one"),
            AIMessage(content="bad two"),
        ]
    )
    with pytest.raises(StructuredOutputError) as exc:
        await structured_invoke(model, Reply, MESSAGES)
    assert "repair" in str(exc.value)
    assert model.call_index == 2  # proves there is no retry loop

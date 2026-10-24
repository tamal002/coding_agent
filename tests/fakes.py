"""Fake chat model for tests.

``ScriptedChatModel`` returns pre-written AI messages, one per call, in order.
No test that uses it needs Ollama or the network.

What it supports (everything later phases need):

- ``.invoke(messages)``  -> the next scripted message
- ``.bind_tools(...)``   -> returns the model itself (no-op)
- ``.with_structured_output(schema, method=...)`` -> a wrapper that parses the
  next scripted JSON text into the schema (real validation)
- ``.stream(messages)``  -> yields the whole reply text as one chunk
- fixed ``usage_metadata`` on every scripted reply, so usage sums can be tested
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# The structured-output methods this fake pretends to support. Tests narrow
# this tuple to simulate models that reject one of the formats.
SUPPORTED_METHODS: tuple[str, ...] = ("json_schema", "function_calling")

# Fixed token counts for every scripted reply usage test.
FAKE_USAGE: dict[str, int] = {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20}


class ScriptedChatModel(BaseChatModel):
    """A chat model whose replies come from a script, in order."""

    responses: list[AIMessage]
    # Any method in here is accepted by with_structured_output; the rest raise.
    methods: tuple[str, ...] = SUPPORTED_METHODS
    call_index: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def take_next(self) -> AIMessage:
        """Return the next scripted reply and advance the counter.

        Raises ``AssertionError`` when the model is called more times than
        the test scripted replies, so tests fail loudly instead of looping.
        """
        if self.call_index >= len(self.responses):
            raise AssertionError(
                "scripted model ran out of replies: the test made "
                f"{self.call_index + 1} calls but scripted {len(self.responses)}"
            )
        reply = self.responses[self.call_index]
        self.call_index += 1
        return reply

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Ignore input messages; replies are scripted, not computed.
        return ChatResult(generations=[ChatGeneration(message=self.take_next())])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self.take_next()
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(content=reply.content, usage_metadata=FAKE_USAGE)
        )
        if run_manager is not None:
            run_manager.on_llm_new_token(str(reply.content), chunk=chunk)
        yield chunk

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        # The fake ignores tools but keeps the conversation going.
        return self

    def with_structured_output(
        self, schema: Any, *, method: str | None = None, **kwargs: Any
    ) -> _ScriptedStructuredWrapper:
        if method is not None and method not in self.methods:
            raise ValueError(
                f"structured output method {method!r} is not supported "
                f"(supported: {self.methods})"
            )
        return _ScriptedStructuredWrapper(self, schema)


class _ScriptedStructuredWrapper:
    """The object ``with_structured_output`` hands back.

    Mirrors what a real model does: parse the reply into the given pydantic
    schema, and raise when the reply is not valid for that schema.
    """

    def __init__(self, scripted: ScriptedChatModel, schema: Any) -> None:
        self._scripted = scripted
        self._schema = schema

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        reply = self._scripted.take_next()
        # Validate exactly like a real structured output would.
        return self._schema.model_validate_json(reply.content)

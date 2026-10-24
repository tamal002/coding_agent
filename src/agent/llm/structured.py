"""Ask a model for schema-validated JSON output, with one honest retry.

The ladder (one rung each, never a loop):

1. Native JSON schema format (``method="json_schema"``)
2. Tool-calling format (``method="function_calling"``), for models that
   reject the first one
3. One repair call: the plain model is asked again with the validation
   error and the schema, and told to reply with corrected JSON only
4. If the repair also fails, raise ``StructuredOutputError`` - the agent
   surfaces the failure instead of burning more tokens.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

# A project schema (record, plan, patch report...). Always a pydantic class.
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputError(Exception):
    """The model could not produce schema-valid output, even after one repair."""

    def __init__(self, schema_name: str, details: str) -> None:
        self.schema_name = schema_name
        self.details = details
        super().__init__(
            f"Could not produce valid {schema_name} output: {details}"
        )


async def structured_invoke(
    model: BaseChatModel,
    schema: type[SchemaT],
    messages: list[BaseMessage],
    role: str | None = None,
) -> SchemaT:
    """Send ``messages`` and return the reply validated against ``schema``.

    ``role`` (plan / code / summarize) only names the caller in the error
    text; it does not change the base model here - pass a different model
    object if you need a different role.
    """
    bound = _bind_with_fallback(model, schema, role)
    try:
        # A real structured runnable either returns a validated schema
        # instance or raises; neither case is the caller's problem.
        result = await bound.ainvoke(messages)
        return cast(SchemaT, result)
    except Exception as first_error:
        return await _repair(model, schema, messages, first_error, role)


def _bind_with_fallback(
    model: BaseChatModel,
    schema: type[BaseModel],
    role: str | None,
) -> Any:
    """Attach structured output to the model: json_schema first, then tool format."""
    role_name = role or "general"
    json_schema_error: Exception
    try:
        return model.with_structured_output(schema, method="json_schema")
    except Exception as error:
        # Some Ollama models do not support the native format yet.
        json_schema_error = error
    try:
        return model.with_structured_output(schema, method="function_calling")
    except Exception as function_calling_error:
        raise StructuredOutputError(
            schema.__name__,
            f"role {role_name!r}: the model supports neither structured output "
            f"format (json_schema: {json_schema_error}, "
            f"function_calling: {function_calling_error})",
        ) from function_calling_error


async def _repair(
    model: BaseChatModel,
    schema: type[SchemaT],
    messages: list[BaseMessage],
    first_error: Exception,
    role: str | None,
) -> SchemaT:
    """One plain call asking the model to fix its invalid reply; then fail."""
    role_name = role or "general"
    repair_request = HumanMessage(
        content=(
            "Your reply was not valid for this task.\n"
            f"Validation error: {first_error}\n"
            f"Reply with JSON matching exactly this schema:\n"
            f"{json.dumps(_schema_shape(schema))}\n"
            "Rules: reply with the JSON object only, no explanations, "
            "no markdown fences."
        )
    )
    reply = await model.ainvoke([*messages, repair_request])
    try:
        return schema.model_validate_json(_extract_json(_reply_text(reply)))
    except (json.JSONDecodeError, ValidationError) as repair_error:
        raise StructuredOutputError(
            schema.__name__,
            f"role {role_name!r}: even the repair call failed "
            f"(first error: {first_error}; repair error: {repair_error})",
        ) from repair_error


def _schema_shape(schema: type[BaseModel]) -> dict[str, Any]:
    """A plain-JSON description of the schema for the repair prompt."""
    return schema.model_json_schema()


def _reply_text(message: Any) -> str:
    """The content of a reply, whatever string type the model returned."""
    return message.content if isinstance(message.content, str) else str(message.content)


def _extract_json(text: str) -> str:
    """Strip one markdown code fence around a JSON reply, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_line_break = stripped.find("\n")
        if first_line_break != -1:
            stripped = stripped[first_line_break + 1 :]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()

"""The one door to every chat model in the project.

Graph code and tools never import ``langchain-ollama`` directly and never
pick a model name themselves. They call ``get_model(role)``:

1. If a model factory is set (tests / future phases), that factory decides.
2. Otherwise the model is built through the unified ``init_chat_model``
   interface, and the model name itself is decided by ``config.get_model_name``
   (env -> saved role pick -> general pick -> ``ConfigError``; a name is
   never invented).

Building the model object sends no request to the server; the connection
happens on the first ``invoke`` or ``stream``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, cast

from langchain_core.language_models.chat_models import BaseChatModel

from agent import config

Roles = Literal["plan", "code", "summarize"]
# A factory swaps in a different model builder; tests use it to inject
# the scripted fake model from tests/fakes.py.
ModelFactory = Callable[[Roles | None], BaseChatModel]

# Set only through set_model_factory() below.
_factory: ModelFactory | None = None


def set_model_factory(factory: ModelFactory | None) -> None:
    """Replace (or clear) the model builder used by ``get_model``.

    Tests call this with a function returning ``ScriptedChatModel`` so no
    test needs a running Ollama. Pass ``None`` to return to the real path.
    """
    global _factory
    _factory = factory


# main entry point to get the chat model for a role (plan / code / summarize, or None = general).
def get_model(role: Roles | None = None) -> BaseChatModel:
    """Return the chat model for the role (plan / code / summarize, or None).

    Raises ``ConfigError`` when no model is selected anywhere; the error
    message always names the exact fix.
    """
    if _factory is not None:
        return _factory(role)
    return _build_model(role)


def _build_model(role: Roles | None) -> BaseChatModel:
    """Build the real model for the role through the unified interface.

    ``init_chat_model`` picks the provider class from the ``model_provider``
    string ("ollama" -> langchain-ollama, no provider import in this file).
    Today the runtime is Ollama-only, so the provider string is fixed; the
    provider-extension phase will pass the provider saved for the role.
    """
    # Imported here so only the real runtime path needs this package.
    from langchain.chat_models import init_chat_model

    settings = config.get_settings()
    model_name = config.get_model_name(role)
    # Ollama-specific kwargs (base_url, num_ctx, ...) are forwarded to
    # ChatOllama's constructor by init_chat_model.
    ollama_kwargs: dict[str, Any] = {
        "base_url": settings.ollama_base_url,
        "num_ctx": settings.ollama_num_ctx,
        "keep_alive": settings.ollama_keep_alive,
        "validate_model_on_init": settings.validate_model_on_init,
    }
    return cast(
        BaseChatModel, init_chat_model(model_name, model_provider="ollama", **ollama_kwargs)
    )

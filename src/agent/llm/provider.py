"""The one door to every chat model in the project.

Graph code and tools never import provider packages directly and never
pick a model themselves. They call ``get_model(role)``:

1. If a model factory is set (tests / future phases), that factory decides.
2. Otherwise the model is built through the unified ``init_chat_model``
   seam: ``model_config.json`` decides provider, model id, optional base
   URL and per-model params (resolved by ``agent.modelconfig.resolver``).
   Provider-specific knowledge lives in the user's saved data — this
   module's code is provider-neutral.

For keyed providers the API key comes from the OS keyring; a missing key
raises ``ConfigError`` naming the fix. A provider whose LangChain
integration package is not installed also raises ``ConfigError`` naming
the exact package to install.

Building the model object sends no request; the connection happens on the
first ``invoke`` or ``stream``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from agent.config import ConfigError
from agent.modelconfig import resolver, secrets, store

Roles = Literal["plan", "code", "summarize"]
# A factory swaps in a different model builder; tests use it to inject
# the scripted fake model from tests/fakes.py.
ModelFactory = Callable[[Roles | None], BaseChatModel]

# Set only through set_model_factory() below.
_factory: ModelFactory | None = None


def set_model_factory(factory: ModelFactory | None) -> None:
    """Replace (or clear) the model builder used by ``get_model``.

    Tests call this with a function returning ``ScriptedChatModel`` so no
    test needs a running server. Pass ``None`` to return to the real path.
    """
    global _factory
    _factory = factory


# main entry point to get the chat model for a role (plan / code / summarize, or None = general).
def get_model(role: Roles | None = None) -> BaseChatModel:
    """Return the chat model for the role (plan / code / summarize, or None).

    Raises ``ConfigError`` when no model is selected, a keyed provider has
    no API key, or the provider's integration package is missing; the error
    message always names the exact fix.
    """
    if _factory is not None:
        return _factory(role)
    return _build_model(role)


def _build_model(role: Roles | None) -> BaseChatModel:
    """Build the real model for the role through the unified interface.

    ``init_chat_model`` picks the provider class from the resolved
    ``model_provider`` string; saved params and base URL are forwarded when
    present, and keyed providers get their API key from the keyring.
    """
    # Imported here so only the real runtime path needs langchain.
    from langchain.chat_models import init_chat_model

    resolved = resolver.resolve_model(role)
    kwargs = dict(resolved.params)
    if resolved.base_url:
        kwargs["base_url"] = resolved.base_url
    if resolved.provider in store.KEY_PROVIDERS:
        api_key = secrets.get_api_key(resolved.provider)
        if not api_key:
            raise ConfigError(
                f"Provider {resolved.provider!r} needs an API key, but none is stored. "
                f"Run 'agent model add' and enter the key for {resolved.provider!r}."
            )
        kwargs["api_key"] = api_key
    try:
        # Annotated so the Any that init_chat_model's loose typing yields
        # does not leak out as the function's return value.
        model: BaseChatModel = init_chat_model(
            resolved.model_id,
            model_provider=resolved.langchain_provider,
            **kwargs,
        )
    except ImportError as exc:
        # init_chat_model names the missing package in the import error;
        # re-raise as the config door's loud, fixable failure.
        raise ConfigError(
            f"Model provider {resolved.langchain_provider!r} is not installed: {exc} "
            f"Install its integration package, e.g. "
            f"'uv add langchain-{resolved.langchain_provider}'."
        ) from exc
    return model

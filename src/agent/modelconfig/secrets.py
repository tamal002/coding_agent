"""Store API keys safely in the OS keyring (never in plain text files).

A key is looked up in this order:

1. Env var ``{PROVIDER}_API_KEY`` (e.g. ``OPENAI_API_KEY``) — wins if set
2. The OS keyring (service: ``coding-agent``, account: ``{provider}:api_key``)
"""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError

SERVICE = "coding-agent"


def key_env_var(provider: str) -> str:
    """Return the env var name for a provider's key.

    Example: "openai" → "OPENAI_API_KEY". Shown in the `agent model add`
    prompt, because env vars always win over the keyring.
    """
    return f"{provider.upper().replace('-', '_')}_API_KEY"


def _account(provider: str) -> str:
    """Return the keyring account name for a provider, e.g. "openai:api_key"."""
    return f"{provider}:api_key"


def get_api_key(provider: str) -> str | None:
    """Return the provider's API key, or ``None`` when there is none.

    Checks the env var first, then the keyring. A missing key (or an
    unusable keyring, e.g. on a headless CI box) simply returns ``None``
    — this function does not raise for a missing key.
    """
    from_env = os.environ.get(key_env_var(provider), "")
    if from_env:
        return from_env
    try:
        stored = keyring.get_password(SERVICE, _account(provider))
    except KeyringError:
        return None
    return stored or None


def set_api_key(provider: str, api_key: str) -> None:
    """Save the key for a provider in the OS keyring.

    Replacing an old key with a new one is fine. If the OS keyring itself
    fails (locked, missing), the error goes to the caller — the user must be
    told when their key was NOT saved.
    """
    keyring.set_password(SERVICE, _account(provider), api_key)


def clear_api_key(provider: str) -> None:
    """Delete the provider's keyring entry; does nothing when none exists.

    Env vars are not touched — clearing the keyring does not change what is
    already set in the shell session.
    """
    try:
        keyring.delete_password(SERVICE, _account(provider))
    except KeyringError:
        pass


def has_api_key(provider: str) -> bool:
    """Return ``True`` when the provider has a key (env var or keyring)."""
    return get_api_key(provider) is not None

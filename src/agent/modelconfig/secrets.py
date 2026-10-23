"""API-key storage in the OS keyring, with env-var precedence.

Keys are never stored in plaintext files. Precedence:

1. env var ``{PROVIDER}_API_KEY`` (session/CI override)
2. keyring entry service ``coding-agent``, account ``{provider}:api_key``
"""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError

SERVICE = "coding-agent"


def key_env_var(provider: str) -> str:
    """Return the env var name that overrides the keyring entry for a provider."""
    return f"{provider.upper().replace('-', '_')}_API_KEY"


def _account(provider: str) -> str:
    return f"{provider}:api_key"


def get_api_key(provider: str) -> str | None:
    """Return the API key for a provider (env first, then keyring), or ``None``."""
    from_env = os.environ.get(key_env_var(provider), "")
    if from_env:
        return from_env
    try:
        stored = keyring.get_password(SERVICE, _account(provider))
    except KeyringError:
        return None
    return stored or None


def set_api_key(provider: str, api_key: str) -> None:
    """Store an API key in the OS keyring."""
    keyring.set_password(SERVICE, _account(provider), api_key)


def clear_api_key(provider: str) -> None:
    """Remove a provider's keyring entry if present (env vars are untouched)."""
    try:
        keyring.delete_password(SERVICE, _account(provider))
    except KeyringError:
        pass


def has_api_key(provider: str) -> bool:
    """Return ``True`` when a key is reachable via env var or keyring."""
    return get_api_key(provider) is not None

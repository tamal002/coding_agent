import pytest

from agent.modelconfig import secrets


def test_env_var_beats_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    def fail(*args: object, **kwargs: object) -> str:
        raise AssertionError("keyring must not be called when the env var is set")

    monkeypatch.setattr(secrets.keyring, "get_password", fail)
    assert secrets.get_api_key("openai") == "env-key"


def test_env_var_name_derivation() -> None:
    assert secrets.key_env_var("openai") == "OPENAI_API_KEY"
    assert secrets.key_env_var("deep-seek") == "DEEP_SEEK_API_KEY"


def test_keyring_used_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        secrets.keyring,
        "get_password",
        lambda service, account: "ring-key" if service == "coding-agent" else None,
    )
    assert secrets.get_api_key("anthropic") == "ring-key"
    assert secrets.has_api_key("anthropic") is True


def test_set_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str | None, bool]] = []

    def fake_set(service: str, account: str, value: str) -> None:
        calls.append((service, account, value, False))

    def fake_delete(service: str, account: str) -> None:
        calls.append((service, account, None, True))

    monkeypatch.setattr(secrets.keyring, "set_password", fake_set)
    monkeypatch.setattr(secrets.keyring, "delete_password", fake_delete)

    secrets.set_api_key("deepseek", "sk-123")
    secrets.clear_api_key("deepseek")

    assert ("coding-agent", "deepseek:api_key", "sk-123", False) in calls
    assert ("coding-agent", "deepseek:api_key", None, True) in calls


def test_clear_missing_key_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    from keyring.errors import KeyringError

    def boom(service: str, account: str) -> None:
        raise KeyringError("not found")

    monkeypatch.setattr(secrets.keyring, "delete_password", boom)
    secrets.clear_api_key("openai")  # must not raise

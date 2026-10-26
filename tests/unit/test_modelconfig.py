from pathlib import Path

import pytest

from agent.config import Settings
from agent.infra import paths
from agent.modelconfig import store


@pytest.fixture()
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)


def _path(settings: Settings) -> Path:
    return paths.config_file(settings)


def test_load_missing_returns_empty(tmp_settings: Settings) -> None:
    config = store.load_config(_path(tmp_settings))
    assert config.version == 1
    assert config.providers == {}
    assert config.selection.general is None
    assert config.selection.roles == {}


def test_add_and_dedup(tmp_settings: Settings) -> None:
    config = store.empty_config()
    assert store.add_model(config, "ollama", "qwen2.5-coder:14b") is True
    assert store.add_model(config, "ollama", "qwen2.5-coder:14b") is False
    # the same id may exist under a different provider
    assert store.add_model(config, "openai", "qwen2.5-coder:14b") is True
    assert len(config.providers["ollama"].models) == 1


def test_custom_base_url_roundtrip(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "custom", "my-model", base_url="https://api.example.com/v1")
    store.save_config(config, _path(tmp_settings))
    loaded = store.load_config(_path(tmp_settings))
    assert loaded.providers["custom"].base_url == "https://api.example.com/v1"
    assert loaded.providers["custom"].models[0].id == "my-model"


def test_remove_clears_selections(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "ollama", "big")
    store.add_model(config, "ollama", "small")
    store.set_general(config, "ollama", "small")
    store.set_role(config, "plan", "ollama", "small")

    assert store.remove_model(config, "ollama", "small") is True
    assert config.selection.general is None
    assert config.selection.roles == {}
    assert [m.id for m in config.providers["ollama"].models] == ["big"]


def test_remove_last_model_drops_provider(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "openai", "gpt-4o")
    assert store.remove_model(config, "openai", "gpt-4o") is True
    assert "openai" not in config.providers


def test_remove_missing_returns_false(tmp_settings: Settings) -> None:
    config = store.empty_config()
    assert store.remove_model(config, "ollama", "nope") is False


def test_effective_inherits_general(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "ollama", "big")
    store.set_general(config, "ollama", "big")
    ref = store.effective_model(config, "code")
    assert ref is not None and ref.model_id == "big"


def test_role_override_and_unset(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "ollama", "big")
    store.add_model(config, "ollama", "small")
    store.set_general(config, "ollama", "big")
    store.set_role(config, "plan", "ollama", "small")

    ref = store.effective_model(config, "plan")
    assert ref is not None and ref.model_id == "small"

    store.unset_role(config, "plan")
    assert config.selection.roles == {}
    ref = store.effective_model(config, "plan")
    assert ref is not None and ref.model_id == "big"


def test_set_role_rejects_unknown_role(tmp_settings: Settings) -> None:
    config = store.empty_config()
    store.add_model(config, "ollama", "big")
    with pytest.raises(ValueError, match="unknown role"):
        store.set_role(config, "bogus", "ollama", "big")


def test_set_general_rejects_unsaved_model(tmp_settings: Settings) -> None:
    config = store.empty_config()
    with pytest.raises(ValueError, match="not saved"):
        store.set_general(config, "ollama", "ghost")


def test_version_guard(tmp_settings: Settings) -> None:
    path = _path(tmp_settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(store.ConfigFormatError, match="unsupported config version"):
        store.load_config(path)


def test_provider_tables_are_consistent() -> None:
    """Every wizard provider is in both tables; the mapping covers all of them."""
    assert set(store.WIZARD_PROVIDERS) == set(store.LANGCHAIN_PROVIDERS)
    assert set(store.LANGCHAIN_PROVIDERS) >= set(store.KEY_PROVIDERS)


def test_custom_provider_is_serviced_by_the_openai_gateway() -> None:
    """init_chat_model is asked for "openai" when the user saved a custom URL."""
    assert store.LANGCHAIN_PROVIDERS["custom"] == "openai"
    assert "custom" in store.KEY_PROVIDERS

# Phase Log

## Phase 1.5 — Model selection store, keyring secrets, `agent model` CLI

- Added `src/agent/modelconfig/store.py`: `model_config.json` schema (providers, models, general + role selections), atomic save/load with version guard, dedup on `(provider, model_id)`, remove cleans selections.
- Added `src/agent/modelconfig/secrets.py`: OS keyring wrapper (service `coding-agent`), env-var precedence (`{PROVIDER}_API_KEY` > keyring).
- Added `src/agent/modelconfig/resolver.py`: resolution chain env (`MODEL_{ROLE}`/`MODEL_NAME`) → role selection → general → `ConfigError` naming the fix; `ensure_runtime_provider` refuses non-Ollama until the provider-extension phase.
- Added `src/agent/cli_model.py`: interactive `agent model add/list/use/remove` (hidden key prompt, duplicate refusal, ★ general marker, ✎ override / ↳ inherits markers, key cleanup offer).
- `config.get_model_name` now delegates to the resolver; `_ROLE_TO_ENV_VAR` removed from config.
- `paths.config_file()` added.
- Tests rewritten/added: `test_modelconfig.py`, `test_secrets.py`, `test_resolver.py` (keyring mocked; no network, no real keyring in tests).
- Gate: ruff clean; mypy strict clean (21 source files); 36 tests passed.
- Smoke-tested with a temp `AGENT_DATA_DIR`: add → save → `model list` shows models, ★ general, role mapping, and the ollama-only runtime flag.

## Phase 1

- Created the project skeleton.
- Added Python 3.11.2 target.
- Added `pyproject.toml` with pinned runtime and dev dependencies.
- Added `.python-version`, `.gitignore`, `.env.example`, and local `.env`.
- Added `src/agent/config.py` with settings and empty-model error behavior.
- Added `src/agent/infra/paths.py`.
- Added minimal `src/agent/cli.py` with a placeholder `agent --help`.
- Added tests for settings defaults/overrides and path normalization.
- Added CI and pre-commit configuration.
- Verified `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` pass (14 tests passed).
- Verified `.env` is git-ignored with `git check-ignore .env`.
- Empty `MODEL_NAME` / `MODEL_PLAN` raises `ConfigError` naming the exact env var.
- Note: `pytest` is pinned to `8.4.2` because `pytest-asyncio==1.1.1` is not compatible with `pytest` 9.x yet.

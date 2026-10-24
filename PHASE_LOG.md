# Phase Log

## Later: (open questions and plan discrepancies, recorded 2026-10-24)

### Open questions

1. **Event log `runs/<run_id>.jsonl` (plan section 2.5).** Inspect the shared contracts (plan section 2.1, Phase 3 events) and determine when the append-only writer should be introduced. If the event log is required by the architecture, name its implementation phase and responsibility explicitly (candidate: the runner or `RunController` once `run_id`/thread identity exist, Phase 8/9). Prefer a small writer that consumes the existing typed events — no second event-management abstraction, no duplicate event sources.
2. **Usage event emission.** Phase 7's `agent_llm` (or the existing runtime/tool boundary that already wraps LLM calls) should emit the `usage` event using the Phase 2 `UsageTracker`. Reuse the existing implementation; do not introduce another usage-tracking layer.

### Implementation-versus-plan discrepancies (plan unchanged on purpose)

1. **Model selection precedence — intended vs. rule text.**
   - *Intended behavior (both agree):* the human is never asked to guess a model; an unresolvable selection fails loudly with the exact fix; runtime is Ollama-only today.
   - *Detail:* global rule 10 says "MODEL_NAME must be supplied by the human in .env; there is no API key". The Phase 1.5 implementation resolves env (`MODEL_{ROLE}`/`MODEL_NAME`) → `model_config.json` role/general selection → `ConfigError`, and keeps API keys in the OS keyring. Plan's own Phase 1.5 section describes this correctly.
   - *Needs:* a plan clarification of the global rule wording (optional, low priority). **No code action** — do not touch working Phase 1.5 code.
2. **Model construction — intended vs. Phase 2 text.**
   - *Intended behavior (both agree):* one door (`get_model(role)`), Ollama-only runtime, no request at construction, model name never guessed.
   - *Detail:* original Phase 2 text constructs `ChatOllama` directly; we build via `init_chat_model(model, model_provider="ollama", ...)` (user-approved in Phase 2) with the same Ollama kwargs forwarded. Behavior identical; construction interface unified for the future provider-extension phase. Already logged in the Phase 2 entry above.
   - *Needs:* optional plan-phase-2 wording note. **No code action.**
3. **Data-directory resolution — intended vs. section 2.5 text.**
   - *Intended behavior (both agree):* one default data dir per OS user, overridable by `AGENT_DATA_DIR` (tests set it to a tmp dir).
   - *Detail:* section 2.5 documents `platformdirs.user_data_dir("agent")`; the implementation uses `user_data_dir("agent", "tamal_saha_own")` plus the `AGENT_DATA_DIR` env alias. Same env override, same semantics; only the default path's app-author component differs.
   - *Needs:* optional plan-section-2.5 note. **No code action** — code wins; do not re-point the data dir to match the doc.

## Phase 2 — LLM provider layer, usage tracking, scripted fake model

- Added `src/agent/llm/provider.py`: `get_model(role)` is the only door to a chat model. If `set_model_factory(fn)` was called (tests / future DI), the factory decides; otherwise the model is built through the unified `langchain.chat_models.init_chat_model(model, model_provider="ollama", ...)` interface, with the name from `config.get_model_name` (never guessed) and Ollama kwargs (`base_url`, `num_ctx`, `keep_alive`, `validate_model_on_init`) forwarded by `init_chat_model`. Zero provider imports in our code. Constructing the model sends no request (connection happens on first call).
- Added pinned dependency `langchain==1.4.7` for `init_chat_model` (its requirements `langchain-core>=1.6.13,<2` and `langgraph>=1.2.12,<1.3` are satisfied by the existing pins). Chosen by user decision: the unified construction interface now matches what the future provider-extension phase will pass per selected provider. Direct `ChatOllama` construction is no longer used in runtime code (tests still assert it receives the right class via `init_chat_model`).
- Added `src/agent/llm/structured.py`: `structured_invoke(model, schema, messages, role)` ladder — try `json_schema` structured binding, fall back to `function_calling`, on validation failure make ONE plain repair call (validation error + schema + "JSON only" rules), then raise `StructuredOutputError`. Supports replies wrapped in markdown fences.
- Added `src/agent/llm/usage.py`: `UsageTracker` sums input/output/total tokens, tolerates missing keys, always reports `$0.00 (local)`; `display()` renders `13 in / 7 out • $0.00 (local)`.
- Added `tests/fakes.py`: `ScriptedChatModel(BaseChatModel)` returns pre-written `AIMessage`s in order (loud `AssertionError` when the script runs out), `bind_tools` no-op returns self, `with_structured_output(schema, method)` validates the scripted JSON for real, `.stream` yields the reply as one chunk, fixed `FAKE_USAGE` (`total_tokens` required by `AIMessage`).
- Added `tests/unit/test_provider.py` (factory hook routing, real ChatOllama build without network, env role fallback, `ConfigError` refusal), `test_structured.py` (json_schema path, fallback, single repair, failed repair → typed error, both-methods-rejected → typed error), `test_usage.py` (sums, missing keys, zero local cost, display).
- Added `tests/unit/test_live_ollama.py`: the only network test, `@pytest.mark.live`, skipped unless `AGENT_LIVE=1` plus a selected model and running Ollama.
- Added `config/prices.yaml` (empty placeholder for a future price table; local cost stays zero).
- `pyproject.toml`: added `[tool.pytest.ini_options]` (`testpaths`, `asyncio_mode = "auto"`, `live` marker).
- `src/agent/cli_model.py`: one over-length comment reflowed (user comment preserved, text unchanged).
- Deviation from the plan text: the plan referenced `Settings.get_model_name(role)`; the canonical implementation is the module function `config.get_model_name(role)` (fuller chain env → role pick → general → refuse, built in Phase 1.5). Same behavior the plan wanted.
- Deviation from the plan test: failed-repair path uses 2 scripted calls (original + repair), not 3 — binding attempts raise at construction and consume no scripted replies.
- Gate: ruff clean; mypy strict clean (24 source files); 53 passed + 3 skipped (live tests). Re-run green after the `init_chat_model` adoption.
- Manual smoke (scripted, no network): factory door returns the fake, plain invoke + usage meter, clean structured reply, markdown-fence repair, typed refusal after a failed repair. Temp data dir not even created when a factory is set (verified cleaned).

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

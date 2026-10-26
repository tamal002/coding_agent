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

### Open question 3 (Phase 3.5 follow-ups parked)

Keep these out of Phase 3.5, revisit later:
- Removing the `{PROVIDER}_API_KEY` env-var precedence from `secrets.py` (credentials are not
  model config; the escape hatch stays until the multi-provider phase decides).
- A wizard prompt or CLI command for per-model params (e.g. `agent model set param`) — params
  is advanced JSON-only editing in `model_config.json` for now (documented on `ModelEntry`).
- Install-on-demand for provider integration packages; Phase 3.5 only raises a `ConfigError`
  naming the exact `uv add langchain-...` fix.
- `num_ctx` awareness: without per-model params, Ollama models run at the server's default
  context (2048). Phase 7 may surface a warning or set a sane default via params.

## Phase 3.5 — `model_config.json` as the single source of truth (provider-generic runtime)

- Contract change (user-approved; plan contract edited by the user, this entry records the implementation): all model/provider settings leave `.env`; `model_config.json` is the only model configuration source. `Settings` no longer holds `provider`, `model_name`, `model_plan`/`model_code`/`model_summarize`, `ollama_base_url`/`ollama_num_ctx`/`ollama_keep_alive`/`validate_model_on_init`; `config.get_model_name` is deleted (provider calls the resolver directly). Phase-1's "empty MODEL_NAME raises ConfigError naming the env var" check is retired accordingly.
- `store.py`: `SUPPORTED_RUNTIME_PROVIDERS` deleted (no runtime refusals). Added the two generic tables: `KEY_PROVIDERS` (which providers need an API key; moved from `cli_model.py`'s `_NEEDS_KEY`) and `LANGCHAIN_PROVIDERS` (saved provider name → `model_provider` string for `init_chat_model`; `custom` maps to `openai` at its saved base URL). `ModelEntry.params` is documented as the advanced JSON-only override pocket forwarded verbatim as `init_chat_model` kwargs (wizard never asks for it).
- `resolver.py` rewritten: chain is now role selection → general selection → `ConfigError` naming only `agent model add`/`agent model use` (no `.env` wording anywhere). `ResolvedModel` now carries everything the builder needs: `provider`, `langchain_provider`, `model_id`, `base_url` (only when saved), `params`. A selection pointing at a model that is not saved (hand-edited JSON) raises `ConfigError` instead of inventing anything. `ensure_runtime_provider` deleted.
- `provider.py`: `_build_model` is provider-neutral — kwargs = saved params (+ saved `base_url` when present); keyed providers get `api_key` from the keyring (`ConfigError` naming `agent model add` when missing); a missing provider integration package surfaces as `ConfigError` naming the exact `uv add langchain-...` fix (wrapped `ImportError`, verified: `init_chat_model` raises ImportError with the package name). The Ollama kwargs block (`base_url`/`num_ctx`/`keep_alive`/`validate_model_on_init` from Settings) is gone; the `cast` is replaced by an annotated variable. Accepted consequence: without per-model params, Ollama models run at the server's default context (2048) — fixing that is a data edit (`{"num_ctx": 8192}`), never provider code.
- `cli_model.py`: uses `store.KEY_PROVIDERS`; the obsolete "(saved - runtime: ollama-only for now)" list note is removed. Wizard flow unchanged (ollama → model id only; keyed providers → key; custom → base URL + key), matching the contract.
- `.env` / `.env.example`: model and OLLAMA_* lines removed; header now says model setup is done via `agent model` commands. Stale env vars in any user's local `.env` are silently ignored by `Settings` (`extra="ignore"`).
- `Settings` stop-switch cleanup (user decision, same session): `max_total_tokens` (the iteration and wall-clock stops already bound loopy behavior, and local tokens cost nothing) and `max_parallel` (subagent fan-out is unbounded by design — the user decides how many run). Remaining stops: `max_iterations_per_step=25`, `tool_timeout_s=120`, `max_wall_minutes=60`, plus `max_cost_usd=5.0` kept for UI parity.
- Tests: `test_resolver.py` rewritten without env cases (role wins, inherit-general, resolve(None), error messages without `MODEL_NAME`, keyed/custom/provider mappings, params carried through, hand-edited JSON failure); `test_provider.py` rewritten for the generic builder (factory tests kept; real ChatOllama build from a saved selection; params forwarded to a captured `init_chat_model`; keyed provider passes `api_key`; missing key → refusal; custom → openai gateway mapping; missing integration package → ConfigError naming the package — real behavior, `langchain-openai` is not installed in this project; empty store → JSON-chain error); `test_config.py` keeps data-dir tests and asserts the model fields are gone; `test_modelconfig.py` gains provider-table consistency checks; `test_live_ollama.py` uses `resolve_model` instead of the deleted `get_model_name`.
- Gates: ruff clean; mypy strict clean (29 files); 90 passed + 3 skipped (live).
- Smoke: `uv run agent model list` shows the saved general model (★) and role inheritance; `resolve_model(None/plan/code/summarize)` against the real `model_config.json` resolves through the JSON-only chain with `.env` holding no model settings.
- Note for Phase 8: `resolve_model`/`ResolvedModel` shape (params, base_url) may be worth caching — no action taken.

## Phase 3 — Event contract, emitter, stream mapper, graph runner


- Verified the installed LangGraph (1.2.16) streaming API before coding, with throwaway experiment scripts (deleted afterwards). Confirmed behaviors that the code now relies on:
  - `graph.astream(..., stream_mode=["custom","updates","messages"], subgraphs=True, version="v2")` yields dict-like parts with keys `type`/`ns`/`data` (the typed `langgraph.types.StreamPart` union: `ValuesStreamPart | UpdatesStreamPart | MessagesStreamPart | CustomStreamPart | ...`).
  - `custom` parts carry exactly what a node sent through the stream writer; `updates` parts carry `{node_name: delta}` and, when a node interrupts, `{"__interrupt__": (Interrupt(...),)}`; `messages` parts carry `(AIMessageChunk, metadata)` tuples including trailing empty chunks.
  - Parallel gate nodes interrupting in one superstep produce separate `__interrupt__` parts; after resuming one of them, the still-pending interrupts are re-announced as fresh parts in the resumed stream, and a resumed node re-plays the custom events it emitted before `interrupt()`.
  - `get_stream_writer()` outside a runnable context raises plain `RuntimeError`. `Interrupt.id` (32-hex) is the resume key; `interrupt_id` on the object is deprecated since v1.0. `Command(resume=...)` requires a checkpointer on the compiled graph.
- Added `src/agent/events/models.py`: shared `EventBase` (extra fields forbidden) and one model class per event kind (all 19 kinds from plan section 2.1), discriminated into the `AgentEvent` union by `kind`; `parse_event()` validates dicts/models against the union. Each subclass has an explicit literal default for `kind` so direct construction is ergonomic. Two documented renames because the base `kind` field is the event's own type tag: `interrupt_requested.payload.kind` → `interrupt_kind`, `error.payload.kind` → `error_kind`. `FileRead.lines` holds the number of lines read (bounded payload; content stays in tools).
- Added `src/agent/events/emit.py`: `make_event(kind, fields, run_id, thread_id, step_id=None, agent=None)` is the single construction door (timestamp filled, validated at the sender); `emit(event)` sends to the LangGraph custom stream inside a graph run and to an in-memory test sink (`drain_events()`) outside one. Only the expected "no writer outside a run" `RuntimeError` is handled; `GraphInterrupt`/`GraphBubbleUp` are never swallowed.
- Added `src/agent/events/mapper.py`: `map_stream_part(part, run_id, thread_id, seen_interrupt_ids)` maps `custom` → validated event, `updates.__interrupt__` → `interrupt_requested` (gate/interrupt_kind read from the node's dict payload, tool-gate defaults for simple temporary payloads; deduped by `Interrupt.id` within a run, since LangGraph re-announces still-pending interrupts after a resume), `messages` → `text_delta` (empty chunks skipped). `node_entered` is emitted by the node itself through `emit()` (that is the contract's assignment), not derived from `updates` deltas which arrive only after a node completes. Typed-`Any`/unknown custom shapes become a visible `log` warning instead of being dropped silently. Non-empty `ns` is preserved as a compact `agent` label (node names without LangGraph's task-id suffixes, e.g. `child_graph`); a node-set `agent` name wins.
- Added `src/agent/runtime/runner.py`: `run_graph_stream(graph, graph_input, run_id, thread_id, config=None)` — thin async generator consuming the stream and yielding typed events; no UI and no business logic. Caller supplies run/thread identity, so a follow-up task in the same thread is just a new `run_id`. Ordinary exceptions yield one `error` (`fatal`) event and are re-raised so the caller still sees the real failure; `GraphBubbleUp` (incl. `GraphInterrupt`) and `asyncio.CancelledError` propagate untouched.
- Added `src/agent/state.py`: empty `AgentState` typed dict; fields are added by the phases that need them (plan section 2.3).
- Tests: `tests/unit/test_events.py` (all 19 kinds build + round-trip through `parse_event`; unknown kind, missing required field, wrong payload type rejected; gate/range validation; sink fill + drain; narrowing by kind) and `tests/graph/test_runner.py` with small temporary graphs (in-memory checkpointer only as a test double for resume; LangGraph does not allow `Command(resume=...)` without one): deterministic two-node per-node event order; nested subgraph events keep their namespace label; scripted-model text arrives as `text_delta` events; interrupt ids stay stable across pause/resume and are not duplicated when the still-pending gate is re-announced; ordinary failure yields the `error` event then re-raises; manually raised `GraphBubbleUp` propagates; cancelling the consuming task propagates `CancelledError` cleanly.
- Gate: ruff clean; mypy strict clean (29 source files); 86 passed + 3 skipped (live).

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

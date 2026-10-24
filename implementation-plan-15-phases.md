# Coding Agent — 15-Phase Implementation Plan (for an AI coding agent)

This file is the build contract. Read it fully once, then open the diagram `coding-agent-langgraph-no-openwiki.excalidraw` once. Both are the source of truth. Implement **exactly one phase per session**, in order.

---

## 0. Rules for the implementing agent (read first, every session)

1. **One phase per session.** Read the phase section, the "Shared contracts" section (section 2), and the diagram nodes listed for the phase. Implement only that phase. Do not start the next one.
2. **Do not build ahead.** If a later-phase feature seems useful now, add a line to `PHASE_LOG.md` under `Later:` and move on. Stubs are allowed only where a phase explicitly says "stub".
3. **Names come from the diagram.** Node IDs (`N1`–`N12`), routers (`R1`–`R9`), human gates (`H1`–`H4`), stores (`S1`–`S3`), and subagent names are fixed. Use them verbatim in file names, function names, event payloads and logs. Example: node `N3 · build_context` → `src/agent/nodes/n3_build_context.py`, function `n3_build_context`.
4. **Gate before finishing.** A phase is done only when its **Test gate** passes completely: `uv run ruff check .`, `uv run mypy src`, `uv run pytest` all green, plus the phase's manual demo.
5. **Finish protocol.** (a) Append a dated entry to `PHASE_LOG.md`: what was built, deviations, open questions. (b) Report changed files, the exact test gate results, and anything the human must do next. (c) Stop and wait for review.
6. **The human owns git and GitHub.** As the implementing agent, never run `git add`, `git commit`, `git tag`, `git push`, or any branch operation in this repository. Do not create commits or tags for a phase. The human will review the diff and handle all git/GitHub work. (The *product* still implements its own N12 branch/commit/PR behavior at runtime; that is application code, not the implementing agent acting on this repository.)
7. **Never break earlier tests.** If an old test fails, fix the code, not the test (unless the phase says the test contract changed).
8. **Stop and ask the human** when a phase says `STOP AND ASK`, or when you face a choice not covered here (for example a new dependency with a license question). Do not guess.
9. **Forbidden everywhere:** a server or HTTP API for the agent; OpenWiki, AFS, Redis, SQLite or any other database beyond Postgres; writes to the user's real git branch `main`/`master`; real network calls in tests (use fakes; live tests are marked `@pytest.mark.live` and skipped by default); printing or logging secrets; `shell=True` subprocess calls with unescaped user input.
10. **Provider is Ollama only.** All model calls go through `langchain-ollama` (`ChatOllama`) against `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`). There is no API key. `MODEL_NAME` must be supplied by the human in `.env`; never guess a model name.
11. **Keep the core headless.** Code under `src/agent/` except `src/agent/ui/` must not import `rich` or `textual`.
12. **Pin versions** in `pyproject.toml` (Phase 1). Before using any library API, read its installed docs or source (`uv run python -c "import x; help(x)"`). Do not rely on memory for library signatures. The versions and API notes in section 2.8 are the baseline for this build.

---

## 1. Overall architecture (what you are building)

A **local terminal application**. The user installs it, points it at a local **Ollama** server, runs `agent`, and gets a Claude-style TUI. The agent runs a **LangGraph** state machine (the diagram) against a **copy of the user's repo** (the workspace). It reads code through **Serena** (symbol-level understanding) and the **filesystem MCP** (files, search). It edits files with its own `edit_file` tool (so every patch is shown as a diff), runs commands through a **permission policy**, pauses at **human gates** (`interrupt()`), and persists everything in **Postgres running in Docker** (the user starts it with one command). There is no server, no wiki, no Redis and no SQLite.

Run flow: UI sends task → runner streams the graph → nodes and tools emit typed **events** → UI renders them. At a human gate the graph pauses, the pending requests enter an **approval inbox**, and the UI shows them **one at a time**. A decision resumes the **single parent thread** with `Command(resume={interrupt_id: decision})`. Parallel subagents can be interrupted at the same time, but human interaction stays serialized.

---

## 2. Shared contracts (define these once, in the phase that says so, then reuse)

### 2.1 Event (phase 3 creates it)
Base fields on every event: `kind: str`, `run_id: str`, `thread_id: str`, `ts: float`, `step_id: str | None`, `agent: str | None`.
Event kinds and payloads:

| kind | payload fields | emitted by |
|---|---|---|
| `node_entered` | `node` (e.g. `N5`), `name` | every node |
| `text_delta` | `text` | LLM nodes |
| `thinking_delta` | `text` | LLM nodes (only if the provider sends reasoning) |
| `tool_started` | `call_id`, `tool`, `args` (truncated) | tool wrapper |
| `tool_finished` | `call_id`, `tool`, `ok: bool`, `duration_ms`, `output_preview` | tool wrapper |
| `file_read` | `path`, `start`, `end`, `lines` | read tools |
| `patch_proposed` | `patch_id`, `path`, `diff` | edit tool |
| `patch_applied` | `patch_id`, `path` | edit tool |
| `patch_rejected` | `patch_id`, `path`, `reason` | edit tool / user |
| `plan_updated` | `plan` (serialized) | N4, H2 |
| `step_status` | `step_id`, `status` | N5, N7, N8 |
| `context_updated` | `tokens_used`, `tokens_window`, `refs_count`, `note` | N3, N9 |
| `interrupt_requested` | `interrupt_id`, `gate` (H1–H4), `kind` (`clarify`/`plan`/`tool`/`blocker`), `payload` | runner, from `__interrupt__` / `state.interrupts` |
| `approval_resolved` | `interrupt_id`, `gate`, `decision`, `status` (`resolved`/`rejected`/`cancelled`) | `RunController` |
| `usage` | `model`, `input_tokens`, `output_tokens`, `cost_usd` (0.0 for Ollama) | LLM wrapper |
| `retry` | `step_id`, `attempt`, `max_attempts`, `reason`, `next_action` | N10 |
| `error` | `kind` (transient/context/plan/agent/fatal/verify), `message`, `step_id` | N10, tools |
| `run_finished` | `status` (done/partial/aborted), `changed_files`, `summary` | N12 |
| `log` | `level`, `message` | any (used for debugging) |

Emission rule: nodes call `emit(event)`, which uses LangGraph's stream writer. Nodes never import UI code. UI approval requests are created from the `__interrupt__` stream chunk or `state.interrupts`, **not** by emitting inside the node before `interrupt()` (that would duplicate the request when LangGraph re-runs the node on resume).

### 2.2 Task and Plan (phase 12 creates them; `AgentState` fields are added as phases need them)
- `Task`: `text: str`, `type: Literal["feature","bugfix","refactor","docs","investigation"]`, `success_criteria: list[str]`, `ambiguity: float`, `risk: Literal["low","medium","high"]`, `rationale: str`.
- `Step`: `id: str`, `goal: str`, `agent: str` (a catalog name), `deps: list[str]`, `status: Literal["pending","running","done","failed","blocked","skipped"]`, `verify: str`, `rationale: str`.
- `Plan`: `version: int`, `steps: list[Step]`.

### 2.3 AgentState (TypedDict, LangGraph state; persisted by S1)
Fields and the phase that adds each:
- `workspace_path` — phase 5; `messages` (with `add_messages` reducer) and subagent `iteration` — phase 7
- `thread_id`, `run_id`, and resumable `status` — phase 8
- `human: HumanState` — phase 9. `HumanState = {pending_interrupt_ids: list[str], decisions: dict[str, str], feedback: str | None, last_gate: str | None}`. The checkpoint's `state.interrupts` is authoritative; `human.pending_interrupt_ids` is a cache for the UI and diagnostics, not a second queue.
- `context_refs: list[ContextRef]` and `artifact_refs: list[str]` — phase 11
- `task: Task | None` and `plan: Plan | None` — phase 12
- `ready_steps: list[str]` and `step_results: dict[str, StepResult]` (merge reducer keyed by step ID) — phase 13
- `error: ErrorInfo | None`, `attempts: dict[str, int]`, and `budget: BudgetState` — phase 14

Add state fields in the phase that first needs them. Do not duplicate checkpoint-owned state in custom tables.

The approval queue itself is **not** an `AgentState` field. It is a projection of the checkpoint's pending interrupts, owned by `RunController` (section 2.7).

### 2.4 Tool metadata (phase 5 creates the decorator; phase 10 adds the policy file)
Each tool has: `name`, `kind` (`read` | `write` | `exec` | `network`), `risk` (`safe` | `risky`), `allowed_agents: list[str]`.
Risk classification (default, from `config/policy.yaml`): read tools = safe; `edit_file`, `write_file`, `run_shell`, git push, GitHub PR creation = risky. Unknown tool = risky.

### 2.5 Workspace and paths
- Data dir: `platformdirs.user_data_dir("agent")`, overridable with env `AGENT_DATA_DIR` (tests always set it to a tmp dir).
- Workspace: `<data_dir>/workspaces/<thread_id>/` — a copy of the user's repo.
- Undo: `<workspace>/.agent/undo/<patch_id>/` holds the original file content.
- Artifacts: `<data_dir>/artifacts/<thread_id>/`.
- Runs log: `<data_dir>/runs/<run_id>.jsonl` (every event, phase 15 uses it for replay).

### 2.6 Subagent catalog (names are fixed; phase 13 implements behavior)
`code_explorer` (read), `code_editor` (write, serialized), `test_runner` (read + exec), `debugger` (read + exec), `docs_agent` (write docs only), `git_agent` (write, serialized, push = risky), `research_agent` (read-only web).

### 2.7 Approval queue and interrupt correlation (phase 9 creates it; phases 12, 13, 14, 15 reuse it)

This is the contract for all four human gates. Do not build a separate approval mechanism for each gate.

**Components**
- `RunController` — exactly one per session/thread. It is the only code allowed to call `graph.astream` for that thread. It owns the stream, the pending map, and the resume calls.
- `ApprovalInbox` — an `asyncio.Queue[ApprovalRequest]` used only to wake the TUI. It is **not** the source of truth and is never persisted as the queue.
- `ApprovalRequest` — structured UI/audit object (see fields below).
- `pending: dict[str, ApprovalRequest]` — keyed by LangGraph `Interrupt.id`, rebuilt from the checkpoint on startup and after every run.

**Hard rules**
1. **One parent thread per session.** `Send` subagents share the parent run, checkpoint, and `thread_id`. Never create a separate graph thread per subagent; that would break `Send`, N7 merging, and session resume.
2. **The checkpoint is authoritative.** Rehydrate with `await graph.aget_state(config)` and read `state.interrupts`. The TUI queue is a projection of that list.
3. **Use `Interrupt.id`, never a UI id, as the resume key.** `Command(resume={interrupt.id: decision})`. A dict whose keys are not valid xxh3 hex digests is treated by LangGraph as a plain resume value, which fails when multiple interrupts are pending. `Interrupt.interrupt_id` is deprecated; use `.id`.
4. **One writer to the run loop.** The TUI submits a decision; only `RunController` resumes. Never call `astream(Command(resume=...))` while another `astream` for the same thread is active.
5. **Interrupts arrive in superstep batches.** While the graph is paused for human review, no new interrupt can appear. After a resume, the graph re-enters the interrupted superstep, may re-interrupt the remaining tasks, and may produce new requests. The UI always processes the current pending set one item at a time.
6. **Emit the request from the interrupt, not before it.** `H#` calls `interrupt(payload, response_schema=...)` as its first statement. `RunController` maps the `__interrupt__` chunk / `state.interrupts` to `interrupt_requested`. Do not emit a request event before `interrupt()`, and do not perform side effects before it.
7. **Keep payloads compact.** The interrupt payload contains ids, tool name, a short summary, and an `artifact_id` for a full diff/command. Large content belongs in S3. Use `response_schema` so LangGraph validates the resume value.
8. **Dedupe on resume.** A resumed node restarts from the top and may replay `node_entered` / text events. Stable event IDs and dedupe by `interrupt_id` are required; the TUI must not show the same request twice.
9. **Status is separate from the graph.** `PENDING → RESOLVING → RESOLVED | REJECTED | CANCELLED | FAILED`. Submit a decision → `RESOLVING`; reconcile after the run → final state. A queue item disappearing does not mean the subagent finished.
10. **Cancellation is explicit.** Cancel a run by rejecting/aborting all pending interrupts (and recording the reason), then stopping the run. There is no silent “drop the queue” path.

**Data model**

```python
ApprovalStatus = Literal["PENDING", "RESOLVING", "RESOLVED", "REJECTED", "CANCELLED", "FAILED"]

class ApprovalRequest(BaseModel):
    request_id: str                 # UI/audit only
    interrupt_id: str               # LangGraph Interrupt.id; resume key
    thread_id: str
    gate: Literal["H1", "H2", "H3", "H4"]
    kind: Literal["clarify", "plan", "tool", "blocker"]
    step_id: str | None = None
    subagent: str | None = None
    tool_call_id: str | None = None
    tool: str | None = None
    summary: str
    args_preview: dict[str, Any] = {}
    artifact_id: str | None = None
    created_at: datetime
    status: ApprovalStatus

class ToolApprovalDecision(BaseModel):
    approved: bool
    reason: str | None = None
    edits: dict[str, Any] | None = None   # reserved for approve-with-edits
    scope: Literal["once", "session"] = "once"
```

`ToolApprovalDecision` is the H3 schema. H1/H2/H4 define their own response schemas (`ClarifyAnswer`, `PlanDecision`, `BlockerDecision`); each carries the fields its gate needs. `RunController` stores the serialized decision and passes it back unchanged in `Command(resume=...)`.

`ApprovalRequest.request_id` is for display and audit. Only `interrupt_id` may be used to resume.

**Resume call**

```python
await graph.astream(
    Command(resume={request.interrupt_id: decision.model_dump(mode="json")}),
    config={"configurable": {"thread_id": thread_id}},
    stream_mode=["custom", "updates", "messages"],
    subgraphs=True,
    version="v2",
)
```

If several interrupts are pending, resume one at a time. LangGraph re-interrupts the unresolved tasks. Batching is an optimization, not the default UI behavior.

**What the TUI does**
- Consume `ApprovalInbox` one request at a time (modal or inline prompt), showing queue position (“1 of 3”), gate, step/subagent, exact tool args, and a diff/command preview from S3.
- Buttons/keys: `y` approve, `n` reject, `a` approve for this session (same tool + args hash), `Esc` reject, `Ctrl+C` cancel the run. H1/H2/H4 use their own response schemas and labels (`answer/abort`, `approve/edit/abort`, `guidance/partial/continue/abort`) while keeping the same inbox and resume path.
- On restart, `agent resume <thread_id>` calls `aget_state`, shows any `state.interrupts` as pending approvals, and resumes from there.
- Write every decision to the audit log (`interrupt_id`, gate, decision, reason, timestamp, user).

**Tests the contract requires**
- Two parallel subagents interrupt in the same superstep → two requests, one at a time.
- Approve the first → the run re-interrupts for the second → approve the second → N7 merges both results.
- Reject one → a denial `ToolMessage` and no protected side effect.
- Restart while two approvals are pending → `aget_state().interrupts` rebuilds the queue.
- A non-hex UI id used as the resume key → a clear error, no corruption.
- Resume one interrupt, then verify the already-completed sibling does not repeat its side effect.
- Cancel while pending → all pending requests become `CANCELLED` and the run ends cleanly.
- Resume does not duplicate a modal (event dedupe by `interrupt_id`).

### 2.8 Library versions and API notes (baseline: latest compatible as of this build)

Pin these exact versions in `pyproject.toml` unless a phase explicitly upgrades one. Before coding against an API, verify it in the installed package.

| Package | Version | Notes |
|---|---|---|
| Python | 3.11.2 | use the system Python; do not install another version |
| `langgraph` | 1.2.16 | state graph, `Send`, interrupts, streaming |
| `langgraph-checkpoint-postgres` | 3.2.0 | `AsyncPostgresSaver` |
| `langchain-core` | 1.6.13 | messages, tools, `BaseChatModel` |
| `langchain-ollama` | 1.1.0 | `ChatOllama`; the only provider |
| `langchain-mcp-adapters` | 0.3.2 | `load_mcp_tools(session)` |
| `textual` | 8.2.8 | TUI |
| `rich` | 15.0.0 | plain output and widgets |
| `typer` | 0.27.3 | CLI |
| `pydantic-settings` | 2.16.1 | `Settings` |
| `serena-agent` | 2.1.0 | run via `uvx`; separate process |
| `pytest` | 8.4.2 | tests; compatible with `pytest-asyncio==1.1.1` |
| `mypy` | 2.4.0 | strict type check |

**API deltas to code against**
- `graph.astream(..., stream_mode=["custom", "updates", "messages"], subgraphs=True, version="v2")`. Each part is a `StreamPart` (`type`, `ns`, `data`), not a bare `(mode, chunk)` tuple. `subgraphs=True` is required to see nested subagent events.
- `get_stream_writer()` raises when called outside a graph run. Catch that specific failure, buffer the event for tests, and never swallow `GraphBubbleUp` / `GraphInterrupt`.
- `interrupt(payload, response_schema=...)` is the modern form. Read the returned value after resume.
- `Interrupt.id` is the resume key; `interrupt_id` is deprecated.
- `Command(resume={interrupt_id: value})` for multiple pending interrupts; resume one at a time for the TUI. Never put UI ids in that map.
- `AsyncPostgresSaver.from_conn_string(...)` is an async context manager. Keep it open with a long-lived `AsyncExitStack`; do not return a saver whose context has already closed.
- Do not use the deprecated prebuilt `tools_condition`; write the `Ra` router explicitly.
- For MCP, keep one long-lived session per server and call `load_mcp_tools(session)`. Do not call `MultiServerMCPClient.get_tools()` per turn (it opens a new session each call).
- Use `astream` v2 for one ordered TUI stream. Do not mix in `stream_events` v3 in the same runner.

---

## 3. Diagram traceability (where each diagram element is built)

| Diagram element | Built in phase |
|---|---|
| S1 Checkpointer | 8 |
| N1 load_state, R1 | 8 |
| N2 analyze_task, R2, H1 | 12 |
| N3 build_context, S2 (context sources) | 11 |
| N4 planner, R3, H2 | 12 |
| N5 dispatch_step, R4 | 13 |
| N6 subagent subgraph (Panel A: prepare_agent, agent_llm, Ra, Rb, tool_node, H3, emit_result) | 7 (loop), 9 (Rb/H3), 10 (MCP tool_node) |
| N7 observe_merge, R5 | 13 |
| N8 progress_check, R6 | 14 |
| N9 compact_context, R7 | 11 |
| N10 error_handler, R8, H4 | 14 |
| N11 verify, R9 | 14 |
| N12 finalize | 14 |
| S3 Artifact Store | 11 |
| Tool Router + MCP servers (Serena, Filesystem, Shell, Git, GitHub) | 10 |
| Subagent selection rules (Panel B) | 13 |
| Approval queue / RunController / ApprovalInbox (Panel D) | 9 (created), 12/14 (reused), 15 (polish) |
| Runtime rules (Panel: checkpoint, interrupt, Send, approval queue, limits) | 8, 9, 13, 14 |
| Legend and reference table (Panel C) | verified in phase 14 |

---

## Phase 1 — Project skeleton, configuration and tooling

**Goal:** an empty folder becomes a versioned, linted, tested project with config, paths, and all pinned dependencies. Nothing agentic yet.

**Depends on:** nothing.
**Diagram:** none (foundation).

**Create**
- `pyproject.toml` (Python 3.11.2, package `agent`, console script `agent = "agent.cli:app"`)
- `.python-version` containing `3.11.2`
- `README.md`, `PHASE_LOG.md`, `.gitignore` (must include `.env`, `workspaces/`, `__pycache__/`, `.venv/`), `.env.example`, and a local `.env` (git-ignored, never committed)
- `src/agent/__init__.py`, `src/agent/config.py`, `src/agent/infra/paths.py`, `src/agent/infra/__init__.py`
- Folder skeleton with empty `__init__.py`: `src/agent/{events,runtime,llm,nodes,routers,subagents,tools,context,memory,safety,infra,ui}/`, `tests/{unit,graph,ui,chaos}/`, `config/`, `docker/`, `migrations/`
- `.github/workflows/ci.yml` (runs ruff, mypy, pytest on push)
- `.pre-commit-config.yaml` (ruff hook)

**Implementation steps**
1. Use the system Python `3.11.2`; do not install another Python. `uv init --package --name agent --python 3.11.2` is not required; create `pyproject.toml` and `.python-version` directly.
2. Add all runtime dependencies now, pinned to the versions in section 2.8: `langgraph`, `langgraph-checkpoint-postgres`, `langchain-core`, `langchain-ollama`, `langchain-mcp-adapters`, `pydantic`, `pydantic-settings`, `platformdirs`, `keyring`, `typer`, `rich`, `textual`, `psutil`. Dev deps: `pytest`, `pytest-asyncio`, `pytest-textual-snapshot`, `ruff`, `mypy`, `pre-commit`. Import only `pydantic`, `pydantic-settings`, `platformdirs`, `typer` and `pytest` in this phase.
3. `config.py`: `class Settings(BaseSettings)` with fields:
   - `provider: Literal["ollama"] = "ollama"`
   - `model_name: str = ""` (env `MODEL_NAME`; required when a model is requested)
   - `model_plan: str = ""`, `model_code: str = ""`, `model_summarize: str = ""` (optional per-role overrides; empty means fall back to `MODEL_NAME`)
   - `ollama_base_url: str = "http://127.0.0.1:11434"`, `ollama_num_ctx: int = 8192`, `ollama_keep_alive: str = "30m"`, `validate_model_on_init: bool = False`
   - `data_dir: Path` (default `platformdirs.user_data_dir("agent")`, env override `AGENT_DATA_DIR`)
   - `max_iterations_per_step: int = 25`, `max_parallel: int = 4`, `tool_timeout_s: int = 120`
   - `max_total_tokens: int = 500_000`, `max_wall_minutes: int = 60`, `max_cost_usd: float = 5.0` (kept for UI parity; local cost is zero)
   - `permission_mode: Literal["ask", "auto-safe", "trusted"] = "ask"`
   - `approval_timeout_s: int = 0` (0 = wait indefinitely)
   Read from `.env` and env vars. Provide `get_settings()` with `functools.lru_cache`, `get_model_name(role)` that returns the role override or `model_name`, and `ConfigError` raised by `get_model_name` when both are empty. The error must name the exact env var (`MODEL_NAME` or `MODEL_PLAN`/`MODEL_CODE`/`MODEL_SUMMARIZE`) and must never guess a model.
4. `.env.example` (and local `.env`) contains:
   ```dotenv
   MODEL_NAME=
   MODEL_PLAN=
   MODEL_CODE=
   MODEL_SUMMARIZE=
   OLLAMA_BASE_URL=http://127.0.0.1:11434
   OLLAMA_NUM_CTX=8192
   OLLAMA_KEEP_ALIVE=30m
   # AGENT_DATA_DIR=  (leave commented; empty would override the platform default)
   ```
   Leave every model blank for the human to fill. Do not invent a model name.
5. `infra/paths.py`: functions `data_dir()`, `workspace_dir(thread_id)`, `artifacts_dir(thread_id)`, `runs_dir()`, `undo_dir(workspace, patch_id)`. Each creates its folder if missing. Pure functions, no side effects other than mkdir.
6. Configure `ruff` (line length 100, rules E,F,I,UP,B) and `mypy --strict` for `src/agent`.
7. Write the CI workflow and the pre-commit hook.
8. Create `PHASE_LOG.md` with the header and a `Phase 1` entry.

**Tests to write** (`tests/unit/test_config.py`, `tests/unit/test_paths.py`)
- Settings read defaults when no env is set (use `_env_file=None`).
- `AGENT_DATA_DIR` overrides `data_dir`; `OLLAMA_NUM_CTX` parses as an int.
- `get_model_name("plan")` falls back to `MODEL_NAME`; `MODEL_PLAN` overrides; both empty raises `ConfigError` naming the env var.
- `workspace_dir("t1")` is under `data_dir()/workspaces/t1` and the folder exists.
- `workspace_dir("../etc")` raises `ValueError` (thread ids must match `^[A-Za-z0-9_-]{1,64}$`).

**Test gate**
- `uv run ruff check .` → no errors
- `uv run mypy src` → no errors
- `uv run pytest` → all pass
- `uv run agent --help` → prints usage (the CLI can be a placeholder with no subcommands yet; create it in this phase as `src/agent/cli.py` with an empty `typer.Typer()`).

**Done when**
- Gate green locally; the human pushes a branch to check CI (the implementing agent does not push).
- `.env` is git-ignored (`git check-ignore .env` prints `.env`).
- No model name is guessed anywhere.

**Do NOT:** import LangGraph or an LLM package yet, build Textual screens, or add Docker files. Do not commit, tag, push, or create branches.

**Report back:** Python version, pinned versions, CI status, the paths printed by `agent --help`, `config` defaults, and the exact empty-model error text.

---

## Phase 1.5 — Model selection store, keyring secrets, and the `agent model` CLI

**Goal:** replace the "one model in `.env`" UX with a curated, provider-keyed store: `model_config.json` for preferences, the OS keyring for API keys, and `agent model add|list|use|remove` commands. The runtime stays Ollama-only; non-Ollama selections may be stored but are flagged "not runnable yet" and refused at call time.

**Depends on:** Phase 1.
**Diagram:** none (CLI/config layer only).

**Create**
- `src/agent/modelconfig/store.py` — `ModelConfig` schema (`version: 1`; `providers.{provider} -> {base_url?, models[]}`; `selection` = `general` + optional role map keyed `plan|code|summarize`), atomic save/load with a format-version guard, `add_model` (dedup on the `(provider, model_id)` pair), `remove_model` (also clears selection references and empty providers), `set_general` / `set_role` / `unset_role`, `effective_model` (role → general inheritance by absence).
- `src/agent/modelconfig/secrets.py` — keyring wrapper: service `coding-agent`, account `{provider}:api_key`; precedence env var `{PROVIDER}_API_KEY` > keyring; `get/set/clear/has`.
- `src/agent/modelconfig/resolver.py` — `resolve_model(role)`: env override (`MODEL_{ROLE}` then `MODEL_NAME`, always provider `ollama`) → `selection.roles[role]` → `selection.general` → `ConfigError` naming the exact fix; `ensure_runtime_provider` refuses non-Ollama until the provider-extension phase; unknown roles raise `ValueError`.
- `src/agent/cli_model.py` — Typer sub-app registered as `agent model`: interactive `add` (provider list `ollama/openai/anthropic/deepseek/custom (OpenAI-compatible base_url)`; model id prompt; hidden API-key prompt skipped for Ollama and skipped when one is already stored; duplicate → "already saved, nothing added"), `list` (models grouped by provider with ★ general marker / "saved — runtime: ollama-only" flag, plus the effective general/plan/code/summarize mapping), `use [role]` with `--unset`, `remove` (cleans selections; offers key removal when the provider empties).
- `tests/unit/test_modelconfig.py`, `tests/unit/test_secrets.py`, `tests/unit/test_resolver.py`

**Modify**
- `src/agent/infra/paths.py`: add `config_file()` → `data_dir()/model_config.json`.
- `src/agent/config.py`: `get_model_name` delegates to the resolver (env overrides keep winning for CI/automation); drop the old role-env var mapping there.
- `src/agent/cli.py`: register the `model` sub-app.
- `tests/unit/test_config.py`: model tests rewritten to the new precedence (env > JSON > error); pure Settings-field tests unchanged.
- `.env.example` / `.env` / `README.md` / `PHASE_LOG.md` / `opencode.md` / this plan.

**Decisions locked**
- API keys live only in the OS keyring (or env) — never plaintext in `model_config.json`.
- Precedence: env > keyring for keys; env > JSON for model selection.
- Wizard providers: `ollama / openai / anthropic / deepseek / custom (OpenAI-compatible base_url)`.
- No network validation of model ids yet (that is doctor / the provider-extension phase).

**Test gate**
- `uv run ruff check .`, `uv run mypy src`, `uv run pytest` — all green.
- `uv run agent --help` shows the `model` command; `uv run agent model list` works (smoke-tested with a temporary `AGENT_DATA_DIR`).
- Keyring is faked/mocked in tests; nothing touches the real keyring or the network.

**Done when**
- Selection survives restart (file-backed), roles inherit the general model by absence, duplicates cannot be created twice, and the fail-loud rule holds: an unresolvable selection raises `ConfigError` naming the missing step — never an invented model.

**Do NOT:** add cloud LLM SDKs to the runtime, make the graph call non-Ollama providers, or store API keys in `model_config.json`. Do not commit, tag, push, or create branches.

---

## Phase 2 — LLM provider layer, usage tracking and a fake model

**Goal:** every model call in the project goes through one function backed by local Ollama. Tests use a scripted fake model, so no test needs the network.

**Depends on:** 1.
**Diagram:** the "LLM provider" concept used by all LLM nodes (N2, N4, N5 planning, agent_llm, N9, N10). No node yet.

**Create**
- `src/agent/llm/provider.py`
- `src/agent/llm/structured.py`
- `src/agent/llm/usage.py`
- `src/agent/llm/__init__.py`
- `tests/fakes.py` (the scripted fake model)

**Implementation steps**
1. Use `langchain-ollama==1.1.0` (`ChatOllama`) and `langchain-core==1.6.13`. No other provider package, no API key.
2. `provider.py`: `def get_model(role: Literal["plan","code","summarize"]) -> BaseChatModel`. Resolve the model name with `Settings.get_model_name(role)`; an empty name raises `ConfigError` naming `MODEL_NAME` or the role override. Build `ChatOllama(model=name, base_url=settings.ollama_base_url, num_ctx=settings.ollama_num_ctx, keep_alive=settings.ollama_keep_alive, validate_model_on_init=settings.validate_model_on_init)`. Never log secrets or send a request during construction.
3. `structured.py`: `async def structured_invoke(model, schema, messages, role=...)`. Try `model.with_structured_output(schema, method="json_schema")`; if the model rejects that method, fall back to `method="function_calling"`; if validation still fails, make one repair call with the validation error and the schema, then fail with a typed `StructuredOutputError`. Do not loop forever.
4. `usage.py`: `class UsageTracker` accumulates input/output tokens from `usage_metadata` and records cost. Ollama is local: `cost_usd=0.0` and the UI renders `$0.00 (local)`. Keep `config/prices.yaml` optional and empty; unknown local models are still zero, not an error.
5. `tests/fakes.py`: `class ScriptedChatModel(BaseChatModel)` that returns pre-written `AIMessage`s in order and reports fixed `usage_metadata`. It must support `.bind_tools()` as a no-op returning self, `.with_structured_output()` for test schemas, and streaming by yielding the whole text as one chunk. This class is used by every later phase's tests.
6. Add `provider.get_model` injection hook: a module-level `_factory` that tests can replace (`set_model_factory(fn)`), so graph code never imports a provider directly.
7. Provide a `live` marker test that calls Ollama once and is skipped by default. It is the only test allowed to touch the network.

**Tests** (`tests/unit/test_provider.py`, `tests/unit/test_usage.py`, `tests/unit/test_structured.py`)
- With `set_model_factory(lambda role: ScriptedChatModel([...]))`, `get_model("plan").invoke(...)` returns the scripted text.
- Missing `MODEL_NAME` raises `ConfigError` naming `MODEL_NAME`; missing `MODEL_PLAN` override falls back correctly.
- `UsageTracker.record` sums tokens; Ollama cost is `0.0`; the display string is `$0.00 (local)`.
- Structured output uses `json_schema` when available, falls back to `function_calling`, retries exactly once on a validation error, then raises.
- Non-live tests make no network calls (assert by monkeypatching the HTTP client).

**Test gate:** ruff, mypy, pytest green.

**Manual demo:** with the human's `MODEL_NAME` set and Ollama running, `uv run python -c "..."` streams one short reply. Otherwise use `ScriptedChatModel`.

**Done when:** every LLM call in the codebase is available only through `get_model`; `ScriptedChatModel` exists and is tested; `MODEL_NAME` is never guessed.

**Do NOT:** call any real API in non-live tests; add another provider; put a key in code or config files; set a default model name.

**Report back:** model resolution rules, empty-model error text, structured-output fallback results, fake-model usage example.

---

## Phase 3 — Event contract, emitter and graph-stream adapter

**HLD elements:** shared event contract; graph/tool event stream; UI-independent runtime events.

**Goal:** implement the event boundary that lets the runtime report progress without coupling the core to Textual or Rich.

### Create or update

- `src/agent/events/models.py` — event models and `AgentEvent` union, following section 2.1.
- `src/agent/events/emit.py` — `emit()` and one event-construction helper.
- `src/agent/events/mapper.py` — LangGraph v2 stream-part to `AgentEvent` mapping.
- `src/agent/runtime/runner.py` — thin graph-stream consumer.
- `src/agent/state.py` — only the minimum state needed by the current graph; extend it in later phases according to section 2.3.

### Implementation

1. Use the exact event kinds and payload contracts from section 2.1. Do not invent a parallel event schema.
2. Use LangGraph's installed v2 streaming API. Inspect the installed version and actual stream-part shapes before coding.
3. Keep event construction in one helper so `run_id`, `thread_id`, timestamps, and optional step/agent identifiers are consistent.
4. Keep `emit()` small. Use LangGraph's stream writer when inside a graph run and a simple test sink outside one. Catch only the expected missing-writer condition; do not swallow graph control-flow exceptions.
5. Preserve namespace information for events emitted by nested graphs/subagents.
6. Map interrupts by stable `Interrupt.id`; avoid emitting duplicate pending-approval events when a run resumes or replays.
7. The runner consumes the graph stream and yields typed events. It must not render terminal UI or own business logic.
8. Keep event delivery UI-neutral. This does not authorize an HTTP server or web API.

### Tests

- Every event model validates its required fields and payload.
- A deterministic two-node graph emits events in order.
- Nested events retain their namespace.
- Interrupt events retain the correct interrupt ID across pause/resume.
- Cancellation is handled; ordinary failures are reported, while LangGraph control-flow exceptions propagate.

**Test gate:** `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` pass.

**Done when:** a small graph can emit the shared event contract through the runner without importing UI libraries.

**Do not:** build an event bus, plugin framework, tracing platform, or duplicate event schema.

**Report back:** changed files, tested stream-part shapes, and test results.

---

## Phase 4 — Minimal graph shell, CLI and Textual interface

**HLD elements:** START/END shell, event consumer, first runtime/UI path. The full N1–N12 graph is added in later phases.

**Goal:** prove the user-input → graph → typed-events → UI path before adding coding-agent behavior.

### Create or update

- `src/agent/graph.py` — a deliberately temporary graph shell.
- `src/agent/ui/plain.py` — plain terminal rendering.
- `src/agent/ui/app.py` and `src/agent/ui/app.tcss` — minimal Textual app.
- `src/agent/cli.py` — `agent run TASK [--plain|--json]`; `agent` without a task opens the TUI.
- UI/CLI smoke tests.

### Implementation

1. Use one temporary response node calling the Phase 2 provider. Label it clearly as a phase-4 placeholder; replace it as the HLD nodes are implemented.
2. All interfaces consume the shared runner/events. Do not call graph nodes directly from the UI.
3. JSON mode emits valid JSON Lines; plain mode prints readable progress; TUI provides transcript, input, status, and cancel/quit.
4. Keep the core headless. Only `src/agent/ui/` may import Textual or Rich.
5. Keep the UI responsive, but do not add advanced widgets, slash-command frameworks, themes, or a command palette.
6. Normal tests use the fake/scripted model. Live Ollama tests are opt-in and skipped by default.

### Tests

- CLI JSON output is valid JSON Lines.
- Plain mode renders a scripted response.
- Textual smoke test submits a prompt and receives the scripted response.
- Cancelling a run leaves no stuck worker.

**Test gate:** lint, type checks, tests, and a short manual CLI/TUI demo pass.

**Done when:** the same temporary graph works through plain CLI, JSON CLI, and TUI.

**Do not:** implement planning, MCP, persistence, or real tool use here. The temporary graph is not the final HLD workflow.

**Report back:** the three interface demos and test results.

---

## Phase 5 — Isolated workspace and native read tools

**HLD elements:** workspace safety; initial Filesystem tool capability; shared tool metadata.

**Goal:** give the future agent a safe, inspectable copy of the repository and a minimal read-only toolset.

### Create or update

- `src/agent/safety/sandbox.py` — workspace creation and safe path resolution.
- `src/agent/tools/metadata.py` or the existing equivalent — tool metadata from section 2.4.
- `src/agent/tools/wrapper.py` — common event/error/duration wrapper.
- `src/agent/tools/native/read.py` — `list_dir`, `read_file`, `search_text`.
- `src/agent/tools/registry.py` — a small registry for implemented tools.
- A sample repository fixture and focused tests.

### Implementation

1. Use the configured data directory and workspace layout from section 2.5. Work only in a copy of the source repository.
2. Exclude `.git` internals and the agent's own workspace/data directory from the copy. Do not change the user's original working tree.
3. Resolve every model-supplied path against the workspace root. Reject path traversal, absolute-path escapes, and symlinks resolving outside the root.
4. Add bounded, useful read tools. Include paths and line numbers in results when possible.
5. Prefer `rg` when installed and provide a tested Python fallback for text search.
6. The common wrapper emits `tool_started`/`tool_finished`, records duration, and returns a structured tool error. It must not swallow LangGraph control-flow exceptions.
7. Tool metadata includes name, kind, risk, and allowed agents. Unknown tools are risky by default, as specified in section 2.4.
8. Keep the registry direct and local. Do not create a plugin marketplace or dynamic installer.

### Tests

- Traversal, absolute-path, and symlink escapes are rejected.
- Workspace edits do not affect the source repository.
- Read tools produce bounded output and correct file/line references.
- Tool errors are visible through events.
- Tool metadata validates allowed agents and risk classification.

**Test gate:** lint, type checks, and tests pass.

**Done when:** the copied workspace can be safely listed, read, and searched.

**Do not:** add write tools, shell execution, MCP, or approval orchestration yet.

**Report back:** workspace layout, tool list, safety test results, and known platform limitations.

---

## Phase 6 — Patch editing, undo and controlled command execution

**HLD elements:** safe file writes, shell/build/test capability, diff visibility, permission-policy foundation.

**Goal:** allow controlled edits and verification inside the copied workspace.

### Create or update

- `src/agent/tools/native/edit.py` — focused patch proposal/application and `edit_file`.
- `src/agent/tools/native/shell.py` — controlled `run_shell`.
- A small undo helper using the section 2.5 workspace layout.
- UI diff/patch summary rendering.

### Implementation

1. Separate patch proposal from patch application. Validate every target path against the workspace root.
2. Before applying, check expected original content where practical. Reject stale/conflicting patches instead of silently overwriting.
3. Store original file content under `<workspace>/.agent/undo/<patch_id>/` and support reverse-order undo for applied patches.
4. Show a readable diff and summarize affected files. Do not build a general version-control engine.
5. Run commands with argument lists where possible, workspace as `cwd`, explicit timeouts, bounded output, and a reported exit code. Never pass untrusted input to `shell=True`.
6. Use a small, explicit command policy for tests, formatters, linters, and builds. Commands that can escape the workspace or perform destructive/external actions must be rejected or later approval-gated.
7. Keep tool metadata consistent with section 2.4: file writes and shell execution are risky by default. The shared human approval flow is implemented in Phase 9.

### Tests

- Valid patches modify only the intended workspace files.
- Unsafe paths and stale patches are rejected.
- Undo restores the original bytes.
- Shell timeout, non-zero exit, and output limits are handled visibly.
- Disallowed commands cannot run.
- No test modifies the developer's source repository.

**Test gate:** lint, type checks, and tests pass.

**Done when:** a patch can be applied, reviewed, verified with an allowed command, and undone.

**Do not:** add automatic commits, PR creation, arbitrary unrestricted shell access, or a full terminal emulator.

**Report back:** patch demo, allowed-command behavior, and undo test results.

---

## Phase 7 — N6 subagent ReAct loop and fixed subagent catalog

**HLD elements:** `N6 · subagent_subgraph`, `prepare_agent`, `agent_llm`, `tools_condition` (`Ra`), approval-routing seam (`Rb`), `tool_node`, `emit_result`, and the fixed subagent catalog.

**Goal:** implement the reusable subagent loop that later receives one step through LangGraph `Send`. In this phase, exercise one subagent at a time; parallel dispatch comes in Phase 13.

### Create or update

- `src/agent/subagents/subgraph.py` — compiled subagent graph.
- `src/agent/subagents/catalog.py` — the fixed names in section 2.6.
- `src/agent/subagents/prompts/` — concise prompts, or a similarly simple prompt module.
- `src/agent/tools/tool_router.py` — the minimal agent-type tool filter if needed for this phase.
- Tests for the subgraph and tool routing.

### Implementation

1. Implement the HLD loop: `prepare_agent` → `agent_llm` → `Ra/tools_condition` → `Rb/needs_approval` → `tool_node` → back to `agent_llm`, or `emit_result` when done. In Phase 7, `Rb` may treat known tools as safe only for isolated tests; Phase 9 must enforce real approval before risky actions are enabled.
2. Use the same provider, structured-output helper, tool wrapper, event contract, and tool metadata already implemented. Do not create parallel implementations inside the subgraph.
3. `prepare_agent` selects the prompt and allowed-tool subset for the requested `agent_type`. It must reject unknown agent types and tools not allowed for that type.
4. Define all fixed catalog names now: `code_explorer`, `code_editor`, `test_runner`, `debugger`, `docs_agent`, `git_agent`, and `research_agent`. Give each a narrow description and tool allowlist. Enable only capabilities implemented and configured in earlier phases.
5. Keep one clear per-step iteration cap (baseline 25 from the HLD) and return a visible partial/failed result if it is reached.
6. The subagent returns status, concise summary, and artifact references. Large tool outputs should eventually be represented by S3 artifact references, implemented in Phase 11.
7. Do not add the planner, DAG dispatcher, or parallel execution here.

### Tests

- Scripted model calls a read tool, receives a result, and finishes.
- Scripted model with no tool calls finishes directly.
- Unknown agent type/tool is rejected.
- Tool failure is sent back as a tool error and can be handled by the model.
- Iteration cap returns a bounded result.
- Result includes status and summary.

**Test gate:** lint, type checks, and deterministic subgraph tests pass.

**Done when:** one subagent can execute a bounded ReAct loop through the shared tool wrapper.

**Do not:** run subagents in parallel, dynamically spawn arbitrary agent types, or add a supervisor hierarchy.

**Report back:** subgraph trace, catalog/allowlists, and stop-condition results.

---

## Phase 8 — S1 Postgres checkpointer, session bootstrap and R1

**HLD elements:** `S1 · Checkpointer`, `N1 · load_state`, `R1 · route_after_load`, thread identity and resume-after-restart.

**Goal:** persist graph execution and establish the correct entry path for new versus resumed tasks.

### Create or update

- `src/agent/memory/checkpointer.py` — supported LangGraph Postgres checkpointer setup.
- `src/agent/nodes/n1_load_state.py`.
- `src/agent/routers/r1_route_after_load.py`.
- Minimal session metadata/migrations only if required.
- `src/agent/infra/` helpers and the existing Postgres Docker configuration.

### Implementation

1. Use Postgres as the only persistence database. Do not add SQLite, Redis, or another database.
2. Use the supported async LangGraph Postgres checkpointer API for the pinned version. Read installed documentation/source and use its required setup/migration procedure.
3. Key graph checkpoints by `thread_id`. The checkpointer owns resumable `AgentState`; do not store a second copy of the full graph state in a custom table.
4. `N1` initializes run context and `thread_id`, restores the saved plan/summary and budgets when applicable, and runs only for a fresh invoke.
5. `R1` routes a new task to `N2`; an unfinished saved plan routes to `N3` to rebuild context and re-plan. A resumed graph must not re-enter `N1` and overwrite restored state.
6. Persist only small session metadata if the UI needs session listing. Avoid a session-management framework.
7. Keep Postgres bound to localhost in Docker Compose, read credentials from configuration, and never print secrets. If Postgres is unavailable, show actionable instructions instead of silently switching databases.

### Tests

- A checkpoint survives process restart and resumes the same thread.
- A new thread passes through `N1`; a resumed thread continues without resetting state.
- `R1` chooses the expected route for new and unfinished tasks.
- Missing Postgres produces a clear error without leaking credentials.
- Postgres integration tests are marked and run when Docker is available.

**Test gate:** unit tests pass; marked Postgres integration tests pass when configured.

**Done when:** LangGraph resumes a saved thread from Postgres and the entry routing matches the HLD.

**Do not:** duplicate checkpoint state, add another database, or implement planning logic in `N1`.

**Report back:** migration/setup notes and restart/resume test results.

---

## Phase 9 — Shared human interrupts, approval inbox and RunController

**HLD elements:** shared interrupt contract; approval inbox; `RunController`; `H3 · tool_approval`/`Rb`; future reuse by `H1`, `H2`, and `H4`.

**Goal:** implement one safe, restart-aware approval mechanism that serializes human interaction even if multiple graph branches are waiting.

### Create or update

- `src/agent/runtime/run_controller.py` — sole owner of graph streaming and resume.
- `src/agent/runtime/approval.py` — approval-inbox projection and decision validation.
- `src/agent/safety/permissions.py` — explicit policy for safe/risky/unknown tools.
- `H3` and `Rb/needs_approval` integration in the subagent graph.
- Minimal TUI approval prompt.

### Implementation

1. The checkpointer's pending interrupts are authoritative. The approval inbox is a rebuildable view/cache for the UI, not a second source of truth.
2. Use `Interrupt.id` to correlate each request with its decision. Validate that a decision matches the pending request and expected payload.
3. Only `RunController` may consume the graph stream or resume a thread. UI code sends a decision to the controller; it must not call `graph.astream()` or `Command(resume=...)` directly.
4. Use one pending request at a time in the UI. Other pending interrupts remain queued and visible as pending.
5. `H3` interrupts before a risky tool performs side effects. On approve, continue to the tool; on deny, send a `ToolMessage` such as `"denied"` back to the agent loop; on abort, terminate through `N12` once Phase 14 adds it.
6. Make interrupted nodes safe to replay: do not perform the risky action before calling `interrupt()`. On resume, validate the decision and then perform the action once.
7. Unknown tools are risky. Apply the same policy to native and MCP tools. Do not implement separate approval queues per tool/gate.
8. Provide a clean seam for H1/H2/H4 to reuse later; do not build their task/planning/recovery behavior before those phases.

### Tests

- Risky tool pauses before execution.
- Approval invokes the matching tool once; denial does not invoke it and returns a denial message to the model.
- Wrong/stale interrupt IDs are rejected.
- Multiple pending interrupts are presented one at a time without losing their IDs.
- Pending approvals can be reconstructed from a Postgres checkpoint after restart.
- Abort leaves the run in a clear state.

**Test gate:** unit, graph, and Postgres-backed interrupt/resume tests pass.

**Done when:** risky tool execution uses one checkpoint-backed approval flow.

**Do not:** create separate approval managers for each gate, or treat an in-memory queue as authoritative.

**Report back:** approval lifecycle and restart test results.

---

## Phase 10 — S2 context-source adapters, MCP Tool Router and Serena

**HLD elements:** `S2 · Context sources`, Tool Router, MCP `tool_node` integration, Serena, Filesystem, Shell, Git/GitHub and optional external research tools.

**Goal:** connect configured MCP capabilities through the same tool metadata, wrapper, and approval policy as native tools.

### Create or update

- `src/agent/tools/mcp_runtime.py` — configured MCP client lifecycle.
- `src/agent/tools/tool_router.py` — permission-scoped tool exposure by `agent_type`.
- `src/agent/context/sources.py` — thin adapters for context-source tools.
- `config/mcp_servers.yaml` and `config/policy.yaml`.
- Minimal diagnostics for unavailable MCP servers.

### Implementation

1. Integrate Serena and Filesystem MCP first. Add Git/GitHub, Shell, Browser/Web, Database, or other MCP servers only when configured and required by the HLD workflow.
2. Normalize MCP tool metadata into the same shape as native tools: name, kind, risk, and `allowed_agents`. Reuse the existing wrapper and approval flow.
3. The Tool Router exposes only tools allowed for the current agent type and policy. It is a small filter/validation component, not another LLM agent or a complex rules engine.
4. `S2` is the logical context-source layer: Serena symbols/references, filesystem search/read, Git history, and runtime/test logs. Use thin adapters; do not duplicate the MCP client's job.
5. Fail clearly when a server is not configured or unavailable. One missing optional server must not crash unrelated read-only tasks.
6. Treat repository text, web pages, and tool results as untrusted input. Tool descriptions and results cannot bypass policy or approval.
7. Keep normal tests offline using fake MCP clients. Mark live MCP tests and skip them by default.
8. Do not add a server/HTTP API for this local agent. “Browser/Web” means a configured tool capability, not a new web backend for the application.

### Tests

- Fake MCP server tools pass through the common wrapper and event stream.
- Serena can perform a symbol/reference lookup.
- Tool Router rejects a tool not allowed for the selected agent type.
- Risky MCP tools use H3 approval.
- Missing server and invalid configuration produce actionable errors without leaking secrets.

**Test gate:** normal tests pass; marked MCP tests pass when configured.

**Done when:** Serena and Filesystem MCP work through the same policy boundary as native tools, with other integrations configurable.

**Do not:** install servers dynamically, trust all MCP tools, or replace working native tools solely to make everything MCP-based.

**Report back:** configured servers, per-agent tool access, and integration-test results.

---

## Phase 11 — N3 context builder, S3 artifact store, N9 compaction and R7

**HLD elements:** `N3 · build_context`, `S2 · Context sources`, `S3 · Artifact Store`, `N9 · compact_context`, `R7 · route_compaction`.

**Goal:** keep prompts relevant and bounded while storing large outputs outside graph state.

### Create or update

- `src/agent/context/builder.py` — `N3`.
- `src/agent/context/tokens.py` — conservative context-size estimate.
- `src/agent/nodes/n9_compact_context.py`.
- `src/agent/routers/r7_route_compaction.py`.
- `src/agent/memory/artifact_store.py` — S3 implementation.
- Extend `AgentState` with `context_refs` and `artifact_refs` according to section 2.3 when this phase adds them.

### Implementation

1. `N3` builds a context bundle from the current task/plan, relevant Serena symbols, targeted file/search results, Git history where useful, and relevant runtime/test logs.
2. Store references in `AgentState`, not entire large file dumps or test logs. S3 stores bounded, thread-scoped artifacts under the configured data directory using section 2.5.
3. Artifact metadata stays small: ID, path, size, content type, creation time. Enforce data-directory boundaries and safe filenames.
4. `R7` compares estimated context use against the configured window. Use the HLD's 70% threshold as the initial default, configurable in settings.
5. When context is at or below threshold, route to the next ready step. Above threshold, run `N9`, which summarizes older history, preserves the task/plan/key findings/unresolved errors, and replaces raw tool output with references.
6. Use the existing provider/token accounting where available. If a model does not report exact token counts, label estimates as estimates.
7. Keep compaction as one focused node. Do not build a multi-tier memory hierarchy, embeddings, vector search, or a knowledge graph.
8. Emit `context_updated` when the effective context changes materially.

### Tests

- Context includes relevant source findings and excludes unrelated oversized output.
- Large logs/diffs are stored as S3 artifacts and referenced from state/events.
- Artifact path escapes are rejected.
- `R7` chooses the correct branch around the configured threshold.
- `N9` preserves task, plan, key findings, and unresolved errors.
- The graph continues after compaction without duplicating old raw output.

**Test gate:** unit and graph tests pass.

**Done when:** context building and compaction follow the HLD while graph state remains bounded.

**Do not:** add embeddings/vector DB, automatic repository-wide indexing, or speculative memory layers.

**Report back:** context threshold behavior and one example artifact reference.

---

## Phase 12 — N2 task analysis, H1 clarification, N4 planning and H2 plan review

**HLD elements:** `N2 · analyze_task`, `R2 · route_after_analyze`, `H1 · human_clarify`, `N4 · planner`, `R3 · route_after_plan`, `H2 · plan_review`.

**Goal:** create the HLD's typed task and plan, with clarification/review only when needed.

### Create or update

- `src/agent/nodes/n2_analyze_task.py` and `src/agent/routers/r2_route_after_analyze.py`.
- `src/agent/nodes/h1_human_clarify.py`.
- `src/agent/nodes/n4_planner.py` and `src/agent/routers/r3_route_after_plan.py`.
- `src/agent/nodes/h2_plan_review.py`.
- Typed `Task`, `Step`, and `Plan` models from section 2.2.

### Implementation

1. `N2` classifies task type, defines measurable success criteria, estimates ambiguity and risk, and records a concise rationale.
2. `R2` routes clear tasks to `N3`; only tasks blocked by missing information go to `H1`.
3. `H1` uses LangGraph `interrupt()`. A user answer returns to `N2` to re-analyze; abort routes to `N12` once available.
4. `N4` produces a small DAG plan with step IDs, goals, dependencies, agent type, status, verification expectation, and rationale. Assign one catalog agent per step.
5. Validate the plan structurally and check dependency IDs/cycles. If invalid, retry planning at most twice, then surface the problem instead of building a repair framework.
6. `R3` decides whether plan review is needed based on plan validity, risk, and configuration. `H2` allows approve, edit/reject with feedback, or abort. Approved plans route to `N5`; feedback returns to `N4`.
7. Use the shared RunController/interrupt contract from Phase 9. Do not create another human queue.
8. Keep planning proportionate: simple tasks should get short plans and avoid unnecessary human prompts.

### Tests

- Clear task routes to context building without clarification.
- Ambiguous task triggers H1; answer returns through N2 and abort terminates.
- Planner produces a valid DAG with dependencies and verification expectations.
- Invalid/cyclic plan retries no more than twice.
- H2 approve/edit/reject/abort routes correctly.
- Structured-output failures remain bounded.

**Test gate:** graph and UI tests pass with scripted model responses.

**Done when:** the task intake and plan-review paths match the HLD and reuse the common interrupt flow.

**Do not:** make human clarification or plan approval mandatory for every task.

**Report back:** one simple-task trace, one clarification trace, and one reviewed-plan trace.

---

## Phase 13 — N5 dispatch, N6 parallel subagents, N7 merge and R4/R5

**HLD elements:** `N5 · dispatch_step`, `R4 · route_dispatch`, `N6 · subagent_subgraph`, `N7 · observe_merge`, `R5 · route_after_observe`, `Send` fan-out, dependency-aware concurrency and write locks.

**Goal:** execute plan steps in dependency order and safely join independent subagent results.

### Create or update

- `src/agent/nodes/n5_dispatch_step.py` and `src/agent/routers/r4_route_dispatch.py`.
- `src/agent/nodes/n7_observe_merge.py` and `src/agent/routers/r5_route_after_observe.py`.
- `src/agent/state.py` reducers for `ready_steps` and `step_results`.
- Small per-workspace write-lock utility if needed.
- The existing N6 subgraph from Phase 7, now invoked through `Send`.

### Implementation

1. `N5` selects steps whose dependencies are complete, validates the selected `agent_type`, confirms the agent has required tools, respects the concurrency limit, and checks write conflicts.
2. `R4` emits one LangGraph `Send` payload per ready step. If no step is ready while unfinished steps remain, route to `N10` as a blocked-plan error.
3. Reuse the N6 subgraph. Each worker receives only its step, agent type, context references, and required settings—not a copy of the entire conversation/history.
4. `N7` joins results using a reducer keyed by step ID, marks statuses, stores large results in S3, and reports failed/partial steps. Merge deterministically by step ID.
5. Read-only steps can run in parallel. Writes must be serialized at minimum per file/workspace; never let two workers edit the same file concurrently. Keep concurrency low and configurable.
6. `R5` routes all-success results to `N8`; any failed/error result goes to `N10`.
7. Do not implement arbitrary dynamic agent spawning. Use the fixed catalog in section 2.6. If a reliable write-lock or merge strategy cannot be implemented simply, serialize all write steps and document the limitation.
8. The graph must remain resumable with concurrent branches. Test the installed LangGraph `Send` and reducer behavior rather than relying on assumed semantics.

### Tests

- Dependent steps execute only after prerequisites complete.
- Independent read-only steps fan out and join correctly.
- Results merge deterministically regardless of completion order.
- Conflicting writes are serialized or rejected.
- Failed/partial worker results route to N10.
- A no-ready-step blocked plan is reported rather than hanging.
- Multiple subagent interrupts are correlated by ID and shown one at a time.

**Test gate:** deterministic sequential graph tests pass; parallel/Postgres integration tests pass when configured.

**Done when:** dependency-aware dispatch and parallel-safe merge match the HLD, with bounded concurrency and safe writes.

**Do not:** add a supervisor hierarchy, unrestricted parallel writes, or a separate approval mechanism inside each subagent.

**Report back:** dispatch trace, concurrency setting, merge behavior, and conflict tests.

---

## Phase 14 — N8 progress/budget checks, N10 recovery, H4 escalation, N11 verification and N12 finalization

**HLD elements:** `N8 · progress_check`, `R6 · route_after_progress`, `N10 · error_handler`, `R8 · route_error`, `H4 · escalate_human`, `N11 · verify`, `R9 · route_after_verify`, `N12 · finalize`.

**Goal:** close every loop safely, recover only from recoverable failures, verify the actual result, and return a clear final status.

### Create or update

- `src/agent/nodes/n8_progress_check.py` and `src/agent/routers/r6_route_after_progress.py`.
- `src/agent/nodes/n10_error_handler.py` and `src/agent/routers/r8_route_error.py`.
- `src/agent/nodes/h4_escalate_human.py`.
- `src/agent/nodes/n11_verify.py` and `src/agent/routers/r9_route_after_verify.py`.
- `src/agent/nodes/n12_finalize.py`.
- Extend state with `error`, `attempts`, and `budget` according to section 2.3.

### Implementation

1. `N8` checks whether the current goal is met, whether progress is being made, and whether token/time/iteration limits are reached. Use the outer LangGraph recursion limit plus the N6 per-step cap.
2. `R6` routes to `R7`/the next step when work remains, to `N11` when the plan is complete, and to `N10` when stuck, looping, or over budget.
3. `N10` classifies the error (`transient`, `context`, `plan`, `agent`, `fatal`, or `verify`), increments the relevant attempt counter, adds a concise recovery hint, and emits an error report.
4. `R8` uses bounded, explicit rules: retry transient failures or reassign a wrong agent through `N5`; rebuild context/re-plan for context or plan errors via `N3`; route fatal/exhausted failures to `H4`.
5. `H4` uses the shared interrupt system. Offer guidance (then replan through N3), accept a partial result, or abort. Do not trap the user in repeated escalations.
6. `N11` runs configured tests, lint, and build checks through the controlled shell/tool layer. Capture bounded output in S3 and return pass/fail results. Do not claim tests passed if they were skipped or failed.
7. `R9` routes verification pass to `N12`; failure goes through `N10` with `error.kind="verify"` and then `R8`.
8. `N12` produces the change summary, diff stats, verification report, remaining issues, and final status (`done`, `partial`, or `aborted`). Any commit/branch/PR behavior must be inside the copied workspace, opt-in, and approval-gated; never operate on the developer's current repository.
9. Make limits configurable and finite. Avoid generic self-healing frameworks, endless retries, or complicated scoring models. A simple repeated-tool-call/no-progress signal is enough initially.
10. Ensure every terminal route reaches a final state. An aborted run must not accidentally be reported as successful.

### Tests

- Transient errors retry only within configured limits.
- Invalid paths/permission denials do not trigger pointless retries.
- Context/plan errors route to N3; fatal/exhausted errors reach H4.
- Budget and no-progress limits stop the run with a clear reason.
- Verification success/failure follows R9 and R8 correctly.
- Final report matches actual file changes and command results.
- Every run ends as done, partial, failed, or aborted; none hangs indefinitely.

**Test gate:** unit and graph tests pass; marked Postgres/recovery integration tests pass when configured.

**Done when:** all HLD error paths, budgets, verification, escalation, and finalization are implemented and tested.

**Do not:** retry forever, hide failed verification, or create commits/PRs without explicit policy and approval.

**Report back:** error-route matrix, verification evidence, and final status examples.

---

## Phase 15 — HLD completeness review, security, evaluation and packaging

**HLD elements:** runtime rules, auditability, secret redaction, all node/router/gate traceability, practical release readiness.

**Goal:** validate the implementation against the complete HLD and make the local application safe and understandable to install and operate.

### Create or update

- `evals/` — a small deterministic evaluation suite.
- `src/agent/safety/audit.py` and `src/agent/safety/redact.py` if the existing code does not already cover these responsibilities.
- `agent doctor` and minimal first-run/setup instructions.
- Packaging metadata and concise architecture, security, and troubleshooting docs.
- CI for lint, types, unit tests, graph tests, and a small evaluation subset.

### Implementation

1. Create a traceability checklist for every HLD ID: N1–N12, R1–R9, Ra/Rb, H1–H4, S1–S3, the seven subagent types, and Tool Router. Mark each implemented/tested or explicitly deferred with a reason. Do not silently omit a diagram element.
2. Add a small representative evaluation set (about 10–15 tasks initially): read-only investigation, single-file edit, multi-file change, verification failure, missing context, denied tool, resume after interruption, and budget exhaustion.
3. Record useful metrics already available from events: task status, verification result, tool calls, retries, approvals, elapsed time, and token usage when reported. Do not build a benchmark platform.
4. Redact secrets from logs/events. Never log `.env` contents, database credentials, or secret environment values.
5. Keep an append-only audit record for risky actions and human decisions, with no unnecessary file contents or secrets.
6. Test workspace confinement, disallowed commands, prompt injection from repository/tool content, approval bypass attempts, interrupt replay, and secret redaction.
7. Provide `agent doctor` for configuration, Ollama reachability/model selection, Postgres status, MCP configuration, and data/workspace permissions. Diagnostics are read-only unless the user explicitly asks for a repair.
8. Verify a clean install, `agent --help`, and a representative local run. Keep setup short and errors actionable.
9. No telemetry by default. Do not add a server/API, OpenWiki, Redis, SQLite, vector DB, or plugin marketplace.
10. Keep real Ollama/MCP/network tests opt-in. Normal CI must be deterministic and offline.
11. Replay/transcript export is optional only if the event log supports it cheaply; it must not become a release blocker unless required by the HLD.

### Tests

- HLD traceability checklist has no unexplained missing IDs.
- Security tests cover path escapes, shell policy, prompt injection, approval bypass, and secret redaction.
- Evaluation suite runs offline with fakes.
- Clean-environment package install and `agent --help` pass.
- `agent doctor` reports actionable diagnostics without leaking secrets.

**Test gate:** lint, type checks, unit/graph tests, security tests, evaluation subset, and package smoke test pass.

**Done when:** the implementation matches the HLD's intended behavior, has evidence for safety/reliability, and can be installed and diagnosed locally.

**Do not:** add infrastructure excluded by the HLD, claim unsupported capabilities, or make optional integrations mandatory.

**Report back:** HLD traceability checklist, evaluation summary, security test results, and remaining limitations.

---

## 4. Dependency order

1. Phase 3: shared events and runner.
2. Phase 4: temporary graph shell and CLI/TUI path.
3. Phase 5: isolated workspace and read tools.
4. Phase 6: patch application, undo, and controlled shell.
5. Phase 7: N6 subagent ReAct loop and fixed catalog.
6. Phase 8: S1 Postgres checkpointing, N1, and R1.
7. Phase 9: shared approval inbox, RunController, H3, and Rb.
8. Phase 10: S2/context-source adapters, MCP Tool Router, and Serena.
9. Phase 11: N3, S3, N9, and R7.
10. Phase 12: N2, R2, H1, N4, R3, and H2.
11. Phase 13: N5, R4, N7, R5, and bounded `Send` parallelism.
12. Phase 14: N8, R6, N10, R8, H4, N11, R9, and N12.
13. Phase 15: HLD traceability, security, evaluation, packaging, and diagnostics.

## 5. Rules for production quality without overengineering

1. **Smallest complete implementation:** production quality means safe behavior, clear errors, bounded work, tests, and maintainable boundaries—not maximum abstraction count.
2. **The HLD is the feature contract.** Keep its node/router/gate/store IDs and required behaviors. Simplify internal implementation, not away required HLD capabilities.
3. **Reuse shared contracts:** provider, event models, tool wrapper, metadata, workspace boundary, checkpoint, and approval flow must each have one implementation.
4. **One source of truth per concern:** Postgres checkpointer owns resumable graph state; pending interrupts in checkpoint are authoritative; the approval inbox is a rebuildable projection; the workspace owns file changes.
5. **Keep modules responsibility-based:** use the prescribed `n#_...` and `r#_...` modules for graph traceability, but do not split trivial helpers into their own modules without a reason.
6. **Prefer direct control flow:** avoid generic factories, registries, managers, routers, and plugin layers beyond those required by the HLD or a concrete test/safety boundary.
7. **Bound all model/tool work:** explicit timeouts, output caps, iteration limits, retry limits, and finite budgets are production requirements.
8. **Fail visibly and safely:** never swallow errors, silently skip verification, bypass approval, or report success after a failed check.
9. **Deterministic tests first:** use scripted models and fake tools. Keep real Ollama, Postgres, and MCP integration tests marked and skipped by default.
10. **Do not build ahead:** record later ideas in `PHASE_LOG.md` under `Later:` and stop at the current phase's completion criteria.
11. **Do not rewrite working code for stylistic reasons:** preserve Phases 1, 1.5, and 2 unless a real contract, test, security, or correctness issue requires a change.
12. **Lean dependencies:** use existing libraries and the pinned versions. Verify APIs from installed docs/source before implementation.
13. **Report evidence:** list changed files, commands and exact results, manual demo, limitations, and deferred work.

## 6. Session checklist

- [ ] Read the project guide, sections 0–2 of this plan, the current phase, and the relevant HLD nodes/panels.
- [ ] Inspect existing code and tests before editing. Preserve working Phase 1, 1.5, and 2 behavior.
- [ ] Implement exactly the current phase. Do not build later-phase behavior early.
- [ ] Keep HLD IDs and state/event/tool contracts consistent.
- [ ] Prefer a direct, testable implementation over speculative abstractions.
- [ ] Run `uv run ruff check .`, `uv run mypy src`, and relevant `uv run pytest` commands.
- [ ] Run integration tests only when services are configured; state clearly when skipped.
- [ ] Update `PHASE_LOG.md` with what changed, deviations, open questions, and `Later:` items.
- [ ] Report changed files, test results, manual demo, limitations, and deferred ideas.
- [ ] Stop and wait for human review before advancing to the next phase.

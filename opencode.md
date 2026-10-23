# Project Guide — Local-First Coding Agent

Last updated: 2026-10-22

This file is the working orientation for future coding sessions. It is **not** a replacement for the two source-of-truth files:

1. `implementation-plan-15-phases.md` — the build contract.
2. `coding-agent-langgraph-no-openwiki.excalidraw` — the architecture graph.

If this guide conflicts with either source of truth, **the plan and diagram win**. Update this guide when a real decision changes.

---

## 1. Current status

- Planning and architecture are complete and updated.
- **Phase 1 and Phase 1.5 are implemented locally.**
- The next allowed implementation step is **Phase 2 only**.
- Do not start Phase 2 until the human explicitly asks to build it.
- The repository currently contains the plan, the diagram, this guide, a Python 3.11.2 project skeleton, pinned dependencies, tests, and local configuration.
- The human owns all git/GitHub work.

---

## 2. What we are building

A **local-first terminal coding agent** with:

- a **Textual TUI** (plus plain-text and JSON CLI output),
- a **LangGraph** state machine,
- **Ollama** as the only model provider,
- **Postgres in Docker** for checkpoint persistence,
- **MCP tools** for Serena, filesystem, git, shell, and optional GitHub/browser,
- a queue-driven **human approval system** shared by all human gates,
- a copied workspace for safe edits,
- typed events streamed from the headless core to every UI.

There is **no server/HTTP API**, no LangGraph Platform, no OpenAI Assistants API, no OpenWiki, no Redis, and no SQLite.

Run flow:

```text
UI task
  -> RunController owns graph.astream
  -> nodes/tools emit typed events
  -> UI renders events
  -> human gate calls interrupt()
  -> pending requests enter the approval inbox
  -> TUI shows one request at a time
  -> Command(resume={Interrupt.id: decision})
  -> graph continues or re-interrupts remaining tasks
```

---

## 3. Non-negotiable rules

1. **One phase per session.** Read the phase, section 2, and the diagram nodes listed for it. Implement only that phase.
2. **Do not build ahead.** Add later ideas to `PHASE_LOG.md` under `Later:`.
3. **Names are fixed.** Use `N1`–`N12`, `R1`–`R9`, `H1`–`H4`, `S1`–`S3`, and the catalog names verbatim in files, functions, events, and logs.
4. **Finish protocol:** update `PHASE_LOG.md`, report changed files and exact test results, then stop for review.
5. **Never run git operations:** no `git add`, `git commit`, `git tag`, `git push`, or branch operations in this repository. The human handles all git/GitHub work. The product may implement its own N12 runtime commit/PR behavior; that is application code, not the implementing agent acting on this repo.
6. **Core stays headless:** everything under `src/agent/` except `src/agent/ui/` must not import `rich` or `textual`.
7. **Ollama only.** No other provider, no API key, no default/guessed model name.
8. **No real network calls in normal tests.** Use `ScriptedChatModel`; only marked `live`, `mcp`, and similar integration tests may touch real services.
9. **Postgres only** for persistence. No SQLite, Redis, or extra databases.
10. **Do not print or log secrets.** Redact DB passwords and any key-like values.
11. **Do not bind Postgres to `0.0.0.0`.** It binds to `127.0.0.1:54329`.
12. **Do not perform side effects before `interrupt()`.** LangGraph re-runs the interrupted node from its start on resume.
13. **Do not swallow `GraphBubbleUp` / `GraphInterrupt`.** Re-raise them in broad handlers.
14. **Pin versions.** Verify installed APIs before coding against them.

---

## 4. Phase map

| Phase | Main deliverable |
|---|---|
| 1 | Project skeleton, Python 3.11.2, pinned deps, config, paths, CI, `PHASE_LOG.md` |
| 1.5 | Model selection store (`model_config.json`), OS keyring secrets, `agent model add/list/use/remove`, resolver |
| 2 | Ollama provider, structured-output helper, usage tracking, `ScriptedChatModel` |
| 3 | Typed events, emitter, v2 stream mapper, runner |
| 4 | Minimal graph, plain CLI, first Textual shell |
| 5 | Workspace sandbox, read tools, tool wrapper |
| 6 | Edit/patch tool, shell tool, diff view, undo |
| 7 | Subagent ReAct loop, `Ra`, iteration cap, thinking view |
| 8 | Postgres/Docker, `AsyncPostgresSaver`, N1/R1, sessions screen |
| 9 | Risk policy, `Rb`, H3, approval queue, `RunController` |
| 10 | MCP runtime, tool router, Serena, tools panel |
| 11 | Context builder, artifact store, R7/N9 compaction |
| 12 | N2/R2/H1, N4 planner, R3/H2 plan review |
| 13 | N5 dispatch, R4, parallel subagents via `Send`, N7 merge |
| 14 | N8/R6, N10/R8, H4, N11/R9, N12 finalize |
| 15 | Evals, replay, security, packaging, first-run wizard |

Phase order matters: persistence comes before approvals, MCP tools come after approvals, context comes after Serena, and parallel orchestration comes after planning.

---

## 5. Expected layout

```text
src/agent/
  config.py
  cli.py
  graph.py
  state.py
  events/       models.py emit.py mapper.py
  runtime/      runner.py approval.py run_controller.py replay.py
  llm/          provider.py structured.py usage.py
  nodes/        n1_*.py ... n12_*.py h1_*.py h2_*.py h4_*.py
  routers/      r1_*.py ... r9_*.py rb_*.py
  subagents/    subgraph.py catalog.py h3_tool_approval.py prompts/
  tools/        wrapper.py registry.py mcp_runtime.py tool_router.py native/
  context/      builder.py git_history.py tokens.py compaction.py
  memory/       checkpointer.py artifact_store.py
  safety/       sandbox.py permissions.py locks.py budgets.py loop_detect.py
  infra/        paths.py docker_pg.py keychain.py migrate.py doctor.py first_run.py
  ui/           app.py app.tcss plain.py screens/ widgets/
config/         policy.yaml mcp_servers.yaml prices.yaml
docker/         compose.yml
migrations/     001_threads.sql 002_approvals.sql 003_context.sql
tests/          unit/ graph/ ui/ chaos/ fixtures/
evals/          tasks/ run_evals.py results/
```

---

## 6. Configuration contract

`Settings` uses `pydantic-settings`, reads `.env` and environment variables, and has safe defaults for everything except model names.

Key fields:

```dotenv
MODEL_NAME=
MODEL_PLAN=
MODEL_CODE=
MODEL_SUMMARIZE=

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_NUM_CTX=8192
OLLAMA_KEEP_ALIVE=30m

# AGENT_DATA_DIR=   leave commented; empty would override the platform default
```

Rules:

- `.env` is local, git-ignored, and never committed.
- Every model variable may be empty until the human fills it.
- `get_model_name(role)` returns the role override or `MODEL_NAME`.
- If both are empty, raise `ConfigError` naming the exact env var. **Never guess a model name.**
- `validate_model_on_init=False`; do not make a network call during model construction.
- Cost for local Ollama is always `0.0`; UI shows `$0.00 (local)`.
- `max_iterations_per_step=25`, `max_parallel=4`, `tool_timeout_s=120`.
- Budget defaults: `max_total_tokens=500_000`, `max_wall_minutes=60`, `max_cost_usd=5.0` (kept for UI parity; local cost is zero).

Data paths:

- Data: platform user data dir for `agent`, overridable with `AGENT_DATA_DIR`.
- Workspace: `<data_dir>/workspaces/<thread_id>/`.
- Undo: `<workspace>/.agent/undo/<patch_id>/`.
- Artifacts: `<data_dir>/artifacts/<thread_id>/`.
- Run logs: `<data_dir>/runs/<run_id>.jsonl`.

---

## 7. Event contract

Base fields on every event:

```text
kind, run_id, thread_id, ts, step_id, agent
```

Event kinds:

`node_entered`, `text_delta`, `thinking_delta`, `tool_started`, `tool_finished`, `file_read`, `patch_proposed`, `patch_applied`, `patch_rejected`, `plan_updated`, `step_status`, `context_updated`, `interrupt_requested`, `approval_resolved`, `usage`, `retry`, `error`, `run_finished`, `log`.

Rules:

- Nodes call `emit(event)`; nodes never import UI code.
- `emit` uses `get_stream_writer()`.
- If no writer exists (outside a graph run), buffer for tests; do not crash.
- Catch only the missing-writer failure. Re-raise graph control-flow exceptions.
- Use `astream(..., stream_mode=["custom", "updates", "messages"], subgraphs=True, version="v2")`.
- Each part is a `StreamPart` with `type`, `ns`, `data`; not an old `(mode, chunk)` tuple.
- Preserve `ns` so nested subagent events are attributed correctly.
- Approval requests are created from `__interrupt__` / `state.interrupts`, never emitted inside a node before `interrupt()`.
- Deduplicate replayed events by stable IDs / `interrupt_id`.

---

## 8. State and graph

`AgentState` is a `TypedDict` persisted by S1. Fields are added by the phase that needs them:

```text
thread_id, run_id, workspace_path, iteration       phase 8
messages (add_messages reducer)                    phase 7
task: Task | None                                  phase 12
plan: Plan | None                                  phase 12
ready_steps: list[str]                             phase 13
step_results: dict[str, StepResult] (merge)        phase 13
context_refs: list[ContextRef]                     phase 14
artifact_refs: list[str]                           phase 14
error, attempts                                    phase 15
budget                                             phase 15
human: HumanState                                  phase 9
status                                             phase 8
```

`HumanState` is only a cache:

```text
{pending_interrupt_ids, decisions, feedback, last_gate}
```

The checkpoint's `state.interrupts` is authoritative. The approval queue is **not** an `AgentState` field.

Main graph flow:

```text
START
 -> N1 load_state
 -> R1 route_after_load
 -> N2 analyze_task
 -> R2 route_after_analyze
 -> H1 human_clarify / N3 build_context
 -> N4 planner
 -> R3 route_after_plan
 -> H2 plan_review / N5 dispatch_step
 -> R4 route_dispatch
 -> N6 subagent_subgraph (one Send per ready step)
 -> N7 observe_merge
 -> R5 route_after_observe
 -> N8 progress_check
 -> R6 route_after_progress
      -> more steps: R7 route_compaction -> N5 or N9 -> N5
      -> complete: N11 verify
      -> stuck/budget: N10 error_handler
 -> R8 route_error
      -> N5 (retry/reassign) / N3 (replan) / H4 escalate
 -> N11 verify
 -> R9 route_after_verify
 -> N12 finalize
```

Resolved loop rule:

```text
N8 -> R6 -> (more steps) -> R7 -> N5/N9 -> ... -> N5
```

Plan-complete goes to N11; stuck or over-budget goes to N10.

N1 flows:

- fresh thread -> initialize workspace, run ID, budget, status;
- crash-resume with `None` -> skip N1 and take the resume path;
- new task on an existing thread -> re-enter N1 with a new `run_id`, preserving workspace/prior state.

N12 must never commit to the user's current `main`/`master` branch. It commits to `agent/<thread_id[:8]>` in the target workspace. The implementing agent does not perform these commits on this repository.

---

## 9. Approval queue contract

This is the most important cross-cutting design. All four human gates share it.

Components:

- `RunController` — exactly one per session/thread; the only code allowed to call `graph.astream` for that thread.
- `ApprovalInbox` — `asyncio.Queue[ApprovalRequest]`; a TUI wake-up mechanism, not persisted and not authoritative.
- `pending: dict[str, ApprovalRequest]` — keyed by LangGraph `Interrupt.id`, rebuilt from the checkpoint.
- `ApprovalRequest` — UI/audit object.
- `ToolApprovalDecision` — H3 response schema.
- H1/H2/H4 define their own response schemas: `ClarifyAnswer`, `PlanDecision`, `BlockerDecision`.

Hard rules:

1. One parent thread per session. `Send` subagents share the parent run, checkpoint, and `thread_id`. Never create a thread per subagent.
2. The checkpoint is authoritative. Rehydrate with `await graph.aget_state(config)` and read `state.interrupts`.
3. Use `Interrupt.id` as the resume key, never a UI `request_id`.
4. `Command(resume={interrupt.id: decision})`; resume one interrupt at a time in the TUI. LangGraph re-interrupts the remaining tasks.
5. Only `RunController` resumes. Never run concurrent `astream` calls for the same thread.
6. Interrupts arrive in superstep batches. While paused, no new interrupt can appear.
7. `interrupt(payload, response_schema=...)` is the first statement in an `H#` node. No side effects before it.
8. Emit the UI request from `__interrupt__` / `state.interrupts`, never before `interrupt()`.
9. Keep payloads compact. Large diffs/commands live in S3 with an `artifact_id`.
10. Deduplicate replayed events by `interrupt_id`.
11. Status lifecycle: `PENDING -> RESOLVING -> RESOLVED | REJECTED | CANCELLED | FAILED`.
12. Cancel by rejecting/aborting all pending interrupts and recording the reason.

Data model:

```python
ApprovalStatus = Literal[
    "PENDING", "RESOLVING", "RESOLVED", "REJECTED", "CANCELLED", "FAILED"
]

class ApprovalRequest(BaseModel):
    request_id: str          # UI/audit only
    interrupt_id: str        # LangGraph Interrupt.id; resume key
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
    edits: dict[str, Any] | None = None
    scope: Literal["once", "session"] = "once"
```

Resume:

```python
await graph.astream(
    Command(resume={request.interrupt_id: decision.model_dump(mode="json")}),
    config={"configurable": {"thread_id": thread_id}},
    stream_mode=["custom", "updates", "messages"],
    subgraphs=True,
    version="v2",
)
```

TUI behavior:

- show queue position, gate, step/subagent, exact tool args, and diff/command preview;
- `y` approve, `n` reject, `a` approve for this session, `Esc` reject, `Ctrl+C` cancel;
- H1/H2/H4 have their own labels but the same inbox and resume path;
- sessions screen shows pending approval count from `state.interrupts`;
- `agent resume <thread_id>` rehydrates pending approvals.

Required tests include:

- two parallel subagents interrupt in one superstep;
- approve first, graph re-interrupts for second, approve second, N7 merges;
- deny prevents the protected side effect;
- restart with two pending approvals rehydrates both;
- UI id used as resume key fails clearly;
- completed sibling does not repeat its side effect;
- cancel marks all pending `CANCELLED`;
- resume does not duplicate a modal.

---

## 10. Persistence and Docker

- Postgres 16, container `agent-postgres`.
- Host binding: `127.0.0.1:54329:5432`.
- Named volume: `agent_pgdata`.
- Password stored in the OS keychain under `pg_password`; generated with `secrets.token_urlsafe(24)`.
- `AsyncPostgresSaver.from_conn_string(...)` is an **async context manager**.
- Keep it open with a long-lived `AsyncExitStack`; call `await saver.setup()` once.
- Migrations are applied in order and recorded in `schema_version`.
- Docker Desktop is installed on this machine but the daemon is currently not running. `agent doctor` must explain that clearly.

---

## 11. MCP and Serena

- Use a long-lived `McpRuntime`; one task owns all sessions and the `AsyncExitStack`.
- Load tools with `load_mcp_tools(session)`.
- Do **not** call `MultiServerMCPClient.get_tools()` per turn; it opens a new session each time.
- Prefix tool names with the server name.
- Limit each agent to at most 15 tools.
- Serena is pinned and launched as:

```text
uvx --from serena-agent==2.1.0 serena start-mcp-server --context=claude-code --project <workspace>
```

- Serena runs as a separate process.
- The Serena wrapper exposes only the operations the agent needs: `overview`, `find`, `references`, `symbol_body`.
- MCP servers run in other processes, so the client-side wrapper emits tool events.
- Enable the browser server read-only for `research_agent` in Phase 13.
- Enable GitHub only in Phase 14, after H3 exists; PR creation is a risky tool.

---

## 12. Context and budgets

- Context window is `OLLAMA_NUM_CTX` (default 8192), capped by the model's advertised maximum.
- Budget split: 15% plan/success criteria, 50% code, 20% history/logs, 15% tool results.
- Raw tool output goes to S3; state keeps references only.
- N3 ranks exact symbol matches, then search hits, then git history.
- Every ref stores `file_hash`; changed files make refs stale and trigger refresh.
- R7 sends to N9 when `tokens_used > 0.7 * window`.
- N9 keeps the system prompt, task, success criteria, all refs, and the last 6 messages; summarizes the rest.
- No wiki, no second symbol index, no embeddings. Serena is the only symbol source.

---

## 13. UI expectations

- Textual app with header, transcript, input, footer.
- Tool cards, file chips, diff view, thinking blocks, plan tree, context panel, agents panel, error card, budget meter, approval modal, approval queue badge.
- Streaming text is throttled; do not render per token.
- `Ctrl+C` cancels a run once; twice quits. `Ctrl+Q` quits.
- Every status has icon **and** text.
- Core modules never import `rich` or `textual`.
- Plain mode uses `rich`; JSON mode prints one event per line.

---

## 14. Testing and commands

Normal gate:

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
uv run agent --help
```

Markers:

- `live` — real Ollama call, skipped by default.
- `docker` — Postgres integration.
- `mcp` — real Serena/MCP integration.
- `chaos` — injected failures/timeouts/loops.
- `evals` — eval subset.
- `expected_fail` — intentionally failing fixture until Phase 6 fixes it.

Testing rules:

- Use `ScriptedChatModel` from `tests/fakes.py`.
- Use `_env_file=None` for settings tests.
- Use `tmp_path` for paths and test-only git repos.
- Never touch the real keychain in tests.
- Test-only git operations may run in a throwaway temp directory outside this repository; never commit/tag/push this repository.

---

## 15. Windows-first notes

- Use `taskkill /T /F` to kill a process tree; process-group kill on POSIX.
- Use `Path.resolve()` and `is_relative_to()` for workspace escape checks.
- Skip symlink tests only when the OS denies symlink creation; `..` and absolute-path tests must still run.
- Do not assume `rg` exists. It is currently absent; Python `re` fallback must be tested.
- Docker Desktop with WSL2 is the expected Phase 8 setup.
- Do not include `ls`/`cat` in the shell allow-list; use native file tools.
- Keep path handling cross-platform even though development is Windows-first.

---

## 16. Environment snapshot

- Platform: Windows.
- System Python: `3.11.2`; use that. Do not install another Python.
- `uv 0.7.9`, `uvx` available.
- Docker CLI `29.5.3`; daemon currently not running.
- `git 2.40`; repository has no product commits yet.
- `rg` is not installed.
- `serena-agent 2.1.0` is the pinned Serena version.

Pinned baseline:

```text
langgraph 1.2.16
langgraph-checkpoint-postgres 3.2.0
langchain-core 1.6.13
langchain-ollama 1.1.0
langchain-mcp-adapters 0.3.2
textual 8.2.8
rich 15.0.0
typer 0.27.3
pydantic-settings 2.16.1
pytest 8.4.2
mypy 2.4.0
```

Phase 1.5 model-selection storage (locked):

```text
model_config.json  in data_dir — providers keyed map, models list,
                   selection.general + selection.roles (plan|code|summarize)
API keys           OS keyring (service "coding-agent", account "{provider}:api_key");
                   never plaintext in the JSON
Precedence         env (MODEL_* overrides; {PROVIDER}_API_KEY) > keyring > JSON
Runtime            Ollama-only; ensure_runtime_provider refuses others with ConfigError
Wizard providers   ollama / openai / anthropic / deepseek / custom (OpenAI-compatible base_url)
Dedup              (provider, model_id) pair; inheritance never invents a model
```

---

## 17. LangGraph/API traps

- `stream_mode=[...]`, `subgraphs=True`, `version="v2"`; handle `StreamPart`, not old tuples.
- `get_stream_writer()` raises outside a graph run; buffer instead.
- `interrupt(payload, response_schema=...)` is the modern form.
- `Interrupt.id` is the resume key; `interrupt_id` is deprecated.
- `Command(resume={interrupt_id: value})` for multiple pending interrupts.
- Never put UI IDs in the resume map.
- `AsyncPostgresSaver.from_conn_string(...)` is an async context manager.
- Do not use deprecated `tools_condition`; write `Ra` explicitly.
- Use `load_mcp_tools(session)` with a long-lived session.
- Use `astream` v2 for the single ordered TUI stream; do not mix in `stream_events` v3.
- Re-raise `GraphBubbleUp` / `GraphInterrupt` in broad exception handlers.
- `interrupt()` must not be inside a `try/except` that swallows graph control flow.
- A resumed node re-enters from its start; make pre-interrupt code idempotent and side-effect-free.

---

## 18. Things not to guess

- Do not invent a model name. Leave `MODEL_NAME` blank until the human fills it.
- Do not choose another provider. Ollama only.
- Do not add another database.
- Do not use `MultiServerMCPClient.get_tools()` per turn.
- Do not create a per-subagent thread.
- Do not make the approval queue the source of truth.
- Do not emit approval requests before `interrupt()`.
- Do not use a UI `request_id` as the resume key.
- Do not bypass H3 in `auto-safe` for risky tools.
- Do not let two writers edit the same workspace concurrently.
- Do not commit/tag/push this repository.

---

## 19. Next session

1. Read `implementation-plan-15-phases.md` section 0, section 2, and the Phase 1 section.
2. Open the diagram once and check the Phase 1 traceability row (none).
3. Implement **Phase 1 only** after the human approves.
4. Create `.env` with blank model variables and `.env.example`; do not fill in a model.
5. Run the Phase 1 gate, update `PHASE_LOG.md`, report changed files and exact results, then stop.

Current user actions still needed:

- Fill `MODEL_NAME` in `.env` after Phase 1 creates it.
- Start Docker Desktop before Phase 8.
- Review and approve the plan/diagram before implementation.

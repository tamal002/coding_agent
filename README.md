# agent

A local-first coding agent built on:

- LangGraph
- Ollama
- Textual
- MCP (Serena and later)

## Install

Not yet. Phase 1 only scaffolding and configuration.

## Model selection (Phase 1.5)

```powershell
uv run agent model add           # provider → model id → API key (key prompt skipped for ollama)
uv run agent model list          # saved models + effective per-role usage
uv run agent model use           # set the general model
uv run agent model use plan      # override the plan role (also: code, summarize)
uv run agent model use plan --unset
uv run agent model remove
```

- Preferences live in `<data dir>\model_config.json`; keys live in the **OS keyring** (service `coding-agent`), never on disk.
- Env vars (`.env` `MODEL_*`, `{PROVIDER}_API_KEY`) override everything for CI/automation.
- Runtime is Ollama-only for now: non-Ollama selections are saved but refused at call time until the provider-extension phase.
- An unselected model makes LLM calls raise `ConfigError` — the agent never invents a model.

## Test

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
uv run agent --help
```

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workbench is a personal intelligence feed. It ingests from configurable sources, filters noise adaptively via a preference learning system, and triages items through interactive cards sent via the configured messenger.

Single-user tool. **Current state**: migrating to PostgreSQL + durable queues + YAML config + `src/workbench/` layout.

## Architecture

FastAPI server (Python) with PostgreSQL storage and a pluggable provider system. Content flows through durable ingestion and triage queues with LLM-based priority scoring.

The server does all heavy lifting. Clients are thin HTTP interfaces:
- **Claude Code plugin** -- slash commands wrapping API calls (no direct storage access)
- **MCP server** -- tool access from any MCP-compatible client
- **Messenger** -- primary user-facing surface for triage cards and responses

### Processing Pipeline

```
Source adapter (raw data) -> Ingestion queue (LLM urgency scoring) -> Queue worker -> LLM extraction -> Adaptive noise filter -> Context enrichment -> Triage card -> Triage queue -> Messenger -> User response -> Storage
```

### Provider Interfaces

All external integrations are behind pluggable interfaces: LLM, QueueScorer, DocReader, Messenger, SourceAdapter, ContextEnricher, MemoryLayer. Resolved from YAML config via dynamic import.

### Storage Layer

Repository pattern -- one interface per domain entity (ItemStore, TriageStore, IngestionQueueStore, etc.). PostgreSQL via asyncpg. Schema managed by Alembic migrations. Backend selected via YAML config.

## Development Commands

```bash
# Start services (docker compose)
make up

# Tail logs
make logs

# Dev server
make serve
```

## Project Structure

```
src/workbench/           -- Python package (importable as `workbench`)
src/workbench/__init__.py -- app version (__version__ = "0.1.0")
src/workbench/__main__.py -- `python -m workbench` entry (imports runtime.app)
src/workbench/domain/    -- entity vocabulary: pydantic models + enums (was models.py)
src/workbench/config/    -- config models, OmegaConf loader, ruamel write-back (was config.py/config_writer.py)
src/workbench/runtime/   -- ASGI app factory + app-level middleware (auth, correlation id); entrypoint runtime.app:app
src/workbench/telemetry/ -- emitted operational signals: metrics, logging, instrumentation, usage aggregation, alerting, log sanitizing
src/workbench/providers/ -- pluggable providers behind base interfaces + registry.py (Provider Registry);
                            subfolders llm/ (incl. plugboard.py), source/, messenger/, queue_scorer/,
                            enrichment/, connection/, change_detector/, doc_reader/, memory/ (MemoryLayer)
src/workbench/pipeline/  -- processing pipeline (extraction, filter, enrichment, triage, scheduler, worker, engine, presenter)
src/workbench/storage/   -- repository interfaces + PostgreSQL implementation (postgres/)
src/workbench/api/       -- REST API route modules + redaction.py (API-output Redaction Rule)
src/workbench/mcp/       -- MCP server and tool definitions
src/workbench/migrations/-- Alembic database migrations
plugin/                  -- Claude Code plugin (thin HTTP client with slash commands)
tests/                   -- test suite
config.example.yml       -- example YAML config (template)
```

The loose root modules and `models.py` are gone: every module now lives under a
layered subpackage (`domain/`, `config/`, `runtime/`, `telemetry/`, `providers/`,
`pipeline/`, `storage/`, `api/`, `mcp/`, `migrations/`). Only `__init__.py` and
`__main__.py` remain at the `src/workbench/` root.

### Per-package README convention

Every package directory under `src/workbench/` carries a `README.md` describing
its purpose and placement rule. When you add a new kind of code to a folder (a
new provider interface, a new cross-cutting concern), update that folder's
`README.md`. `tests/test_folder_docs.py` enforces presence (every package dir
except `__pycache__` and the Alembic-generated `migrations/versions/` must have a
non-empty README).

## Design Decisions

- PostgreSQL as primary storage backend. Pluggable via repository pattern.
- Durable ingestion + triage queues with LLM-based priority scoring. Dedicated QueueScorer interface.
- `src/workbench/` package layout with independent app and config versions (both semver).
- YAML config with OmegaConf for env var interpolation and typed ProviderConfig validation.
- Alembic for schema migrations.
- Bearer token auth on all endpoints except `/health`.
- Plugin is a pure HTTP client -- all reads/writes go through the server API, never direct to storage.
- Adaptive noise filter uses LLM judgment against natural language patterns, not regex.
- Enrichment has configurable depth (shallow/deep) with budget controls and trace logging.
- Triage cards are source-type-specific with actionable options, not simple yes/no.
- All provider subprocess calls use `asyncio.create_subprocess_exec` (not `subprocess.run`).
- `/health` is unauthenticated, returns 503 on PG failure, includes app version and queue stats.

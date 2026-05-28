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
# Start services
podman compose up -d

# Tail logs
podman compose logs -f

# Dev server
uvicorn workbench.main:app --host 0.0.0.0 --port 8421 --reload
```

## Project Structure

```
src/workbench/           -- Python package (importable as `workbench`)
src/workbench/__init__.py -- app version (__version__ = "0.1.0")
src/workbench/main.py    -- FastAPI app entrypoint
src/workbench/config.py  -- YAML config loader (OmegaConf + pydantic validation)
src/workbench/models.py  -- Pydantic domain models
src/workbench/storage/   -- repository interfaces + PostgreSQL implementation
src/workbench/pipeline/  -- processing pipeline (extraction, filter, enrichment, triage, scheduler)
src/workbench/memory/    -- memory layer interface + implementations
src/workbench/providers/ -- pluggable providers (llm/, queue_scorer/, doc_reader/, messenger/, source/, enrichment/)
src/workbench/mcp/       -- MCP server and tool definitions
src/workbench/api/       -- REST API route modules
src/workbench/migrations/-- Alembic database migrations
plugin/                  -- Claude Code plugin (thin HTTP client with slash commands)
tests/                   -- test suite
config.example.yml       -- example YAML config (template)
```

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

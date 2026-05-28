# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workbench is a Meta-internal personal intelligence feed. It ingests from internal sources (Phabricator diffs, Tasks, Workplace, calendar, SEVs, oncall, email), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Google Chat.

Single-user tool for personal work use. Not open source.

**Current state**: Phase 1a partially implemented (SQLite-based). Migrating to PostgreSQL + durable queues + YAML config + `src/workbench/` layout. See ADRs 0006-0008.

## Architecture

FastAPI server (Python) with PostgreSQL storage (single instance, two databases: `workbench` + `zep`) and Zep memory layer for knowledge graph and preference learning. All services run via Podman Compose on the devgpu. OnDemands connect over the network. Content flows through durable ingestion and triage queues with LLM-based priority scoring.

The server does all heavy lifting. Clients are thin HTTP interfaces:
- **Claude Code plugin** — slash commands wrapping API calls (no direct storage access)
- **MCP server** — tool access from any MCP-compatible client
- **Google Chat** — primary user-facing surface for triage cards and responses

### Processing Pipeline

```
Source adapter (raw data) → Ingestion queue (LLM urgency scoring) → Queue worker → LLM extraction → Adaptive noise filter → Context enrichment → Rich triage card → Triage queue → Google Chat → User response → Storage + Zep
```

### Provider Interfaces

All external integrations are behind pluggable interfaces: LLM (Claude API), QueueScorer, DocReader, Messenger (Google Chat), SourceAdapter, ContextEnricher. Resolved from YAML config via dynamic import (ADR 0005).

### Storage Layer

Repository pattern — one interface per domain entity (ItemStore, TriageStore, IngestionQueueStore, etc.). PostgreSQL via asyncpg as the only Phase 1 backend. Schema managed by Alembic migrations. Backend selected via YAML config.

### Data Model

Single-user, no multi-tenant complexity. All data belongs to one user.

## Key Files

- `docs/specs/2026-05-21-workbench-design.md` — full design spec (architecture, storage layer, API endpoints, pipeline stages, triage card formats)
- `docs/specs/2026-05-27-zep-memory-layer-design.md` — Zep memory layer integration spec
- `docs/plans/` — implementation plans (to be written)
- `docs/plans/_stale/` — old step specs from prior design, kept as reference

## Development Commands

```bash
# Start all services (Workbench + Zep + PostgreSQL)
podman compose up -d

# Tail logs
podman compose logs -f

# Development (Workbench only, no Zep)
uvicorn workbench.main:app --host 0.0.0.0 --port 8421 --reload
```

## Project Structure

```
docs/                    — all documentation
docs/specs/              — design specs (main spec + Zep spec)
docs/plans/              — implementation plans and step specs
docs/adr/                — architectural decision records
src/workbench/           — Python package (importable as `workbench`)
src/workbench/__init__.py — app version (__version__ = "0.1.0")
src/workbench/main.py    — FastAPI app entrypoint
src/workbench/config.py  — YAML config loader (OmegaConf + pydantic validation)
src/workbench/models.py  — Pydantic domain models
src/workbench/storage/   — repository interfaces + PostgreSQL implementation
src/workbench/pipeline/  — processing pipeline (extraction, filter, enrichment, triage, scheduler)
src/workbench/memory/    — Zep memory layer (MemoryLayer interface + implementations)
src/workbench/providers/ — pluggable providers (llm/, queue_scorer/, doc_reader/, messenger/, source/, enrichment/)
src/workbench/mcp/       — MCP server and tool definitions
src/workbench/api/       — REST API route modules
src/workbench/migrations/— Alembic database migrations
plugin/                  — Claude Code plugin (thin HTTP client with slash commands)
tests/                   — test suite
config.example.yml       — example YAML config (template)
```

## Design Decisions

- PostgreSQL as only Phase 1 storage backend. Single instance, two databases (workbench + zep). See ADR 0006.
- Durable ingestion + triage queues with LLM-based priority scoring. Dedicated QueueScorer interface. See ADR 0007.
- `src/workbench/` package layout. Independent app version and config version (both semver). See ADR 0008.
- YAML config with OmegaConf for env var interpolation and typed ProviderConfig validation. See ADR 0005.
- Pluggable storage via repository pattern. Alembic for schema migrations.
- Bearer token auth on all endpoints except `/health`.
- Plugin is a pure HTTP client — all reads/writes go through the server API, never direct to storage.
- Adaptive noise filter uses LLM judgment against natural language patterns, not regex.
- Preference learning via Zep knowledge graph: triage responses → auto-extracted facts → queried at scoring time. Replaces hand-rolled 3-layer synthesis. See ADR 0004.
- Enrichment has configurable depth (shallow/deep) with budget controls and trace logging.
- Triage cards are source-type-specific with actionable options, not simple yes/no.
- Claude API (Anthropic) as the LLM provider.
- Google Chat as the messenger. See ADR 0001.
- All provider subprocess calls use `asyncio.create_subprocess_exec` (not `subprocess.run`).
- `/health` is unauthenticated, returns 503 on PG failure, includes app version and queue stats.

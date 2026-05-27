# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workbench is a Meta-internal personal intelligence feed. It ingests from internal sources (Phabricator diffs, Tasks, Workplace, calendar, SEVs, oncall, email), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Google Chat.

Single-user tool for personal work use. Not open source.

**Current state**: Pre-implementation. Specs and plans exist; no source code yet.

## Architecture

FastAPI server (Python) with pluggable storage (SQLite / XDB / PostgreSQL) and Zep memory layer for knowledge graph and preference learning. All services run via Podman Compose on the devgpu. OnDemands connect over the network.

The server does all heavy lifting. Clients are thin HTTP interfaces:
- **Claude Code plugin** — slash commands wrapping API calls (no direct storage access)
- **MCP server** — tool access from any MCP-compatible client
- **Google Chat** — primary user-facing surface for triage cards and responses

### Processing Pipeline

```
Source adapter (raw data) → LLM extraction (Claude API) → Adaptive noise filter → Context enrichment → Rich triage card → Google Chat → User response → Storage + Zep
```

### Provider Interfaces

All external integrations are behind pluggable interfaces: LLM (Claude API), DocReader, Messenger (Google Chat), SourceAdapter, ContextEnricher.

### Storage Layer

Repository pattern — one interface per domain entity (ItemStore, TriageStore, PreferenceStore, etc.). Implementations for XDB (default), SQLite, and PostgreSQL. Backend selected via config.

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
uvicorn server.main:app --host 0.0.0.0 --port 8421 --reload
```

## Planned Project Structure

```
docs/            — all documentation
docs/specs/      — design specs (main spec + Zep spec)
docs/plans/      — implementation plans and step specs
docs/adr/        — architectural decision records
server/          — FastAPI app, API routes
server/storage/  — pluggable storage layer (base interfaces + xdb/sqlite/postgres implementations)
server/pipeline/ — processing pipeline (extraction, filter, enrichment, triage, scheduler)
server/memory/   — Zep memory layer (MemoryLayer interface + implementations)
server/providers/— pluggable provider implementations (llm/, doc_reader/, messenger/, source/, enrichment/)
server/mcp/      — MCP server and tool definitions
server/api/      — REST API route modules
plugin/          — Claude Code plugin (thin HTTP client with slash commands)
tests/           — test suite
```

## Design Decisions

- Pluggable storage via repository pattern. XDB (MySQL) as default for shared state across devservers/ODs. SQLite for dev/testing. PostgreSQL as option.
- No auth layer — single-user tool on a devserver, server trusts all requests.
- Plugin is a pure HTTP client — all reads/writes go through the server API, never direct to storage.
- Adaptive noise filter uses LLM judgment against natural language patterns, not regex.
- Preference learning via Zep knowledge graph: triage responses → auto-extracted facts → queried at scoring time. Replaces hand-rolled 3-layer synthesis.
- Enrichment has configurable depth (shallow/deep) with budget controls and trace logging.
- Triage cards are source-type-specific with actionable options, not simple yes/no.
- Claude API (Anthropic) as the LLM provider.
- Google Chat as the messenger.

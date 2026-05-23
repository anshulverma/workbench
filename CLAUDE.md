# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workbench is an open-source personal intelligence feed. It ingests from multiple sources (email, meeting notes, tasks, code reviews, social feeds), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Messenger (WhatsApp/Discord/Google Chat).

**Current state**: Pre-implementation. Specs and plans exist; no source code yet.

## Architecture

FastAPI server (Python) + PostgreSQL, deployed via docker-compose. Three containers: `workbench-server` (API + MCP + pipeline + scheduler), `workbench-db` (PostgreSQL), and optionally `workbench-worker` (background tasks).

The server does all heavy lifting. Clients are thin:
- **Claude Code plugin** — slash commands wrapping API calls
- **MCP server** — tool access from any MCP-compatible client
- **Webapp** (Phase 2) and **Mobile apps** (Phase 3) planned later

### Processing Pipeline

```
Source adapter (raw data) → LLM extraction → Adaptive noise filter → Context enrichment → Rich triage card → Messenger → User response → Database
```

### Provider Interfaces

All external integrations are behind pluggable interfaces, configured per-workspace: LLM (Claude/OpenAI/Ollama), DocReader, WorkbenchStore (export), Messenger, SourceAdapter, ContextEnricher.

### Multi-Tenant Data Model

Users ↔ Workspaces (many-to-many with roles). Each workspace has isolated sources, filters, preferences, items, plans, and enrichment settings. Token-based auth.

## Key Files

- `specs/2026-05-21-workbench-design.md` — full design spec (architecture, data model, API endpoints, DB schema, pipeline stages, triage card formats)
- `plans/phase-1-plan.md` — Phase 1 implementation sequence

## Development Commands

```bash
# Start the stack
docker-compose up

# Run the server (once implemented)
# FastAPI app entrypoint: server/main.py

# Database migrations (Alembic)
# alembic upgrade head
```

## Planned Project Structure

```
server/          — FastAPI app, models, migrations, API routes
server/pipeline/ — processing pipeline (extraction, filter, enrichment, triage, preferences, scheduler)
server/providers/— pluggable provider implementations (llm/, doc_reader/, messenger/, source/, enrichment/)
server/mcp/      — MCP server and tool definitions
server/api/      — REST API route modules
plugin/          — Claude Code plugin (thin API client with slash commands)
tests/           — test suite
```

## Design Decisions

- PostgreSQL from day one (no flat file storage for state).
- Adaptive noise filter uses LLM judgment against natural language patterns, not regex.
- Preference learning has three layers: interaction log (append-only) → synthesized preference summary → informed pipeline decisions.
- Enrichment has configurable depth (shallow/deep) with per-workspace budget controls and trace logging.
- Triage cards are source-type-specific with actionable options, not simple yes/no.
- Docker-compose compatible with Podman.

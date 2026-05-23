# Workbench Phase 1 — Implementation Plan

## Context

Build the server, database, Claude Code plugin, and MCP server for a personal intelligence feed. Ingests from multiple pluggable sources (email, meeting notes, social feeds, tasks, code reviews), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Messenger (WhatsApp/Discord/Google Chat).

Full spec at: `specs/2026-05-21-workbench-design.md`

## Key Decisions

- **Architecture**: FastAPI server does all heavy lifting (pipeline, LLM calls, scheduling). Clients are thin.
- **Multi-tenant**: Users ↔ Workspaces (many-to-many with roles). All data is workspace-scoped.
- **Deployment**: docker-compose with three containers: `workbench-server`, `workbench-db`, optional `workbench-worker`
- **Auth**: Token-based. Plugin and MCP server store the token in config.
- **Provider interfaces**: LLM (Claude/OpenAI/Ollama), DocReader, WorkbenchStore, Messenger, SourceAdapter, ContextEnricher — all pluggable, configured per-workspace
- **Filter**: Adaptive noise filter with 3-layer preference learning (interaction log → preference summary → informed decisions). LLM judgment, not regex.
- **Triage**: Rich source-type-specific triage cards with actionable options, sent via Messenger
- **Enrichment**: Configurable depth (shallow/deep) with per-workspace budget controls and trace logging
- **Scheduler**: Server-side background scheduler (APScheduler) replaces crons
- **Database**: PostgreSQL from day one

## Implementation Sequence

### 1. Docker stack

- `server/Dockerfile` — FastAPI server image
- `server/docker-compose.yml` — three-container stack (server, PostgreSQL, optional worker)
- `server/requirements.txt` — Python dependencies
- Verify: `docker-compose up` starts all containers

### 2. Database schema and models

- `server/models/` — SQLAlchemy models for all tables:
  - Core: `users`, `workspaces`, `workspace_members`
  - Per-workspace: `items`, `plans`, `triage_cards`, `interaction_log`, `filter_rules`, `email_filters`, `preferences`, `enrichment_trace`, `processed`, `source_configs`, `workspace_config`
- `server/migrations/` — Alembic migrations for all tables
- `server/config.py` — server configuration (DB URL, secrets, defaults)
- Verify: `alembic upgrade head` creates all tables

### 3. Auth endpoints

- `server/api/auth.py`:
  - `POST /auth/register` — create user account
  - `POST /auth/login` — get API token
  - `POST /auth/token` — generate API token for plugin/MCP
- Verify: register user, login, use token for authenticated requests

### 4. Workspace management endpoints

- `server/api/workspaces.py`:
  - `POST /workspaces` — create workspace
  - `GET /workspaces` — list user's workspaces
  - `GET /workspaces/{id}` — workspace details
  - `PATCH /workspaces/{id}` — update workspace config
  - `POST /workspaces/{id}/members` — add member
  - `DELETE /workspaces/{id}/members/{user_id}` — remove member
- Verify: create two workspaces, confirm data isolation

### 5. Provider interfaces (base classes)

- `server/providers/llm/base.py` — LLM provider interface (`extract`, `score_relevance`, `generate_triage_card`, `synthesize_preferences`)
- `server/providers/doc_reader/base.py` — DocReader interface
- `server/providers/doc_export/base.py` — WorkbenchStore interface
- `server/providers/messenger/base.py` — Messenger interface (bidirectional)
- `server/providers/source/base.py` — SourceAdapter interface
- `server/providers/enrichment/base.py` — ContextEnricher interface

### 6. Provider implementations

- LLM: `server/providers/llm/claude.py`, `openai.py`, `ollama.py`
- DocReader: `server/providers/doc_reader/google_docs.py`, `notion.py`, `raw_url.py`
- Export: `server/providers/doc_export/google_docs.py`, `notion.py`
- Messenger: `server/providers/messenger/whatsapp.py`, `discord.py`, `google_chat.py`
- Source adapters: `server/providers/source/email_gmail.py` (full implementation), `meetings_stub.py`, `social_stub.py`, `tasks_stub.py`, `code_review_stub.py` (stubs)
- Enrichment: `server/providers/enrichment/stub.py`

### 7. Processing pipeline

- `server/pipeline/engine.py` — pipeline orchestration
- `server/pipeline/extraction.py` — LLM extraction (raw text → structured items)
- `server/pipeline/filter.py` — adaptive noise filter (relevance + confidence scoring, threshold logic, filter rules matching)
- `server/pipeline/enrichment.py` — context enrichment (depth, budget, trace logging)
- `server/pipeline/triage.py` — rich triage card generation (source-type-specific)
- `server/pipeline/preferences.py` — preference synthesis (incremental cursor-based digest → LLM summary)

### 8. API endpoints (items, triage, plans, preferences, filter rules, interactions, enrichment, sources, export, config, health)

- `server/api/items.py` — `GET /workspaces/{id}/items`, `PATCH .../items/{item_id}`, `DELETE .../items/{item_id}`
- `server/api/triage.py` — `GET .../triage/pending`, `POST .../triage/respond`
- `server/api/plans.py` — `POST .../plans`, `GET .../plans`, `PATCH .../plans/{plan_id}`
- `server/api/preferences.py` — `GET .../preferences`, `GET .../preferences/digest`
- `server/api/filter_rules.py` — `GET .../filter-rules`, `POST .../filter-rules`, `GET .../filter-rules/email/{account}`
- `server/api/interactions.py` — `GET .../interactions` (cursor-based pagination)
- `server/api/enrichment.py` — `GET .../enrichment/trace`
- `server/api/sources.py` — `GET .../sources`, `POST .../sources`, `PATCH .../sources/{source_id}`, `DELETE .../sources/{source_id}`
- `server/api/export.py` — `POST .../export`
- `server/api/config.py` — `GET .../config`, `PATCH .../config`
- `server/api/health.py` — `GET /health`
- `server/main.py` — FastAPI app entrypoint, mounts all routers

### 9. Server-side scheduler

- `server/pipeline/scheduler.py` — background scheduler (APScheduler or similar):
  - Poll each workspace's enabled source adapters on their configured schedule
  - Check Messenger channels for triage responses
  - Daily cleanup: archive completed items, flag stale items, regenerate preferences, re-export Dashboard
- Schedules are per-workspace and configurable via API

### 10. MCP server

- `server/mcp/server.py` — MCP server implementation
- `server/mcp/tools.py` — MCP tool definitions:
  - `workbench_process` — submit content for processing
  - `workbench_items` — list/filter items
  - `workbench_triage_pending` — list pending triage items
  - `workbench_triage_respond` — respond to a triage card
  - `workbench_status` — workspace status and health
  - `workbench_plans` — list/create/update plans
  - `workbench_sources` — manage source adapters

### 11. Claude Code plugin (thin client)

- `plugin/.claude-plugin/plugin.json` — plugin manifest
- `plugin/commands/process.md` — `/process <text or doc link>`: POST to `/workspaces/{id}/process`
- `plugin/commands/setup.md` — `/workbench:setup`: start containers, register user, configure workspace
- `plugin/commands/status.md` — `/workbench:status`: GET `/health` + workspace status
- `plugin/commands/triage.md` — `/workbench:triage`: interactive CLI triage via API
- `plugin/commands/sources.md` — `/workbench:sources`: manage sources via API
- `plugin/config/config.json` — server URL, API token, default workspace ID

### 12. End-to-end testing

- `tests/test_pipeline.py` — pipeline stage tests
- `tests/test_api.py` — API endpoint tests
- `tests/test_providers.py` — provider interface tests
- `tests/test_filter.py` — filter and preference learning tests
- `tests/test_preferences.py` — preference synthesis tests

## Verification

1. `docker-compose up` — server and DB start, migrations run
2. Create user + workspace via API — verify auth works
3. Configure Gmail source for workspace — verify credentials stored
4. `POST /workspaces/{id}/process` with pasted text — triage card sent via Messenger
5. Respond to triage card — item appears in DB with correct priority
6. `POST /workspaces/{id}/process` with Google Doc link — doc fetched and processed
7. Wait for server-side scheduler — verify it polls sources and processes new items
8. "Never" response — filter rule created in DB for the workspace
9. Verify second workspace has independent items, filters, preferences
10. Connect via MCP — verify tools work (`workbench_process`, `workbench_items`, etc.)
11. `/workbench:setup` from Claude Code — containers start, plugin configured
12. `/process` from Claude Code — delegates to server, triage card sent
13. Check enrichment trace — budget settings respected
14. Preferences digest — incremental cursor-based read works

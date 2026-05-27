# Workbench Phase 1 — Implementation Plan

## Context

Build the server, storage layer, Claude Code plugin, and MCP server for a Meta-internal personal intelligence feed. Ingests from internal sources (Phabricator diffs, Tasks, Workplace, calendar, SEVs, oncall, email), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Google Chat.

Single-user tool running on devgpu, accessible from OnDemands.

Full spec at: `specs/2026-05-21-workbench-design.md`

## Key Decisions

- **Architecture**: FastAPI server does all heavy lifting (pipeline, LLM calls, scheduling). Clients are thin HTTP interfaces.
- **Single-user**: No multi-tenant user/workspace management. No auth layer.
- **Deployment**: FastAPI process on devgpu. OnDemands connect over the network.
- **Storage**: Pluggable via repository pattern. XDB (MySQL) as default, SQLite and PostgreSQL as alternatives.
- **LLM**: Claude API (Anthropic).
- **Messenger**: Google Chat.
- **Sources**: Phabricator, Tasks, Workplace, Calendar, SEVs, Oncall, Email — all Meta-internal.
- **Plugin**: Thin HTTP client only. All operations go through the server API.
- **Provider interfaces**: LLM, DocReader, Messenger, SourceAdapter, ContextEnricher — all pluggable.
- **Filter**: Adaptive noise filter with 3-layer preference learning (interaction log → preference summary → informed decisions). LLM judgment, not regex.
- **Triage**: Rich source-type-specific triage cards with actionable options, sent via Google Chat.
- **Enrichment**: Configurable depth (shallow/deep) with budget controls and trace logging.
- **Scheduler**: Server-side background scheduler (APScheduler) for source polling.

## Implementation Sequence

### 1. Server skeleton

- `server/main.py` — FastAPI app entrypoint
- `server/config.py` — server configuration (storage backend, Claude API key, Google Chat config, port, etc.)
- `server/requirements.txt` — Python dependencies
- Verify: `python server/main.py` starts, `GET /health` returns OK

### 2. Storage layer (interfaces + SQLite)

- `server/storage/base.py` — all repository interfaces (ItemStore, TriageStore, PlanStore, PreferenceStore, InteractionStore, FilterRuleStore, EnrichmentTraceStore, SourceConfigStore, ProcessedStore, ConfigStore)
- `server/storage/factory.py` — backend selection from config
- `server/storage/sqlite/` — SQLite implementation of all stores
- Verify: unit tests pass against SQLite backend

### 4. Provider interfaces (base classes)

- `server/providers/llm/base.py` — LLM provider interface (`extract`, `score_relevance`, `generate_triage_card`, `synthesize_preferences`)
- `server/providers/doc_reader/base.py` — DocReader interface
- `server/providers/messenger/base.py` — Messenger interface (bidirectional)
- `server/providers/source/base.py` — SourceAdapter interface
- `server/providers/enrichment/base.py` — ContextEnricher interface

### 5. Provider implementations

- LLM: `server/providers/llm/claude.py` — Anthropic Claude API
- DocReader: `server/providers/doc_reader/google_docs.py`
- Messenger: `server/providers/messenger/google_chat.py`
- Source adapters: `server/providers/source/phabricator.py` (Conduit API), `email.py` (Gmail via Google API proxy) — Phase 1 only
- Enrichment: `server/providers/enrichment/meta.py` (Meta-internal), `stub.py` (testing)

### 6. Processing pipeline

- `server/pipeline/engine.py` — pipeline orchestration
- `server/pipeline/extraction.py` — LLM extraction (raw text → structured items)
- `server/pipeline/filter.py` — adaptive noise filter (relevance + confidence scoring, threshold logic, filter rules matching)
- `server/pipeline/enrichment.py` — context enrichment (depth, budget, trace logging)
- `server/pipeline/triage.py` — rich triage card generation (source-type-specific)
- `server/pipeline/preferences.py` — preference synthesis (incremental cursor-based digest → LLM summary)

### 7. API endpoints

- `server/api/items.py` — `GET /api/items`, `PATCH /api/items/{item_id}`, `DELETE /api/items/{item_id}`
- `server/api/triage.py` — `GET /api/triage/pending`, `POST /api/triage/respond`
- `server/api/plans.py` — `POST /api/plans`, `GET /api/plans`, `PATCH /api/plans/{plan_id}`
- `server/api/preferences.py` — `GET /api/preferences`, `GET /api/preferences/digest`
- `server/api/filter_rules.py` — `GET /api/filter-rules`, `POST /api/filter-rules`, `GET /api/filter-rules/{source_type}`
- `server/api/interactions.py` — `GET /api/interactions` (cursor-based pagination)
- `server/api/enrichment.py` — `GET /api/enrichment/trace`
- `server/api/sources.py` — `GET /api/sources`, `POST /api/sources`, `PATCH /api/sources/{source_id}`, `DELETE /api/sources/{source_id}`
- `server/api/config.py` — `GET /api/config`, `PATCH /api/config`
- `server/api/health.py` — `GET /health`
- `server/main.py` — mounts all routers

### 8. Server-side scheduler

- `server/pipeline/scheduler.py` — background scheduler (APScheduler or similar):
  - Poll each enabled source adapter on its configured schedule
  - Check Google Chat for triage responses
  - Daily cleanup: archive completed items, flag stale items, regenerate preferences

### 9. MCP server

- `server/mcp/server.py` — MCP server implementation
- `server/mcp/tools.py` — MCP tool definitions:
  - `workbench_process` — submit content for processing
  - `workbench_items` — list/filter items
  - `workbench_triage_pending` — list pending triage items
  - `workbench_triage_respond` — respond to a triage card
  - `workbench_status` — server status and health
  - `workbench_plans` — list/create/update plans
  - `workbench_sources` — manage source adapters

### 10. Claude Code plugin (thin HTTP client)

- `plugin/.claude-plugin/plugin.json` — plugin manifest
- `plugin/commands/process.md` — `/process <text or doc link>`: POST to `/api/process`
- `plugin/commands/setup.md` — `/workbench:setup`: configure server URL
- `plugin/commands/status.md` — `/workbench:status`: GET `/health` + dashboard summary
- `plugin/commands/triage.md` — `/workbench:triage`: interactive CLI triage via API
- `plugin/commands/sources.md` — `/workbench:sources`: manage sources via API
- `plugin/config/config.json` — server URL (e.g., `http://devgpu:8421`)

### 11. End-to-end testing

- `tests/test_pipeline.py` — pipeline stage tests
- `tests/test_api.py` — API endpoint tests
- `tests/test_storage.py` — storage layer tests (run against each backend)
- `tests/test_filter.py` — filter and preference learning tests
- `tests/test_preferences.py` — preference synthesis tests

## Verification

1. Start server on devgpu — `python server/main.py` runs, `/health` returns OK
2. From an OnDemand, `curl http://devgpu:8421/health` — server is reachable
3. `POST /api/process` with pasted text — triage card sent via Google Chat
4. Respond to triage card in Google Chat — item appears in storage with correct priority
5. Configure Phabricator source — verify diffs needing review are ingested
6. Wait for scheduler — verify it polls sources and processes new items
7. "Never" response — filter rule created in storage
8. Connect via MCP — verify tools work (`workbench_process`, `workbench_items`, etc.)
9. `/workbench:setup` from Claude Code — plugin configured with server URL
10. `/process` from Claude Code — delegates to server, triage card sent to Google Chat
11. Switch storage backend to SQLite — verify same behavior
12. Check enrichment trace — budget settings respected
13. Preferences digest — incremental cursor-based read works

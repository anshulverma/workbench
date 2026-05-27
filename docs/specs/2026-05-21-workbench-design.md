# Workbench — Personal Intelligence Feed

## Context

Meeting notes, emails, Workplace posts, tasks, diffs, and oncall alerts generate a constant stream of information that requires manual triage. Workbench is a Meta-internal tool that ingests from internal sources, filters noise adaptively, and maintains a prioritized dashboard of action items, draft plans, and meetings to schedule — so that opening one view gives a clear picture of what needs attention.

Single-user tool, running on a devserver, accessible from any OnDemand.

## Scope

Server + storage + Claude Code plugin + MCP server. Two user-facing surfaces:

1. **Google Chat** — triage cards, responses, daily morning briefing
2. **Claude Code plugin / MCP** — on-demand queries and dashboard view from the terminal

No webapp for now. If a richer visual dashboard is needed later, build a Nest app (not Unidash — Unidash is for analytics data sources, not custom APIs).

## Architecture

```
┌──────────────┐ ┌────────────┐
│ Claude Code  │ │ MCP Client │
│ Plugin       │ │            │
└──────┬───────┘ └─────┬──────┘
       │               │
       └───────┬───────┘
               │ HTTP / MCP protocol
              ┌▼─────────────────┐
              │  Workbench       │
              │  Server          │
              │  (FastAPI)       │
              ├──────────────────┤
              │  Pipeline        │  ← Source polling, LLM extraction,
              │  Engine          │    filtering, triage, enrichment
              ├──────────────────┤
              │  LLM Provider    │  ← Claude API (Anthropic)
              ├──────────────────┤
              │  Messenger       │  ← Google Chat
              ├──────────────────┤
              │  Source Adapters  │  ← Phabricator, Tasks, Workplace,
              │                  │    Calendar, SEVs, Oncall, Email
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │  Storage Layer   │
              │  (pluggable)     │
              │                  │
              │  XDB / SQLite /  │
              │  PostgreSQL      │
              └──────────────────┘
```

The server does all heavy lifting: source polling, LLM calls for extraction/filtering/triage, enrichment, preference synthesis, and Google Chat communication. Clients are thin HTTP interfaces to the API:

- **Claude Code plugin** (Phase 1) — slash commands wrapping API calls. All reads and writes go through the server. No direct storage access.
- **MCP server** (Phase 1) — tool access from any MCP-compatible client

## Deployment

All services run via Podman Compose on the devgpu. OnDemands connect to the Workbench server over the network.

- **Workbench server**: FastAPI app (API + MCP server + pipeline engine + scheduler)
- **Zep server**: Self-hosted memory layer (knowledge graph, fact extraction)
- **Zep PostgreSQL**: PostgreSQL + pgvector for Zep's storage
- **Storage**: SQLite initially (local file, fast iteration). XDB later for shared state across devservers/ODs.
- **Process management**: systemd user service running `podman compose`. Survives logout, auto-restarts on crash, starts on boot.

```bash
# Start all services
podman compose up -d

# Tail logs
podman compose logs -f

# Production: managed by systemd
systemctl --user start workbench
systemctl --user enable workbench
journalctl --user -u workbench -f
```

```ini
# ~/.config/systemd/user/workbench.service
[Unit]
Description=Workbench Intelligence Feed Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/anshulverma/workspace/workbench
ExecStart=/usr/bin/podman compose up
ExecStop=/usr/bin/podman compose down
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

See `docs/specs/2026-05-27-zep-memory-layer-design.md` for the full Zep integration spec and docker-compose.yml.

## Data Model

Single-user tool. No multi-tenant user/workspace management. All data belongs to the one user.

Configuration is stored alongside the data in the storage layer:
- Source adapter configurations
- Feed polling schedules
- Filter rules
- Interaction log (Zep handles preference learning)
- Items, plans, triage cards
- Enrichment settings and trace log
- Google Chat configuration

## Storage Layer

All persistence is behind a **repository pattern** — one interface per domain entity. The server code never touches SQL or storage-specific APIs directly.

### Repository Interfaces

```python
class ItemStore(ABC):
    async def get_items(self, filters: ItemFilters) -> list[Item]: ...
    async def get_item(self, item_id: str) -> Item | None: ...
    async def save_item(self, item: Item) -> Item: ...
    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item: ...
    async def archive_item(self, item_id: str) -> None: ...

class TriageStore(ABC):
    async def get_pending(self) -> list[TriageCard]: ...
    async def save_card(self, card: TriageCard) -> TriageCard: ...
    async def record_response(self, card_id: str, response: TriageResponse) -> None: ...

class PlanStore(ABC):
    async def get_plans(self, filters: PlanFilters) -> list[Plan]: ...
    async def save_plan(self, plan: Plan) -> Plan: ...
    async def update_plan(self, plan_id: str, updates: PlanUpdate) -> Plan: ...

    # PreferenceStore removed — replaced by Zep MemoryLayer

class InteractionStore(ABC):
    async def append(self, entry: InteractionEntry) -> None: ...
    async def get_since(self, cursor: int, limit: int) -> list[InteractionEntry]: ...
    async def count(self) -> int: ...

class FilterRuleStore(ABC):
    async def get_rules(self) -> list[FilterRule]: ...
    async def add_rule(self, rule: FilterRule) -> FilterRule: ...
    async def get_source_rules(self, source_type: str) -> list[FilterRule]: ...

class EnrichmentTraceStore(ABC):
    async def log_trace(self, trace: EnrichmentTrace) -> None: ...
    async def get_traces(self, filters: TraceFilters) -> list[EnrichmentTrace]: ...

class SourceConfigStore(ABC):
    async def get_sources(self) -> list[SourceConfig]: ...
    async def save_source(self, source: SourceConfig) -> SourceConfig: ...
    async def update_source(self, source_id: str, updates: SourceConfigUpdate) -> SourceConfig: ...
    async def delete_source(self, source_id: str) -> None: ...

class ProcessedStore(ABC):
    async def is_processed(self, source_type: str, source_id: str) -> bool: ...
    async def mark_processed(self, source_type: str, source_id: str) -> None: ...

class ConfigStore(ABC):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def get_all(self) -> dict[str, str]: ...
```

### Implementations

| Backend | Module | Notes | Phase |
|---------|--------|-------|-------|
| SQLite | `server/storage/sqlite/` | Local file. Fast iteration, no provisioning. | **Phase 1** |
| XDB | `server/storage/xdb/` | MySQL via `db_locator`. Shared across devservers/ODs. | Phase 2 |
| PostgreSQL | `server/storage/postgres/` | Standard relational. If running alongside existing PG. | Phase 2 |

The active backend is selected via server config (`WORKBENCH_STORAGE_BACKEND=sqlite|xdb|postgres`, default `sqlite`).

### Schema

The logical schema is the same regardless of backend. Tables:

- `items` (id, source_type, source_id, summary, category, origin, priority, status, raw_data JSON, created_at, updated_at)
  - `category`: `action_item`, `meeting`, `informational` — groups items in the dashboard
  - `origin`: `auto_included`, `triaged`, `manual` — how the item entered the system
  - `status`: `active`, `done`, `archived`
- `plans` (id, title, status, content, sources JSON, created_at)
- `triage_cards` (id, item_id, card_content JSON, options JSON, sent_at, responded_at, response)
- `interaction_log` (id, timestamp, source_type, item_id, item_summary, triage_card_full JSON, enrichment_context JSON, options_presented JSON, option_chosen, todo_created JSON, enrichment_depth, enrichment_calls, enrichment_time_ms)
- `filter_rules` (id, source_type, pattern, action, priority, created_from_interaction_id)
- ~~`preferences`~~ — removed, replaced by Zep's knowledge graph
- `enrichment_trace` (id, item_id, depth, calls_made, time_ms, context_retrieved JSON, timestamp)
- `processed` (source_type, source_id, processed_at)
  - For poll-based sources, `source_id` is a composite key that includes modification state (e.g., `D12345_1748372400` for diffs). Each modification creates a new raw item so updates are surfaced. The raw item includes the original entity ID so the LLM has context about prior triage decisions.
- `source_configs` (id, adapter_type, config JSON, schedule, enabled, created_at)
- `jobs` (id, trigger, status, input_hash, items_extracted, items_included, items_triaged, items_dropped, items_failed, error, created_at, completed_at)
- `config` (key, value)

## Provider Interfaces

All external integrations are behind pluggable interfaces.

### LLM Provider

Claude API (Anthropic) for extraction, filtering, triage card generation, and preference synthesis. Accessed via Meta's Plugboard proxy using the standard `anthropic` Python SDK.

**Auth setup:**
- Base URL: `https://plugboard.x2p.facebook.net`
- mTLS cert: `/var/facebook/credentials/$USER/agent_x509/claude_code_$USER.pem`
- CA cert: `/var/facebook/rootcanal/ca.pem`
- API key: obtained via `/usr/local/bin/claude_code/api-key-helper` (rotated automatically)
- Uses Claude Code quota allocation

**Model:** Single model (Sonnet) for all stages to start. Model-per-stage configuration (e.g., Haiku for scoring, Sonnet for extraction) can be added later if cost is a concern.

| Implementation | Notes |
|---------------|-------|
| ClaudeProvider | Anthropic Python SDK via Plugboard proxy |

Each provider implements: `extract(raw_text) → structured items`, `score_relevance(item, preferences, rules) → (relevance, confidence)`, `generate_triage_card(item, enrichment) → card`, `synthesize_preferences(digest) → summary`.

### DocReader

Read content from Google Doc links submitted via `/api/process`.

| Implementation | Reads from |
|---------------|-----------|
| GoogleDocsReader | Google Docs URLs via Google API proxy |

### Messenger

Google Chat, bidirectional. The bot sends triage cards and polls for text responses. Uses `google_api.py` (from `fbcode/claude-templates`) with DCAT token auth — runs on a devserver with no fbcode deployment needed.

**Interaction model:**
- Bot sends a rich Card V2 with numbered options and openLink fallback buttons
- **Primary:** User types a number ("1", "2", "3") in the chat — bot polls via `list_messages()` and matches the reply to the current pending card
- **Fallback:** Each option is also an openLink button (URL hits `http://devgpu:8421/api/triage/respond?card_id=X&choice=N`) for click-to-respond
- Cards are sent **one at a time, sequentially** — no ambiguity about which card a reply targets
- "5 items to triage. Here's #1 of 5:" prefix for batch awareness
- User can type "skip all" or "skip remaining" to bail out of a sequence

**Why not interactive card buttons (postback)?** Postback callbacks require the PHP/WIB pipeline in WWW (Google Chat → Apps Script → Graph API → Iris queue → PHP handler). This conflicts with keeping all code outside fbcode.

| Implementation | Notes |
|---------------|-------|
| GoogleChatMessenger | `google_api.py` — send cards, poll responses via `list_messages()` |

### SourceAdapter

Poll internal Meta sources for new items, output raw data.

| Adapter | Notes | Phase |
|---------|-------|-------|
| PhabricatorAdapter | Via Conduit API (`differential.revision.search`). Fetches: (1) diffs authored by you — new comments, status changes, land notifications; (2) diffs where you're a direct reviewer; (3) diffs where you're a reviewer via project membership. Polls by `dateModified` to catch updates. | **Phase 1** |
| EmailAdapter | Gmail via Google API proxy / `google_api.py`. Polls entire inbox (no pre-filtering). The adaptive noise filter and preference learning system learn what matters over time and construct filter rules from triage responses. | **Phase 1** |
| TasksAdapter | Tasks assigned to you, tasks you're subscribed to | Phase 2 |
| WorkplaceAdapter | Workplace group posts, mentions, comments | Phase 2 |
| CalendarAdapter | Meeting notes, upcoming meetings needing prep | Phase 2 |
| SEVAdapter | SEVs you're involved in, SEV updates | Phase 2 |
| OncallAdapter | Oncall alerts, escalations during your rotation | Phase 2 |

Source adapters fetch **raw data only**. The LLM Provider does semantic extraction.

Note: The DocReader (GoogleDocsReader) handles Google Docs content in Phase 1 — it reads doc links submitted via `/api/process`, not by polling. It is a provider, not a source adapter, because docs don't have a polling model.

### ContextEnricher

Fetch additional context about referenced entities before triage. Uses internal Meta tools and APIs.

| Implementation | Notes |
|---------------|-------|
| MetaEnricher | Looks up people (org chart), tasks (parent/subtasks), diffs (related diffs, test results), SEVs (timeline, related SEVs) |
| StubEnricher | Default — returns empty context (for development/testing) |

**Depth setting** (config):
- `shallow` (default): Fetch only the directly referenced entity
- `deep`: Follow reference chains (task → parent → project → team → recent activity)

**Budget settings** (config):
- `max_api_calls_per_item`: default 3 (shallow), 15 (deep)
- `max_seconds_per_item`: default 10s (shallow), 60s (deep)
- `max_deep_items_per_run`: default 50

**Enrichment trace log**: Every call logged with item ID, depth, calls made, time, context retrieved.

## Processing Pipeline

All processing runs on the server. The pipeline is triggered by:
- **Server-side scheduler**: Periodic source polling
- **API call**: Manual processing via `/api/process`

```
Source adapter (raw data) → LLM extraction → Relevance filter → Context enrichment → Rich triage card → Google Chat → User response → Store
```

### Stage 1: Source Adapter

Server-side adapters poll configured internal sources and produce raw items. Default polling interval: **15 minutes**, configurable per source adapter.

```json
{
  "id": "source-specific-unique-id",
  "source_type": "diff|task|workplace|calendar|sev|oncall|email",
  "source_label": "D12345678 — Refactor auth middleware",
  "raw_text": "Full content from the source"
}
```

### Stage 2: LLM Extraction

Claude API reads raw text and extracts structured items: summary, action items, plan seeds, meetings to schedule.

**Error handling:** Each item is retried up to 3 times with exponential backoff (1s, 2s, 4s) on LLM failures (rate limits, timeouts, malformed responses). If still failing, the item is marked as failed and the pipeline continues with remaining items. The job's `items_failed` counter tracks failures. Failed items are retried on the next poll run.

### Stage 3: Adaptive Noise Filter

Every item gets two scores (0-100):
- **Relevance**: How likely this requires the user's action or attention.
- **Confidence**: How sure the system is about the relevance score.

**Thresholds** (configurable):
- Relevance >= 70 AND confidence >= 70 → auto-include
- Relevance < 30 AND confidence >= 70 → auto-drop (still logged)
- Everything else → send triage card via Google Chat

The filter reads `preferences` and `filter_rules` before scoring.

**Filter rules** are natural language patterns:

```json
{"pattern": "posts from Workplace group 'Infrastructure Announcements'", "action": "include", "priority": "P3"}
{"pattern": "CI bot comments on diffs", "action": "drop"}
{"pattern": "SEVs where I'm not oncall or directly involved", "action": "drop"}
```

The LLM matches incoming items against rules using judgment, not regex.

**Source-specific pre-filter**: Each source type can have its own filter rules table. Starts empty. Learns from triage responses.

### Stage 4: Context Enrichment

The ContextEnricher gathers additional information about referenced entities. Respects depth and budget settings. Results are attached to the triage card.

### Stage 5: Rich Triage Card

Every item gets a context-rich triage card sent via Google Chat. The card includes:
- Source-specific summary and context (LLM-generated)
- Enrichment results (who else is involved, related items, background)
- **Template-based options per source type** — fixed option structure, deterministic response mapping. The LLM generates the card summary and fills in context-sensitive details (e.g., the pattern for "never surface"), but the option set is hardcoded per source type. This makes response processing reliable — "1" always means the same action for a given source type.

**Diff triage card example:**
> **D12345678 needs your review — "Refactor auth middleware"**
> Author: @alice, 450 lines changed in fbcode/auth/middleware/
> [Enriched: related to T98765, 2 other reviewers assigned, all tests passing]
>
> **What do you want to do?**
> 1. Add review todo (P1)
> 2. Add review todo (P2)
> 3. Skip
> 4. Never surface diffs in auth/middleware/

**Task triage card:**
> **T98765 assigned to you — "Fix auth token expiry"**
> Assigned by @bob, priority P1, tagged: backend, auth
> [Enriched: parent task T98760 "Auth hardening Q3", 3 other subtasks]
>
> **What do you want to do?**
> 1. Add to Dashboard as P1
> 2. Change priority
> 3. Skip
> 4. Never surface tasks tagged "auth"

**Workplace triage card:**
> **@charlie mentioned you in "Infrastructure Migration Update"**
> Posted in Infrastructure Engineering group, 2h ago
>
> **Summary:** Charlie is asking TLs to review the migration timeline and flag blockers by EOW.
>
> **What do you want to do?**
> 1. Add todo: "Review migration timeline" (P1, due Friday)
> 2. Add todo: "Reply to Charlie"
> 3. Skip
> 4. Mute this Workplace group

**SEV triage card:**
> **SEV 54321 — "Auth service latency spike in PRN"**
> Status: Investigating, oncall: @dave, started 30min ago
> [Enriched: your team owns auth service, 3 related SEVs in past month]
>
> **What do you want to do?**
> 1. Track this SEV (P0)
> 2. Track this SEV (P1)
> 3. Skip — I'm not involved
> 4. Never surface SEVs for auth service unless I'm oncall

### Stage 6: Response Processing

When the user responds via Google Chat:
- The chosen action is executed (create todo, update priority, add plan, etc.)
- The full triage card + response is logged to the interaction log
- "Never"/"always" responses create filter rules
- The triage interaction is dual-written to the interaction log and Zep

## Preference Learning System

Powered by Zep's knowledge graph (see `docs/specs/2026-05-27-zep-memory-layer-design.md`). Two layers:

### Layer 1: Interaction Log

Every triage card and user response stored in full:

```
interaction_log:
  id, timestamp, source_type, item_id, item_summary,
  triage_card_full (JSON),
  enrichment_context (JSON),
  options_presented (JSON array),
  option_chosen (text),
  todo_created (JSON, nullable),
  enrichment_depth (text),
  enrichment_calls (int),
  enrichment_time_ms (int)
```

Append-only, never pruned.

### Layer 2: Zep Knowledge Graph

Zep auto-extracts preference facts from the interaction log continuously:
- "User always prioritizes diffs where reviewers are blocked"
- "User drops emails from infrastructure-announcements group"
- "User treats SEVs for auth service as P0"

The noise filter queries Zep for relevant preference facts at scoring time. No batch synthesis job needed — Zep handles this continuously.

**Seed preferences (cold start):** On first run, the setup flow (`/workbench:setup` or `POST /api/preferences/seed`) prompts for a short seed: "What do you care about? What don't you care about?" Seed facts are written into Zep. Subsequent learning is automatic from triage responses.

**Fallback:** If Zep is unavailable, the noise filter uses only explicit filter rules from SQLite. Less intelligent, but functional.

Zep also accumulates entity knowledge (people, diffs, tasks, relationships) and provides relationship context for triage card generation. See the Zep design spec for details.

## Priority Scorer

| Priority | Criteria |
|----------|----------|
| P0 — Today | Explicit deadline within 24h, "urgent"/"blocker"/"critical", from your manager, active SEV for your service |
| P1 — This Week | Deadline this week, blocking others, review requests on active diffs, oncall alerts |
| P2 — This Month | Deadline this month, standard follow-ups |
| P3 — Someday | No deadline, nice-to-do |
| Pending | Insufficient context → triage card via Google Chat |

## Dashboard

The dashboard is not a separate UI — it's data served via the API and rendered by whichever surface requests it.

### Surfaces

**Google Chat — Morning Briefing**: A daily automated message (configurable time) summarizing P0/P1 items, pending triage, and anything new since yesterday. Sent proactively.

**Claude Code plugin — `/workbench:status`**: On-demand formatted dashboard in the terminal. Shows priorities, pending triage count, stale items, and active plans.

**MCP — `workbench_status`**: Same data, accessible from any MCP client.

### Dashboard Content

```markdown
# Workbench
Last updated: 2026-05-21 15:30 UTC

## Action Items

### P0 — Today
- [ ] Review D12345678 — auth middleware refactor (due: today) [diff]
- [ ] Respond to SEV 54321 — auth latency spike [sev]

### P1 — This Week
- [ ] Fix T98765 — auth token expiry [task]
- [ ] Review D12345679 — logging changes [diff]

### P2 — This Month
- [ ] Meet with XYZ about infrastructure migration [workplace]

### P3 — Someday
- [ ] Look into refactoring the auth middleware [workplace]

### Pending Clarification
- [ ] "Sync with PM about launch readiness" — asked 2026-05-21

## Meetings to Schedule
- [ ] P1: Follow-up with PM on launch timeline (this week)
- [ ] P2: Meet with XYZ re: infrastructure

## Plans
| Plan | Status | Link |
|------|--------|------|
| Auth Hardening Q3 | draft | [link] |
| Infrastructure Migration | reviewed | [link] |
```

## Draft Plan Creation (Phase 2)

Deferred to Phase 2. The `plans` table and API endpoints remain in the schema but are not actively used in Phase 1. Focus is on the triage loop being rock solid first.

When implemented: a "plan seed" is detected when 3+ action items from different sources converge on the same topic within a 7-day window. The system gathers related context, uses Claude to synthesize a structured plan, stores it, and links related items. Status lifecycle: draft → reviewed → finalized.

## Server Components

### API Endpoints

Lightweight auth — static bearer token. The server checks `Authorization: Bearer <token>` on every request (except `GET /health`). Token is configured via `WORKBENCH_API_TOKEN` env var on the server and stored in the plugin's `config.json`. No user management, no login flow. The token syncs across devservers/ODs via dotsync2.

**Processing**
- `POST /api/process` — manually submit content for processing (text or doc URL). Async — returns `{job_id, status: "pending"}`.
- `GET /api/jobs/{job_id}` — query pipeline job status and results
- `POST /api/preferences/seed` — bootstrap initial preference summary from user input (cold start)

**Items**
- `GET /api/items` — list items with filters (priority, source, status)
- `PATCH /api/items/{item_id}` — update item (mark done, change priority)
- `DELETE /api/items/{item_id}` — archive an item

**Triage**
- `GET /api/triage/pending` — list items awaiting triage response
- `POST /api/triage/respond` — record a triage response

**Plans**
- `POST /api/plans` — create a draft plan
- `GET /api/plans` — list plans
- `PATCH /api/plans/{plan_id}` — update plan

**Preferences**
- `GET /api/preferences` — get preference summary
- `GET /api/preferences/digest` — get incremental digest

**Filter Rules**
- `GET /api/filter-rules` — list filter rules
- `POST /api/filter-rules` — add a filter rule
- `GET /api/filter-rules/{source_type}` — source-specific filter rules

**Interaction Log**
- `GET /api/interactions` — query interaction history (cursor-based pagination)

**Enrichment**
- `GET /api/enrichment/trace` — query enrichment trace log

**Sources**
- `GET /api/sources` — list configured source adapters
- `POST /api/sources` — add a source adapter
- `PATCH /api/sources/{source_id}` — update source config (schedule, enable/disable)
- `DELETE /api/sources/{source_id}` — remove a source adapter

**Config**
- `GET /api/config` — get configuration
- `PATCH /api/config` — update configuration

**Memory (Zep)**
- `GET /api/memory/facts` — list Zep's extracted preference facts
- `POST /api/memory/rebuild` — replay interaction log through Zep to rebuild knowledge graph

**Health**
- `GET /health` — server health check

### MCP Server

The server also exposes an MCP endpoint so any MCP-compatible client can interact with Workbench natively through tool calls:

- `workbench_process` — submit content for processing
- `workbench_items` — list/filter items
- `workbench_triage_pending` — list pending triage items
- `workbench_triage_respond` — respond to a triage card
- `workbench_status` — server status and health
- `workbench_plans` — list/create/update plans
- `workbench_sources` — manage source adapters

### Server-Side Scheduler

The server runs a background scheduler (APScheduler or similar) that:

- Polls each enabled source adapter on its configured schedule
- **Triage queue manager**: After a poll run, queues all new triage cards. Sends one card at a time to Google Chat. Polls `list_messages()` for the user's text reply. On response (or timeout), advances to the next card. Timeout = configurable (default 30 min), after which the card stays pending and the queue advances to the next card. No re-send or nagging — the morning briefing includes pending triage count, and `/workbench:triage` handles batch catchup.
- Sends daily morning briefing via Google Chat (configurable time, default 9:00 AM)
- Runs daily cleanup (archive completed items, flag stale items)

Schedules are configurable via the API.

## Claude Code Plugin (Thin Client)

The plugin is a thin HTTP client wrapping API calls. No pipeline logic, no storage access, no LLM calls. All operations go through the server.

```
~/.claude/plugins/local/workbench/
  .claude-plugin/plugin.json
  commands/
    process.md         -- /process <text or doc link>: POST to /api/process
    setup.md           -- /workbench:setup: configure server URL
    status.md          -- /workbench:status: GET /health + dashboard summary
    triage.md          -- /workbench:triage: interactive CLI triage via API
    sources.md         -- /workbench:sources: manage sources via API
  config/
    config.json        -- server URL (e.g., http://devgpu:8421)
```

## Project Structure (in repo)

```
workbench/
  docs/
    specs/                         -- design specs
    plans/                         -- implementation plans
    adr/                           -- architectural decision records
    memory/                        -- project memory (decisions, context)
  docker-compose.yml               -- Podman Compose (workbench + zep + zep-postgres)
  server/
    Dockerfile
    requirements.txt
    main.py                        -- FastAPI app entrypoint
    config.py                      -- server configuration
    storage/
      base.py                     -- repository interfaces (ABC)
      factory.py                  -- backend selection from config
      sqlite/                     -- SQLite implementation (Phase 1)
        __init__.py
        connection.py
        items.py, triage.py, plans.py, interactions.py,
        filter_rules.py, enrichment.py, sources.py,
        processed.py, config.py, jobs.py
      xdb/                        -- XDB implementation (Phase 2)
      postgres/                   -- PostgreSQL implementation (Phase 2)
    memory/
      base.py                     -- MemoryLayer interface (ABC)
      noop.py                     -- NoopMemoryLayer (testing/Zep-disabled)
      zep.py                      -- ZepMemoryLayer (Zep Python SDK)
    api/
      items.py                    -- items endpoints
      triage.py                   -- triage endpoints
      plans.py                    -- plans endpoints
      preferences.py              -- preferences endpoints (proxies Zep facts)
      filter_rules.py             -- filter rules endpoints
      interactions.py             -- interaction log endpoints
      enrichment.py               -- enrichment endpoints
      sources.py                  -- source adapter management
      memory.py                   -- memory/facts + rebuild endpoints
      config.py                   -- config endpoints
      health.py                   -- health check
    mcp/
      server.py                   -- MCP server implementation
      tools.py                    -- MCP tool definitions
    pipeline/
      engine.py                   -- pipeline orchestration
      extraction.py               -- LLM extraction stage
      filter.py                   -- adaptive noise filter
      enrichment.py               -- context enrichment
      triage.py                   -- triage card generation
      scheduler.py                -- background job scheduler
    providers/
      llm/
        base.py                   -- LLM provider interface
        claude.py                 -- Anthropic Claude API
      doc_reader/
        base.py                   -- DocReader interface
        google_docs.py            -- Google Docs via Google API proxy
      messenger/
        base.py                   -- Messenger interface
        google_chat.py            -- Google Chat API
      source/
        base.py                   -- SourceAdapter interface
        phabricator.py            -- Phabricator diffs (Phase 1)
        email.py                  -- Gmail (Phase 1)
        tasks.py                  -- Meta Tasks (Phase 2)
        workplace.py              -- Workplace posts (Phase 2)
        calendar.py               -- Calendar / meeting notes (Phase 2)
        sev.py                    -- SEVs (Phase 2)
        oncall.py                 -- Oncall alerts (Phase 2)
      enrichment/
        base.py                   -- ContextEnricher interface
        meta.py                   -- Meta-internal enricher
        stub.py                   -- stub for testing
  plugin/
    .claude-plugin/plugin.json
    commands/
      process.md
      setup.md
      status.md
      triage.md
      sources.md
    config/
      config.json
  tests/
    test_pipeline.py
    test_api.py
    test_storage.py
    test_memory.py
    test_filter.py
```

## Verification

1. `podman compose up -d` — all three services start (workbench, zep, zep-postgres)
2. `GET /health` returns OK from devgpu and from an OnDemand
3. `POST /api/process` with pasted text — triage card sent via Google Chat
4. Respond to triage card in Google Chat — item appears in storage with correct priority
5. Triage response dual-written to Zep — `GET /api/memory/facts` shows extracted preference
6. Configure Phabricator source — verify diffs needing review are ingested
7. Wait for scheduler — verify it polls sources and processes new items
8. "Never" response — filter rule created in storage
9. Zep down — pipeline degrades gracefully (uses filter rules only, no crash)
10. Connect via MCP — verify tools work (`workbench_process`, `workbench_items`, etc.)
11. `/workbench:setup` from Claude Code — plugin configured with server URL
12. `/process` from Claude Code — delegates to server, triage card sent to Google Chat
13. `POST /api/memory/rebuild` — replays interaction log, knowledge graph rebuilt

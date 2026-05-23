# Workbench — Personal Intelligence Feed

## Context

Meeting notes, emails, social feed posts, tasks, and code review comments generate a constant stream of information that requires manual triage. Workbench is an open-source system that ingests from multiple sources, filters noise adaptively, and maintains a prioritized dashboard of action items, draft plans, and meetings to schedule — so that opening one view gives a clear picture of what needs attention.

## Phased Delivery

- **Phase 1** (this spec): Server + database + Claude Code plugin + MCP server. Triage via Messenger. Containerized deployment.
- **Phase 2**: Webapp — interactive dashboard.
- **Phase 3**: Mobile apps (iOS/Android).

## Architecture

```
┌──────────────┐ ┌────────────┐ ┌───────────┐ ┌──────────────┐
│ Claude Code  │ │ MCP Client │ │ Webapp    │ │ Mobile Apps  │
│ Plugin       │ │            │ │ (Phase 2) │ │ (Phase 3)    │
└──────┬───────┘ └─────┬──────┘ └─────┬─────┘ └──────┬───────┘
       │               │              │               │
       └───────┬───────┘──────────────┘───────────────┘
               │ HTTP / MCP protocol
              ┌──────▼──────────┐
              │  Workbench      │
              │  Server         │
              │  (FastAPI)      │
              ├─────────────────┤
              │  Pipeline       │  ← Source polling, LLM extraction,
              │  Engine         │    filtering, triage, enrichment
              ├─────────────────┤
              │  LLM Provider   │  ← Configurable: Claude / OpenAI / Ollama / etc.
              ├─────────────────┤
              │  Messenger      │  ← WhatsApp / Discord / Google Chat
              ├─────────────────┤
              │  Source Adapters │  ← Gmail, stubs for meetings/tasks/etc.
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │  PostgreSQL     │
              │  (multi-tenant) │
              └─────────────────┘
```

The server does all heavy lifting: source polling, LLM calls for extraction/filtering/triage, enrichment, preference synthesis, and Messenger communication. Clients are thin interfaces to the API:

- **Claude Code plugin** (Phase 1) — slash commands wrapping API calls
- **MCP server** (Phase 1) — native tool access from any MCP-compatible client
- **Webapp** (Phase 2) — interactive dashboard in the browser
- **Mobile apps** (Phase 3) — iOS (Swift) and Android (Kotlin) apps for on-the-go triage, reviewing action items, and responding to triage cards via push notifications

## Deployment

Docker + docker-compose with three containers:
1. **workbench-server**: FastAPI application (API + MCP server + pipeline engine + scheduler)
2. **workbench-db**: PostgreSQL
3. **workbench-worker** (optional): Background task worker for long-running pipeline jobs (can start as part of the server process and split out later if needed)

Compatible with Podman for environments where Docker is unavailable.

## Multi-Tenant Data Model

### Users and Workspaces

- A **user** is a person with login credentials.
- A **workspace** is an isolated context with its own feeds, filters, preferences, items, and plans.
- Users can have multiple workspaces (e.g., "Work", "Side Project", "Open Source").
- A workspace can have multiple users (e.g., a team workspace).
- The relationship is many-to-many with a role (owner, member).

### Per-Workspace Isolation

Each workspace has its own:
- Source adapter configurations and credentials (Gmail accounts, etc.)
- Feed polling schedules
- Filter rules (global + per-email-account)
- Preference summary and interaction log
- Items, plans, triage cards
- Enrichment settings and trace log
- Messenger configuration

### Auth

Token-based authentication for API access. Each user gets an API token. The Claude Code plugin and MCP server store the token in their config. OAuth support can be added for the webapp in Phase 2.

## Provider Interfaces

All external integrations are behind pluggable interfaces, configured per-workspace.

### LLM Provider

Configurable LLM for extraction, filtering, triage card generation, and preference synthesis.

| Implementation | Notes |
|---------------|-------|
| ClaudeProvider | Anthropic API |
| OpenAIProvider | OpenAI API |
| OllamaProvider | Local Ollama instance |

Each provider implements: `extract(raw_text) → structured items`, `score_relevance(item, preferences, rules) → (relevance, confidence)`, `generate_triage_card(item, enrichment) → card`, `synthesize_preferences(digest) → summary`.

### DocReader

Read content from a document link. Multiple implementations active simultaneously.

| Implementation | Reads from |
|---------------|-----------|
| GoogleDocsReader | Google Docs URLs (via Google Docs API) |
| NotionReader | Notion page URLs (via Notion API) |
| RawURLReader | Any URL (fetch + extract text) |

### WorkbenchStore (Export Target)

Optional export of Dashboard to external doc systems. The database is the source of truth.

| Implementation | Notes |
|---------------|-------|
| GoogleDocsExporter | via Google Docs API |
| NotionExporter | via Notion API |

### Messenger

Send triage cards and receive user responses. Bidirectional. Configured per-workspace.

| Implementation | Notes |
|---------------|-------|
| WhatsAppMessenger | via WhatsApp Business API |
| DiscordMessenger | via Discord Bot API |
| GoogleChatMessenger | via Google Chat API |
| SlackMessenger | via Slack Bot API (community contribution welcome) |

### SourceAdapter

Poll for new items, output raw data. Configured per-workspace with per-adapter credentials.

| Adapter | Notes |
|---------|-------|
| EmailAdapter (Gmail) | Gmail API — works everywhere |
| MeetingNotesAdapter | Stub — implement for your calendar system |
| SocialFeedAdapter | Stub — implement for your corporate social feed |
| TasksAdapter | Stub — implement for your task system (Jira, Linear, Asana, etc.) |
| CodeReviewAdapter | Stub — implement for your code review system (GitHub PRs, GitLab MRs, etc.) |

Source adapters fetch **raw data only**. The LLM Provider does semantic extraction.

### ContextEnricher

Fetch additional context about referenced entities before triage. Configured per-workspace.

| Implementation | Notes |
|---------------|-------|
| StubEnricher | Default — returns empty context |

Implement custom enrichers to look up referenced entities in wikis, task systems, people directories, etc.

**Depth setting** (per-workspace config):
- `shallow` (default): Fetch only the directly referenced entity
- `deep`: Follow reference chains (task → parent → project → team → recent activity)

**Budget settings** (per-workspace config):
- `max_api_calls_per_item`: default 3 (shallow), 15 (deep)
- `max_seconds_per_item`: default 10s (shallow), 60s (deep)
- `max_deep_items_per_run`: default 50

**Enrichment trace log**: Every call logged with item ID, depth, calls made, time, context retrieved.

## Processing Pipeline

All processing runs on the server. The pipeline is triggered by:
- **Server-side scheduler**: Periodic source polling (replaces Claude Code crons)
- **API call**: Manual processing via `/api/workspaces/{id}/process`

```
Source adapter (raw data) → LLM extraction → Relevance filter → Context enrichment → Rich triage card → Messenger → User response → Store in database
```

### Stage 1: Source Adapter

Server-side adapters poll configured sources and produce raw items:

```json
{
  "id": "source-specific-unique-id",
  "source_type": "meeting|email|social|task|code_review",
  "source_label": "Weekly Sync 2026-05-21",
  "raw_text": "Full content from the source"
}
```

### Stage 2: LLM Extraction

The configured LLM Provider reads raw text and extracts structured items: summary, action items, plan seeds, meetings to schedule.

### Stage 3: Adaptive Noise Filter

Every item gets two scores (0-100):
- **Relevance**: How likely this requires the user's action or attention.
- **Confidence**: How sure the system is about the relevance score.

**Thresholds** (configurable per-workspace):
- Relevance >= 70 AND confidence >= 70 → auto-include
- Relevance < 30 AND confidence >= 70 → auto-drop (still logged)
- Everything else → send triage card via Messenger

The filter reads workspace-specific `preferences` and `filter_rules` before scoring.

**Filter rules** are natural language patterns:

```json
{"pattern": "posts from group 'Infrastructure Announcements'", "action": "include", "priority": "P3"}
{"pattern": "CI bot comments on code reviews", "action": "drop"}
```

The LLM matches incoming items against rules using judgment, not regex.

**Email-specific pre-filter**: Each email account (within a workspace) has its own filter rules table. Starts empty. Learns from triage responses.

### Stage 4: Context Enrichment

The ContextEnricher gathers additional information about referenced entities. Respects depth and budget settings. Results are attached to the triage card.

### Stage 5: Rich Triage Card

Every item gets a context-rich triage card sent via Messenger. The card includes:
- Source-specific summary and context
- Enrichment results (who else is involved, related items, background)
- Actionable options tailored to the source type

**Email triage card example:**
> **Email from @alice — "Q3 planning doc needs your input"**
> Received 2h ago, you're in TO (not CC)
>
> **Summary:** Alice shared a Q3 planning doc and is asking each TL to add their team's priorities by Friday.
>
> **What do you want to do?**
> 1. Add todo: "Add team priorities to Q3 planning doc" (P1, due Friday)
> 2. Add todo: "Reply to Alice about Q3 planning"
> 3. Add todo: "Review Q3 planning doc"
> 4. Skip this email
> 5. Never surface emails from this sender
> 6. Never surface emails with this pattern

**Meeting notes triage card:**
> **Meeting: Weekly Sync with Team Foo (2026-05-21)**
> Attendees: you, @alice, @bob, @charlie
>
> **Summary:** Discussed Project X migration timeline. You volunteered to own the design doc.
>
> **Action items found:**
> - Write Project X design doc (due: next Friday)
> - Schedule follow-up with @alice on data migration
>
> **What do you want to do?**
> 1. Accept all action items as P1
> 2. Accept with adjusted priorities
> 3. Skip all
> 4. Add a draft plan for "Project X Migration"

**Task triage card:**
> **Task #12345 assigned to you — "Fix auth token expiry"**
> Assigned by @bob, priority P1, tagged: backend, auth
> [Enriched: parent task #12340 "Auth hardening Q3", 3 other subtasks]
>
> **What do you want to do?**
> 1. Add to Dashboard as P1
> 2. Change priority
> 3. Skip
> 4. Never surface tasks tagged "auth"

**Code review triage card:**
> **PR #456 needs your review — "Refactor auth middleware"**
> Author: @bob, 450 lines changed in auth/middleware/
> [Enriched: related to task #12345, 2 other reviewers assigned]
>
> **What do you want to do?**
> 1. Add review todo (P1)
> 2. Add review todo (P2)
> 3. Skip
> 4. Never surface code reviews in auth/middleware/

### Stage 6: Response Processing

When the user responds via Messenger:
- The chosen action is executed (create todo, update priority, add plan, etc.)
- The full triage card + response is logged to the interaction log
- "Never"/"always" responses create filter rules
- The preference summary is updated incrementally

## Preference Learning System

Three layers, all stored in the database per-workspace:

### Layer 1: Interaction Log

Every triage card and user response stored in full:

```
interaction_log:
  id, workspace_id, timestamp, source_type, item_id, item_summary,
  triage_card_full (JSON),        -- full triage card as presented
  enrichment_context (JSON),      -- context gathered before triage
  options_presented (JSON array),
  option_chosen (text),
  todo_created (JSON, nullable),
  enrichment_depth (text),
  enrichment_calls (int),
  enrichment_time_ms (int)
```

Append-only, never pruned.

### Layer 2: Preference Summary

A single record per workspace synthesized from the interaction log:

```markdown
# Preferences
Last updated: 2026-05-22

## What I care about
- Anything where someone is blocked on me
- Tasks assigned to me that are P0/P1
...

## What I don't care about
- FYI posts from large groups unless they mention my project by name
...

## Priority tendencies
- I tend to bump things up when people are waiting on me
...

## Communication style
- I prefer short messages, not paragraphs
...
```

**Incremental updates**: The server reads only new interaction log entries since the last cursor position, computes statistics, and uses the LLM to synthesize the updated preference summary.

### Layer 3: Preference-Informed Decisions

The preference summary is loaded as context for every pipeline run. It informs noise filtering, priority scoring, draft plan creation, and triage card style.

## Priority Scorer

| Priority | Criteria |
|----------|----------|
| P0 — Today | Explicit deadline within 24h, "urgent"/"blocker"/"critical", from your manager |
| P1 — This Week | Deadline this week, blocking others, review requests on active code reviews |
| P2 — This Month | Deadline this month, standard follow-ups |
| P3 — Someday | No deadline, nice-to-do |
| Pending | Insufficient context → triage card via Messenger |

## Dashboard Format

Stored in the database, served via API, optionally exported to Google Docs or Notion:

```markdown
# Workbench
Last updated: 2026-05-21 15:30 UTC

## Action Items

### P0 — Today
- [ ] Review design doc for Project X (due: 2026-05-22) [meeting/Weekly Sync]
- [ ] Respond to PR #456 comment from @alice [code_review]

### P1 — This Week
- [ ] Set up integration test environment [meeting/1:1]
- [ ] Review task #98765 — infra migration [task]

### P2 — This Month
- [ ] Meet with XYZ about infrastructure migration [meeting]

### P3 — Someday
- [ ] Look into refactoring the auth middleware [social]

### Pending Clarification
- [ ] "Sync with PM about launch readiness" — asked 2026-05-21

## Meetings to Schedule
- [ ] P1: Follow-up with PM on launch timeline (this week)
- [ ] P2: Meet with XYZ re: infrastructure

## Plans
| Plan | Status | Link |
|------|--------|------|
| Project X Migration | draft | [link] |
| Auth Middleware Refactor | reviewed | [link] |
```

## Draft Plan Creation

A "plan seed" is detected when 3+ action items from different sources converge on the same topic within a 7-day window. When detected:

1. Gather all related context from the database
2. Use LLM Provider to synthesize a structured plan
3. Store the plan in the database, optionally export to Google Docs/Notion
4. Status lifecycle: draft → reviewed → finalized

## Server Components

### API Endpoints

**Auth**
- `POST /auth/register` — create a user account
- `POST /auth/login` — get API token
- `POST /auth/token` — generate API token for plugin/MCP

**Workspaces**
- `POST /workspaces` — create a workspace
- `GET /workspaces` — list user's workspaces
- `GET /workspaces/{id}` — workspace details
- `PATCH /workspaces/{id}` — update workspace config
- `POST /workspaces/{id}/members` — add a member
- `DELETE /workspaces/{id}/members/{user_id}` — remove a member

**Processing**
- `POST /workspaces/{id}/process` — manually submit content for processing (text or doc URL)

**Items**
- `GET /workspaces/{id}/items` — list items with filters (priority, source, status)
- `PATCH /workspaces/{id}/items/{item_id}` — update item (mark done, change priority)
- `DELETE /workspaces/{id}/items/{item_id}` — archive an item

**Triage**
- `GET /workspaces/{id}/triage/pending` — list items awaiting triage response
- `POST /workspaces/{id}/triage/respond` — record a triage response

**Plans**
- `POST /workspaces/{id}/plans` — create a draft plan
- `GET /workspaces/{id}/plans` — list plans
- `PATCH /workspaces/{id}/plans/{plan_id}` — update plan

**Preferences**
- `GET /workspaces/{id}/preferences` — get preference summary
- `GET /workspaces/{id}/preferences/digest` — get incremental digest

**Filter Rules**
- `GET /workspaces/{id}/filter-rules` — list filter rules
- `POST /workspaces/{id}/filter-rules` — add a filter rule
- `GET /workspaces/{id}/filter-rules/email/{account}` — email-specific filter rules

**Interaction Log**
- `GET /workspaces/{id}/interactions` — query interaction history (cursor-based pagination)

**Enrichment**
- `GET /workspaces/{id}/enrichment/trace` — query enrichment trace log

**Sources**
- `GET /workspaces/{id}/sources` — list configured source adapters
- `POST /workspaces/{id}/sources` — add a source adapter
- `PATCH /workspaces/{id}/sources/{source_id}` — update source config (credentials, schedule, enable/disable)
- `DELETE /workspaces/{id}/sources/{source_id}` — remove a source adapter

**Export**
- `POST /workspaces/{id}/export` — export Dashboard to Google Docs or Notion

**Config**
- `GET /workspaces/{id}/config` — get workspace configuration
- `PATCH /workspaces/{id}/config` — update configuration

**Health**
- `GET /health` — server health check

### MCP Server

The server also exposes an MCP endpoint so any MCP-compatible client can interact with Workbench natively through tool calls:

- `workbench_process` — submit content for processing
- `workbench_items` — list/filter items
- `workbench_triage_pending` — list pending triage items
- `workbench_triage_respond` — respond to a triage card
- `workbench_status` — workspace status and health
- `workbench_plans` — list/create/update plans
- `workbench_sources` — manage source adapters

### Server-Side Scheduler

Replaces Claude Code crons. The server runs a background scheduler (APScheduler or similar) that:

- Polls each workspace's enabled source adapters on their configured schedule
- Checks Messenger channels for triage responses
- Runs daily cleanup (archive completed items, flag stale items, regenerate preferences, re-export Dashboard)

Schedules are per-workspace and configurable via the API.

## Database Schema (PostgreSQL)

### Core Tables

- `users` (id, email, name, password_hash, created_at)
- `workspaces` (id, name, created_at)
- `workspace_members` (workspace_id, user_id, role)

### Per-Workspace Tables (all have workspace_id FK)

- `items` (id, workspace_id, source_type, source_id, summary, priority, status, created_at, updated_at)
- `plans` (id, workspace_id, title, status, content, sources, created_at)
- `triage_cards` (id, workspace_id, item_id, card_content, options, sent_at, responded_at, response)
- `interaction_log` (id, workspace_id, timestamp, source_type, item_id, triage_card_full, enrichment_context, options_presented, option_chosen, todo_created, enrichment_depth, enrichment_calls, enrichment_time_ms)
- `filter_rules` (id, workspace_id, pattern, action, priority, created_from_interaction_id)
- `email_filters` (id, workspace_id, account, pattern, action, created_from_interaction_id)
- `preferences` (id, workspace_id, content, cursor_position, updated_at)
- `enrichment_trace` (id, workspace_id, item_id, depth, calls_made, time_ms, context_retrieved, timestamp)
- `processed` (workspace_id, source_type, source_id, processed_at)
- `source_configs` (id, workspace_id, adapter_type, credentials_encrypted, schedule, enabled, created_at)
- `workspace_config` (workspace_id, key, value)

## Claude Code Plugin (Thin Client)

The plugin is a thin wrapper around the API. No pipeline logic, no source polling, no LLM calls.

```
~/.claude/plugins/local/workbench/
  .claude-plugin/plugin.json
  commands/
    process.md         -- /process <text or doc link>: POST to /workspaces/{id}/process
    setup.md           -- /workbench:setup: start containers, register, configure
    status.md          -- /workbench:status: GET /health + /workspaces/{id}/status
    triage.md          -- /workbench:triage: interactive CLI triage via API
    sources.md         -- /workbench:sources: manage sources via API
  config/
    config.json        -- server URL, API token, default workspace ID
```

## Project Structure (in repo)

```
workbench/
  specs/                          -- design specs
  plans/                          -- implementation plans
  server/
    Dockerfile
    docker-compose.yml
    requirements.txt
    main.py                       -- FastAPI app entrypoint
    config.py                     -- server configuration
    models/                       -- SQLAlchemy models
    migrations/                   -- Alembic migrations
    api/
      auth.py                     -- auth endpoints
      workspaces.py               -- workspace CRUD
      items.py                    -- items endpoints
      triage.py                   -- triage endpoints
      plans.py                    -- plans endpoints
      preferences.py              -- preferences endpoints
      filter_rules.py             -- filter rules endpoints
      interactions.py             -- interaction log endpoints
      enrichment.py               -- enrichment endpoints
      sources.py                  -- source adapter management
      export.py                   -- doc export endpoints
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
      preferences.py              -- preference synthesis
      scheduler.py                -- background job scheduler
    providers/
      llm/
        base.py                   -- LLM provider interface
        claude.py                 -- Anthropic Claude
        openai.py                 -- OpenAI
        ollama.py                 -- Local Ollama
      doc_reader/
        base.py                   -- DocReader interface
        google_docs.py
        notion.py
        raw_url.py
      doc_export/
        base.py                   -- WorkbenchStore interface
        google_docs.py
        notion.py
      messenger/
        base.py                   -- Messenger interface
        whatsapp.py
        discord.py
        google_chat.py
      source/
        base.py                   -- SourceAdapter interface
        email_gmail.py
        meetings_stub.py
        social_stub.py
        tasks_stub.py
        code_review_stub.py
      enrichment/
        base.py                   -- ContextEnricher interface
        stub.py
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
    test_providers.py
    test_filter.py
    test_preferences.py
```

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

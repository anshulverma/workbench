# Workbench — Personal Intelligence Feed

## Context

Meeting notes, emails, social feed posts, tasks, and code review comments generate a constant stream of information that requires manual triage. The goal is an open-source system that ingests from multiple sources, filters noise adaptively, and maintains a prioritized dashboard of action items, draft plans, and meetings to schedule — so that opening one view gives a clear picture of what needs attention.

The system is designed for open source with pluggable providers. Enterprise-specific integrations (internal CLIs, corporate wikis, proprietary task systems) are implemented behind provider interfaces so they can be swapped without changing the core.

## Phased Delivery

- **Phase 1** (this spec): Claude Code plugin + API server + PostgreSQL database. Triage via Messenger (WhatsApp/Discord/Google Chat). Containerized deployment.
- **Phase 2**: Webapp — interactive dashboard consuming the API. Replaces Messenger as primary triage UI.
- **Phase 3**: Mobile apps (iOS/Android), same API.

Phase 1's architecture anticipates the API layer so Phase 2 just adds a frontend.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│ Claude Code Plugin                                  │
│  commands/ (process, setup, status, cleanup, sources)│
│  scripts/  (source adapters, doc ops, messaging)    │
│  cron jobs (source watcher, clarify checker, cleanup)│
└──────────────────────┬──────────────────────────────┘
                       │ HTTP
              ┌────────▼────────┐
              │   API Server    │
              │   (FastAPI)     │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   PostgreSQL    │
              └─────────────────┘
```

The plugin never writes to the database directly — all state goes through the API. This allows the webapp (Phase 2) and mobile apps (Phase 3) to share the same data layer.

## Deployment

Docker + docker-compose (API server container + PostgreSQL container). One `Dockerfile` / `Containerfile` and a `docker-compose.yml` define the two-container stack. Compatible with Podman for environments where Docker is unavailable.

## Provider Interfaces

All external integrations are behind pluggable interfaces. Each provider has a default OSS implementation and can be swapped for enterprise-specific implementations.

### DocReader

Read content from a document link. Multiple implementations active simultaneously.

| Implementation | Reads from |
|---------------|-----------|
| GoogleDocsReader | Google Docs URLs (via Google Docs API) |
| NotionReader | Notion page URLs (via Notion API) |
| RawURLReader | Any URL (fetch + extract text) |

Enterprise environments can add custom readers (e.g., internal wiki pages, corporate doc systems) by implementing the DocReader interface.

### WorkbenchStore

Read/write the Dashboard, Log, Archive, and Plans. One active implementation at a time. **In Phase 1**, this writes to the database via the API. Google Docs and Notion become optional *export targets* — the database is the source of truth.

| Implementation | Notes |
|---------------|-------|
| GoogleDocsExporter | via Google Docs API |
| NotionExporter | via Notion API |

### Messenger

Send triage cards and receive user responses. Bidirectional.

| Implementation | Notes |
|---------------|-------|
| WhatsAppMessenger | via WhatsApp Business API |
| DiscordMessenger | via Discord Bot API |
| GoogleChatMessenger | via Google Chat API |

Enterprise environments can add custom messengers (e.g., Slack, MS Teams) by implementing the Messenger interface.

### SourceAdapter

Poll for new items, output raw data. Claude does semantic extraction.

| Adapter | Notes |
|---------|-------|
| MeetingNotesAdapter | Stub — implement for your calendar/meeting system |
| EmailAdapter (Gmail) | Gmail API (works everywhere) |
| SocialFeedAdapter | Stub — implement for your corporate social feed |
| TasksAdapter | Stub — implement for your task management system (Jira, Linear, Asana, etc.) |
| CodeReviewAdapter | Stub — implement for your code review system (GitHub PRs, GitLab MRs, etc.) |

Source adapters fetch **raw data only** (ID, source type, label, raw text). They do not extract action items or priorities — that requires LLM reasoning and happens in the pipeline after the adapter stage.

### ContextEnricher

Fetch additional context about referenced entities before triage. Configurable depth.

| Implementation | Notes |
|---------------|-------|
| StubEnricher | Default — returns empty context |

Enterprise environments implement custom enrichers to look up referenced entities in wikis, task systems, people directories, etc.

**Depth setting** (in config):
- `shallow` (default): Fetch only the directly referenced entity (the task ID, the wiki page by name)
- `deep`: Follow reference chains (task → parent task → project → team → recent activity)

**Budget settings** (in config):
- `max_api_calls_per_item`: Max API calls for enriching a single item (default: 3 shallow, 15 deep)
- `max_seconds_per_item`: Timeout per item (default: 10s shallow, 60s deep)
- `max_deep_items_per_run`: Max items to deep-enrich per cron run (default: 50)

**Enrichment trace log**: Every enrichment call is logged to the database with item ID, depth used, calls made, time taken, and what context was retrieved. This allows tuning budget settings based on actual usage.

## Processing Pipeline

```
Source adapter (raw data) → Claude extraction → Relevance filter → Context enrichment → Rich triage card → Messenger → User response → Route to database
```

### Stage 1: Source Adapter

Scripts fetch raw data and output a simple schema:

```json
{
  "id": "source-specific-unique-id",
  "source_type": "meeting|email|social|task|code_review",
  "source_label": "Weekly Sync 2026-05-21",
  "raw_text": "Full content from the source"
}
```

### Stage 2: Claude Extraction

The LLM reads the raw text and extracts structured items: summary, action items, plan seeds, meetings to schedule. This is where semantic reasoning happens — not in the adapter scripts.

### Stage 3: Adaptive Noise Filter

Every item gets two scores (0-100):
- **Relevance**: How likely this requires the user's action or attention.
- **Confidence**: How sure the system is about the relevance score.

**Thresholds** (configurable in database settings):
- Relevance >= 70 AND confidence >= 70 → auto-include
- Relevance < 30 AND confidence >= 70 → auto-drop (still logged)
- Everything else → send triage card via Messenger

The filter reads `preferences` and `filter_rules` from the database before scoring. Over time, confidence rises and Messenger questions decrease.

**Filter rules** are natural language patterns stored in the database:

```json
{"pattern": "posts from group 'Infrastructure Announcements'", "action": "include", "priority": "P3"}
{"pattern": "CI bot comments on code reviews", "action": "drop"}
```

Claude matches incoming items against rules using judgment, not regex.

**Email-specific pre-filter**: Each email account has its own filter rules table. Starts empty. Learns from triage responses. Catches mechanical noise (known senders, patterns) before burning an LLM call.

### Stage 4: Context Enrichment

Before building the triage card, the ContextEnricher gathers additional information about referenced entities. Respects depth and budget settings. Results are attached to the triage card.

### Stage 5: Rich Triage Card

Every item — regardless of source — gets a context-rich triage card sent via Messenger. The card includes:
- Source-specific summary and context
- Enrichment results (who else is involved, related items, background)
- Actionable options tailored to the source type

**Email triage card example:**
> **Email from @alice — "Q3 planning doc needs your input"**
> Received 2h ago, you're in TO (not CC)
>
> **Summary:** Alice shared a Q3 planning doc and is asking each TL to add their team's priorities by Friday. Doc link: [link]
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
> **Summary:** Discussed Project X migration timeline, agreed on Q3 deadline. You volunteered to own the design doc.
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
> [Enriched: parent task #12340 "Auth hardening Q3", 3 other subtasks, @charlie also working on it]
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
- The chosen action is executed (create todo, update priority, add plan, etc.) via the API
- The full triage card + response is logged to the interaction log in the database
- "Never"/"always" responses create filter rules
- The preference summary is updated incrementally

## Preference Learning System

Three layers, all stored in the database:

### Layer 1: Interaction Log (database table)

Every triage card and user response is stored in full:

```
interaction_log:
  id, timestamp, source_type, item_id, item_summary,
  triage_card_full (JSON),        -- full triage card as presented
  enrichment_context (JSON),      -- context gathered before triage
  options_presented (JSON array),  -- what options were shown
  option_chosen (text),           -- what the user picked
  todo_created (JSON, nullable),  -- details of any todo created
  enrichment_depth (text),        -- shallow or deep
  enrichment_calls (int),         -- API calls used
  enrichment_time_ms (int)        -- time spent enriching
```

This log is append-only and never pruned.

### Layer 2: Preference Summary (database record)

A single record that synthesizes patterns from the interaction log. Structure:

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

**Incremental updates**: `preferences.py` reads only new interaction log entries since the last cursor position (stored in a metadata table), computes updated statistics, and outputs a digest for Claude to synthesize into the updated preference summary. The full log is not re-read each time.

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

Preference tendencies override the default rubric when applicable.

## Deduplication

Check the database by source-specific artifact ID. Skip if already processed. Prevents the same item from appearing multiple times across cron runs.

## Dashboard Format

The Dashboard is stored in the database and optionally exported to Google Docs or Notion. Format:

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

Plain-text checkboxes (`- [ ]` / `- [x]`). Users edit text to mark items done. Full-document replacement is safe with this format.

## Draft Plan Creation

A "plan seed" is detected when 3+ action items or discussion points from different sources converge on the same topic within a 7-day window. When detected:

1. Gather all related context: meeting notes, emails, tasks, enrichment data from the database
2. Synthesize into a structured plan:

```markdown
# [Plan Title]
Status: draft
Created: YYYY-MM-DD
Sources: [list of meetings, tasks, posts that contributed]

## Context
[Synthesized background from all sources]

## Plan
[The actual plan content]

## Open Questions
[Anything unresolved]
```

3. Store the plan in the database, optionally export to Google Docs/Notion
4. Status lifecycle: draft → reviewed → finalized

### Marking Items Done

Users mark action items done by editing `- [ ]` to `- [x]` in the exported doc, or via the API (Phase 2: via webapp). The daily cleanup cron detects checked items and archives them.

## Claude Code Plugin Structure

```
~/.claude/plugins/local/workbench/
  .claude-plugin/plugin.json
  commands/
    process.md                 -- /process <text or doc link>: manual input processing
    setup.md                   -- /workbench:setup: deploy containers, create config, register crons
    status.md                  -- /workbench:status: show health, pending items, stats
    cleanup.md                 -- /workbench:cleanup: manual prune trigger
    sources.md                 -- /workbench:sources: list/enable/disable input sources
    triage.md                  -- /workbench:triage: manually triage pending items in the CLI
  scripts/
    doc_reader.sh              -- bash wrapper for reading docs (dispatches to provider)
    doc_sections.py            -- parse/replace doc sections by heading
    doc_export.sh              -- export Dashboard to Google Docs or Notion
    messenger.sh               -- bash wrapper for sending/reading messages (delegates to provider)
    messenger_triage.py        -- build triage cards, process responses, log interactions
    sources/
      meetings.sh              -- fetch raw meeting notes (stub — implement for your system)
      email.sh                 -- fetch raw emails from Gmail
      social.sh                -- fetch social feed posts (stub — implement for your system)
      tasks.sh                 -- fetch tasks (stub — implement for your system)
      code_review.sh           -- fetch code review items (stub — implement for your system)
    state.py                   -- read/write config, talk to API server
    preferences.py             -- incremental log digest for preference synthesis
    enrich.py                  -- context enrichment with depth/budget controls
    api_client.py              -- thin client for the Workbench API
  config/
    config.json                -- API server URL, active providers, enrichment settings, budgets
    providers.json             -- provider-specific credentials and config
  docker/
    Dockerfile                 -- API server image
    docker-compose.yml         -- API server + PostgreSQL
```

## Scripts

Thin bash wrappers handle external API calls. Python scripts handle parsing, state management, and orchestration. All state goes through the API — scripts never write to the database directly.

### Doc Operations

**`doc_reader.sh`** — Read documents from any supported provider.

- `doc_reader.sh read <doc_url>` — fetch doc content as markdown (auto-detects provider from URL)
- `doc_reader.sh provider <url>` — print which DocReader would handle this URL

**`doc_export.sh`** — Export Dashboard from database to a doc provider.

- `doc_export.sh export` — export Dashboard to the configured WorkbenchStore provider
- `doc_export.sh create <title> <body>` — create a new doc via the active provider

**`doc_sections.py`** — Parse and manipulate markdown docs by heading sections.

- `doc_sections.py get <section_heading>` — extract content under a heading
- `doc_sections.py replace <section_heading> <new_content_file>` — replace a section
- `doc_sections.py insert <section_heading> <subsection_heading> <entry>` — insert an entry
- `doc_sections.py remove-checked` — remove all `- [x]` lines, print them (for archiving)

### Messenger

**`messenger.sh`** — Bash wrapper that dispatches to the active Messenger provider.

- `messenger.sh send <text>` — send a message to the configured user
- `messenger.sh read [--since=<timestamp>]` — read recent messages
- `messenger.sh provider` — print which provider is active

**`messenger_triage.py`** — Build and manage triage cards.

- `messenger_triage.py send <item_json>` — build a triage card from an item, enrich it, send via Messenger, record in database
- `messenger_triage.py check` — read Messenger replies, match to pending triage cards, process chosen actions, log to interaction log, update filter rules
- `messenger_triage.py pending` — list items awaiting triage response

### Source Adapters

Each adapter fetches raw data and outputs simple JSON to stdout.

**`sources/meetings.sh`** — Meeting notes. Default: stub. Implement for your calendar system.
**`sources/email.sh`** — Gmail. Works everywhere via Gmail API.
**`sources/social.sh`** — Social/corporate feed posts. Default: stub.
**`sources/tasks.sh`** — Task management items. Default: stub. Implement for Jira, Linear, Asana, etc.
**`sources/code_review.sh`** — Code review items. Default: stub. Implement for GitHub PRs, GitLab MRs, etc.

Output schema (raw data only, no extraction):

```json
{
  "id": "source-specific-unique-id",
  "source_type": "meeting|email|social|task|code_review",
  "source_label": "Weekly Sync 2026-05-21",
  "raw_text": "Full content from the source"
}
```

### State & Enrichment

**`state.py`** — Config management and API delegation.
**`api_client.py`** — Thin HTTP client for the Workbench API.
**`enrich.py`** — Context enrichment with depth/budget controls and trace logging.
**`preferences.py`** — Reads new interaction log entries since last cursor, computes digest, outputs structured summary for Claude to synthesize.

## API Server

FastAPI application running in a Docker container. Endpoints:

### Items
- `POST /items` — create a new item (from pipeline)
- `GET /items` — list items with filters (priority, source, status)
- `PATCH /items/{id}` — update item (mark done, change priority)
- `DELETE /items/{id}` — archive an item

### Triage
- `POST /triage/cards` — store a triage card sent to user
- `GET /triage/pending` — list items awaiting triage response
- `POST /triage/respond` — record a triage response and execute the action

### Plans
- `POST /plans` — create a draft plan
- `GET /plans` — list plans with status filter
- `PATCH /plans/{id}` — update plan content or status

### Preferences
- `GET /preferences` — get current preference summary
- `POST /preferences` — update preference summary
- `GET /preferences/digest` — get incremental digest since last cursor

### Filter Rules
- `GET /filter-rules` — list all filter rules
- `POST /filter-rules` — add a filter rule
- `GET /filter-rules/email/{account}` — list email-specific filter rules for an account

### Interaction Log
- `POST /interactions` — log a triage interaction
- `GET /interactions` — query interaction history (with cursor-based pagination)

### Enrichment
- `GET /enrichment/trace` — query enrichment trace log
- `GET /enrichment/budget` — get current budget settings

### Config
- `GET /config` — get plugin configuration
- `PATCH /config` — update configuration

### Health
- `GET /health` — API server health check

## Database Schema (PostgreSQL)

Key tables:

- `items` — action items, meetings to schedule (id, source_type, source_id, summary, priority, status, created_at, updated_at)
- `plans` — draft plans (id, title, status, content, sources, created_at)
- `triage_cards` — sent triage cards (id, item_id, card_content, options, sent_at, responded_at, response)
- `interaction_log` — full triage card + response (id, timestamp, source_type, item_id, triage_card_full, enrichment_context, options_presented, option_chosen, todo_created, enrichment_depth, enrichment_calls, enrichment_time_ms)
- `filter_rules` — global filter rules (id, pattern, action, priority, created_from_interaction_id)
- `email_filters` — per-account email filter rules (id, account, pattern, action, created_from_interaction_id)
- `preferences` — current preference summary (id, content, cursor_position, updated_at)
- `enrichment_trace` — enrichment call log (id, item_id, depth, calls_made, time_ms, context_retrieved, timestamp)
- `processed` — dedup tracking (source_type, source_id, processed_at)
- `config` — key-value settings

## Cron Jobs

| Cron | Schedule | Purpose |
|------|----------|---------|
| Source watcher | `*/30 * * * *` | Poll all enabled sources, run pipeline, send triage cards |
| Triage response checker | `0 */2 * * *` | Read Messenger replies, process responses, update filter rules and preferences |
| Daily cleanup | `47 6 * * *` | Archive completed items, flag stale items (>14 days), re-sort Dashboard, regenerate preference summary, optionally export to Google Docs/Notion, re-create expired crons |

All crons created as `durable: true` via `CronCreate`.

**Self-healing:** The daily cleanup cron calls `CronList` and re-creates any missing crons.

## Commands

### `/process <text or doc link>`
Manual entry point. Accepts pasted text, Google Doc URL, or Notion URL. Runs the full pipeline (fetch via DocReader → Claude extraction → filter → enrich → triage card → Messenger).

### `/workbench:setup`
First-time setup:
1. Start Docker containers (API server + PostgreSQL)
2. Run database migrations
3. Store API server URL and provider config in `config.json`
4. Register the 3 cron jobs
5. Send a test message via Messenger to verify connectivity
6. Optionally create initial Dashboard export in Google Docs/Notion

### `/workbench:status`
Show: container health, API server status, cron health, pending triage cards, filter rules count, sources enabled, processed items count, enrichment budget usage.

### `/workbench:cleanup`
Manual trigger for daily cleanup logic.

### `/workbench:sources`
List enabled/disabled sources. Enable or disable sources interactively.

### `/workbench:triage`
Manually triage pending items directly in the CLI (alternative to Messenger for when you're already in Claude Code).

## Verification

1. Run `/workbench:setup` — verify containers start, database migrates, crons register
2. Run `/process` with pasted meeting notes — verify triage card sent via Messenger with correct options
3. Respond to triage card — verify item appears in database with correct priority
4. Run `/process` with a Google Doc link — verify doc content is fetched and processed
5. Wait for source watcher cron — verify it picks up new items from enabled sources
6. Respond "never" to a triage card — verify email/filter rule created
7. Run `/workbench:cleanup` — verify completed items archived, stale items flagged
8. Run `/workbench:status` — verify all systems healthy
9. Check enrichment trace log — verify budget settings respected
10. Run `preferences.py` digest — verify incremental read from last cursor

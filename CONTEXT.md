# CONTEXT.md — Domain Glossary

Meta-internal personal intelligence feed. Ingests from internal sources, filters noise adaptively, triages via Google Chat, learns from responses.

## Language

### Core

**Item**: A single actionable thing stored in the `items` table — an action item, meeting to schedule, or informational note. One raw input (email, meeting notes) produces multiple independent items via LLM extraction.
_Avoid_: "task" (ambiguous with Meta Tasks, the source system), "ticket", "entry"

**Triage Card**: A structured, source-type-specific presentation of an item awaiting user decision. Sent to Google Chat one at a time as a Card V2 with numbered options. The user responds by typing a number or clicking an openLink fallback button.
_Avoid_: "notification" (triage cards are interactive, not just alerts), "message"

**Triage Response**: A user's decision on a triage card (add todo, skip, mute source, etc.). Submitted via text reply in Google Chat (primary), openLink button click (fallback), or API/CLI.
_Avoid_: "answer", "reaction"

**Filter Rule**: A natural language pattern matched by the LLM (not regex) to auto-include or auto-drop items. Created explicitly or learned from "never"/"always" triage responses.
_Avoid_: "filter" alone (ambiguous — could mean the noise filter stage), "rule" alone

**Preference Summary**: A single synthesized record describing what the user cares about, doesn't care about, and priority tendencies. Built incrementally from the interaction log by the LLM. Loaded as context for every pipeline run.
_Avoid_: "preferences" (plural, ambiguous — could mean the raw interaction log), "profile"

**Interaction Log**: Append-only record of every triage card shown and the user's response. Source data for preference synthesis. Never pruned.
_Avoid_: "history", "audit log"

### Pipeline

**Raw Item**: Unprocessed data fetched by a source adapter — has `source_type`, `source_id`, `raw_text`. Not yet extracted.
_Avoid_: "raw data", "input"

**Extracted Item**: A single actionable thing produced by LLM extraction from a raw item. Has its own `category` (action_item, meeting, plan_seed, informational) and flows through filter/enrichment/triage independently.
_Avoid_: "parsed item", "result"

**Pipeline Job**: An async unit of work created when content enters the pipeline (via `/api/process` or source polling). Returns a job ID immediately; pipeline runs in background. Each item committed independently — partial failures don't roll back.
_Avoid_: "request", "run"

**Triage Queue**: Ordered list of triage cards waiting to be sent to Google Chat. Cards are sent one at a time, sequentially. Advances on response or timeout.
_Avoid_: "pending list", "backlog"

### Infrastructure

**Storage Backend**: The pluggable persistence layer behind the repository pattern. SQLite (Phase 1 default), XDB and PostgreSQL as later options. Selected via config. Business logic never touches SQL directly.
_Avoid_: "database" (too specific — the abstraction is the point), "store" alone (ambiguous with repository interfaces)

**Repository**: An interface for a single domain entity (e.g., `ItemStore`, `TriageStore`). Has implementations for each storage backend. The server depends only on the interface.
_Avoid_: "DAO", "model"

**Source Adapter**: A provider that polls an internal Meta system (Phabricator, Tasks, Workplace, etc.) and produces raw items. Fetch only — no semantic extraction.
_Avoid_: "connector", "integration", "plugin"

**Enrichment**: Additional context gathered about entities referenced in an item before triage — people (org chart), tasks (parent/subtasks), diffs (test results). Has depth (shallow/deep) and budget controls.
_Avoid_: "context" alone (too generic), "lookup"

**Morning Briefing**: Daily automated Google Chat message summarizing P0/P1 items, pending triage, and new items since yesterday. Sent by the scheduler at a configurable time.
_Avoid_: "daily digest" (could be confused with preference digest), "summary"

## Relationships

- One **Raw Item** produces multiple **Extracted Items** via LLM extraction
- Each **Extracted Item** gets its own relevance score, **Triage Card**, and **Item** row
- **Triage Cards** are sent to Google Chat one at a time from the **Triage Queue**
- A **Triage Response** creates an **Interaction Log** entry and may create a **Filter Rule**
- The **Interaction Log** feeds **Preference Summary** synthesis
- The **Preference Summary** informs the noise filter in every pipeline run
- **Repositories** abstract the **Storage Backend** from all business logic

## Example dialogue

> "I got a triage card for a diff but I already reviewed it."
> → Skip the card. The interaction log records the skip. If this happens often for already-reviewed diffs, the preference summary will learn to deprioritize them.

> "The morning briefing didn't include a SEV from last night."
> → Check if the SEV adapter is enabled and its poll schedule. If the SEV was ingested but auto-dropped, check filter rules — there may be a rule dropping SEVs for that service.

> "I want to switch from XDB to SQLite for testing."
> → Set `WORKBENCH_STORAGE_BACKEND=sqlite` in server config. All repositories swap to the SQLite implementation. No code changes.

## Dropped concepts

- **Workspace** — single-user tool, no multi-tenant isolation needed. All data is flat, no workspace_id scoping.
- **Credential encryption** — source adapters reference secrets via env vars or filesystem paths (DCAT certs, API keys), not stored in the DB.
- **Export** — no Google Docs / Notion export. Dashboard lives in Google Chat (morning briefing) and CLI (`/workbench:status`).
- **Multi-platform Messenger** — Google Chat only. No WhatsApp/Discord/Slack.

## Flagged ambiguities

- **"task"** is ambiguous: Meta Tasks (the source system) vs. an action item in Workbench. Use **"item"** for Workbench entities, **"Meta Task"** or **"Tasks source"** for the external system.
- **"card"** is ambiguous: Google Chat Card V2 (the rendered message) vs. triage card (the domain object). Use **"triage card"** for the domain object, **"Card V2"** or **"chat card"** for the Google Chat rendering.
- **"filter"** is ambiguous: the noise filter pipeline stage vs. a filter rule. Use **"noise filter"** for the stage, **"filter rule"** for individual patterns.

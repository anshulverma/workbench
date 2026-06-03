# CONTEXT.md -- Domain Glossary

Personal intelligence feed. Ingests from configurable sources, filters noise adaptively, triages via the configured messenger, learns from responses.

## Language

### Core

**Item**: A single actionable thing stored in the `items` table -- an action item, meeting to schedule, or informational note. One raw input (email, meeting notes) produces multiple independent items via LLM extraction. Created eagerly when the pipeline decides to triage -- status starts as `pending_triage`. Status lifecycle: `pending_triage -> active` (user accepted or auto-expired), `pending_triage -> archived` (user skipped), `active -> done`, `active -> archived`.
_Avoid_: "task" (ambiguous with external task trackers), "ticket", "entry"

**Triage Card**: A structured, source-type-specific presentation of an item awaiting user decision. Sent to the configured messenger one at a time with numbered options. The user responds by typing a number or using a messenger-specific interaction.
_Avoid_: "notification" (triage cards are interactive, not just alerts), "message"

**Triage Response**: A user's decision on a triage card (add todo, skip, mute source, etc.). Submitted via the messenger (primary) or API/CLI.
_Avoid_: "answer", "reaction"

**Filter Rule**: A natural language pattern matched by the LLM (not regex) to auto-include or auto-drop items. Created explicitly or learned from "never"/"always" triage responses.
_Avoid_: "filter" alone (ambiguous -- could mean the noise filter stage), "rule" alone

**Preference Fact**: A single learned preference extracted from triage interactions -- e.g., "user always prioritizes PRs where reviewers are blocked." Stored in the memory layer's knowledge graph, queried at scoring time by the noise filter.
_Avoid_: "preference" (singular, too vague), "rule" (ambiguous with filter rule -- filter rules are explicit and deterministic, preference facts are learned and probabilistic)

**Memory Layer**: A provider (registered in YAML config under `memory:`) for knowledge graph integration. Two implementations: `NoopMemoryLayer` (default) and `ZepMemoryLayer` (production). Records triage interactions, entities, and pipeline decisions; answers preference and relationship queries. Uses the same ProviderConfig + dynamic import pattern as other providers.
_Avoid_: "knowledge base", "brain"

**Interaction Log**: Append-only record of every triage card shown and the user's response. Source data for preference synthesis. Never pruned.
_Avoid_: "history", "audit log"

### Pipeline

**Raw Item**: Unprocessed data fetched by a source adapter -- has `source_type`, `source_id`, `raw_text`, and `urgency_signals` (flat dict of source-metadata-derived priority hints). Not yet extracted. Enters the system via the ingestion queue.
_Avoid_: "raw data", "input"

**Extracted Item**: A single actionable thing produced by LLM extraction from a raw item. Has its own `category` (action_item, meeting, plan_seed, informational) and flows through filter/enrichment/triage independently. `plan_seed` is recognized by extraction but has no special handling until Phase 2.
_Avoid_: "parsed item", "result"

**Pipeline Job**: An async unit of work tracking pipeline processing. Created eagerly at enqueue time with status `queued`. The ingestion queue is an internal mechanism -- API clients see only the job ID. Status progression: `queued -> pending -> running -> completed/failed`. Each item committed independently -- partial failures don't roll back.
_Avoid_: "request", "run"

**Triage Queue**: Durable, priority-ordered list of triage cards waiting to be sent to the configured messenger, persisted as columns on the `triage_cards` table in PostgreSQL (not a separate table). Cards are ordered by relevance score (highest first) and sent one at a time, sequentially. Queue status lifecycle: `queued -> sent -> responded / expired`. Advances on response or timeout. Has a configurable daily cap (default 20). Cards older than a configurable expiry (default 7 days) are auto-included at P3. Each card stores its `bot_message_id` for response polling recovery across restarts.
_Avoid_: "pending list", "backlog"

**Ingestion Queue**: Durable queue of raw content waiting for pipeline processing, persisted in PostgreSQL (`ingestion_queue` table). Source adapters and `/api/process` enqueue here instead of running the pipeline directly. Items are dedup-checked against the ProcessedStore at enqueue time (manual submissions bypass dedup). Each item gets a lightweight LLM urgency score inline at enqueue time for priority ordering. An in-process async worker (asyncio task with semaphore, default concurrency 2) dequeues items via `SELECT ... FOR UPDATE SKIP LOCKED` ordered by urgency score. Failed items retry with exponential backoff (`2^attempt * base_delay`) up to max_attempts (default 3), then become dead-letter entries. Dead letters are inspectable via `GET /api/queue/dead-letter`, retryable via `POST /api/queue/dead-letter/{id}/retry`, and purgeable via `DELETE /api/queue/dead-letter/{id}`. The queue is an internal mechanism -- API clients interact with pipeline jobs, not queue entries.
_Avoid_: "job queue" (ambiguous with pipeline jobs), "task queue"

**Queue Scorer**: A lightweight LLM call made inline at enqueue time that evaluates raw content + urgency signals to produce a numeric urgency score (0-100). Behind a dedicated `QueueScorer` ABC (separate from `LLMProvider`) -- the interface is `async def score_urgency(raw_text, urgency_signals) -> int`. Default implementation uses a cheap model (Haiku) via a `class:` path in `queue.scorer:` config. Determines dequeue ordering only -- does not auto-drop items.
_Avoid_: "pre-filter" (it doesn't filter), "ranker"

**Urgency Signals**: Structured metadata (`dict[str, Any]`) attached to a RawItem by the source adapter, derived from source-system metadata without LLM calls. Examples: `{"blocking_reviewer": true}`, `{"sender_is_manager": true, "subject_contains_urgent": true}`, `{"issue_priority": "P0"}`. Fed to the queue scorer as context for urgency scoring.
_Avoid_: "priority hints" (too vague), "metadata" (too generic)

**Dead Letter**: An ingestion queue entry that has exhausted its retry attempts and permanently failed. Stays in the queue with status `dead_letter` for inspection via `GET /api/queue/dead-letter`. Surfaced in the morning briefing. Not automatically retried or purged -- requires manual investigation. Recovery via `POST /api/queue/dead-letter/{id}/retry` (resets to `queued`) or `DELETE /api/queue/dead-letter/{id}` (permanent discard).
_Avoid_: "failed item" (ambiguous with pipeline failures)

### Observability and Operations

**Instrumented Wrapper**: A decorator-pattern class that wraps a provider (SourceAdapter, ContextEnricher, LLMProvider) with metrics (Prometheus counters and histograms) and structured logging without modifying the provider's own code. Applied automatically by the registry at construction time. Three implementations: `InstrumentedSourceAdapter`, `InstrumentedContextEnricher`, `InstrumentedLLMProvider`.
_Avoid_: "metrics mixin" (it's a wrapper, not a mixin -- the provider is unaware of instrumentation)

**Sanitizing Processor**: A structlog processor that redacts PII patterns (email addresses, phone numbers) and truncates free-text content in log output. Operates on structured event dicts, not formatted strings. Extensible with extra patterns via `extra_patterns` constructor arg (used by workbench-meta for PHIDs, employee IDs). Configurable via the `privacy:` config section.
_Avoid_: "log filter" (it's a structlog processor, not a stdlib logging filter)

**Correlation ID**: A UUID4 generated per HTTP request by `CorrelationIdMiddleware`, bound to structlog's contextvars so all loggers in that async context include it automatically. Returned in `X-Request-ID` response header. Pipeline jobs use their existing job_id as correlation ID during processing.
_Avoid_: "trace ID" (distinct from OpenTelemetry trace IDs, which may also be present)

**Alert Manager**: A component that evaluates health conditions (connection health, dead letters, adapter failures, queue depth) on each scheduler tick and sends alerts via the configured messenger with cooldown-based dedup. Not an external alerting system -- reuses the existing messenger provider.
_Avoid_: "monitoring" (too generic), "pager" (implies external system)

**Retention Policy**: Configurable time-based cleanup for stored data (archived items, expired cards, enrichment traces, dead letters). Executed by a daily scheduler task after the morning briefing. Interaction log is exempt -- never pruned, needed for preference learning.
_Avoid_: "garbage collection" (implies automated runtime collection)

**Connection**: A shared external system credential/session (e.g., Google OAuth2, Intern API auth) initialized once at startup and injected into adapters and enrichers that reference it by name in YAML config. Implements `Connection` ABC with `initialize()`, `close()`, `is_healthy()`. Uses factory methods (not cached properties) for API service creation to ensure thread safety under concurrent `asyncio.to_thread()` calls.
_Avoid_: "connector" (ambiguous with source adapter), "client" (a connection manages auth, not API calls)

**Composite Enricher**: A `ContextEnricher` implementation that routes to the correct source-specific enricher by `item.source_type`. Built by `create_composite_enricher()` from the `enrichment:` config section. Supports per-enricher budget overrides. Falls back to a default enricher (StubEnricher) for unknown source types.
_Avoid_: "enrichment router" (it's a concrete enricher, not a routing layer)

**Adapter State Store**: A simple utility interface (`get_state`, `save_state`, `delete_state`) for adapters that need persistent state across restarts (e.g., GChat's tracked_threads map). Backed by a PG table (`adapter_state`). Injected into adapters via `state_store` constructor arg using `inspect.signature` pattern -- adapters that don't need state don't declare the parameter.
_Avoid_: "adapter cache" (it's persistent, not a cache)

**Identity Resolution**: Automatic entity deduplication across sources within the memory service. When enrichers record entities with source-qualified IDs (e.g., `github:alice-gh`, `email:alice@meta.com`), the memory service detects matches via signal-tiered identifying attributes (strong: email/phone/platform_uid auto-merge; medium: name/username need 2+ matches; weak: supporting only) and merges into a single canonical entity with a generated UUID4 canonical ID. PG is the source of truth; Neo4j graph updated best-effort. Canonical IDs are always UUIDs, never source-qualified strings.
_Avoid_: "entity matching" (resolution implies canonical identity), "dedup" alone (it's cross-source merging, not within-source dedup)

**Entity Ref**: A dict with `type` (EntityType enum value) and `id` (source-qualified string) identifying an entity referenced by an enricher. Returned in the `entity_refs` list within enricher output dicts. Uses dict format `{"type": "person", "id": "github:alice-gh"}` (not tuples) for clean JSON/JSONB round-tripping. Card generation extracts entity refs and queries the memory service for each.
_Avoid_: "entity reference" spelled out (use "entity ref" for consistency with the field name)

**Triage Response Result**: The return type of `execute_triage_response()` — a pure data object with `explanation`, `prompt`, `followup_status`, and `actions_executed`. Enables the consolidated response handling function to remain pure (no messenger dependency). The API route returns it as JSON; the scheduler checks it and sends messenger prompts if needed.
_Avoid_: "response object" (too generic)

**Action Item**: An `Item` with `action_source` set (e.g., `"triage_response"`, `"manual"`) and `action_category` from `ActionCategory` enum. Created from user todos in free-text triage responses. Linked to a parent item via `parent_item_id`. Surfaced via `GET /api/actions`, plugin command, morning briefing, and React UI. Has `snoozed_until` (query-time filter) and `completed_at` fields.
_Avoid_: "task" (conflicts with external task trackers and Meta Tasks source), "todo" alone (too informal -- action items have structure: category, priority, parent link)

### Infrastructure

**Storage Backend**: The pluggable persistence layer behind the repository pattern. PostgreSQL is the default backend. Selected via config. Business logic never touches SQL directly. Schema managed by Alembic migrations.
_Avoid_: "database" (too specific -- the abstraction is the point), "store" alone (ambiguous with repository interfaces)

**Repository**: An interface for a single domain entity (e.g., `ItemStore`, `TriageStore`). Has implementations for each storage backend. The server depends only on the interface.
_Avoid_: "DAO", "model"

**Source Adapter**: A provider that polls an external system (GitHub, email, etc.) and produces raw items. Fetch only -- no semantic extraction. Loaded at runtime via dynamic import from the YAML config file.
_Avoid_: "connector", "integration", "plugin"

**Provider**: A pluggable implementation behind a base interface (Messenger, SourceAdapter, LLMProvider, QueueScorer, ContextEnricher, DocReader, or MemoryLayer). Each provider declares a `ProviderConfig` pydantic model for typed configuration and an `async def close(self)` method for cleanup (no-op default). The server resolves providers from dotted class paths in the YAML config via `importlib.import_module` -- it never imports or knows about specific implementations.
_Avoid_: "plugin" (overloaded -- Claude Code has plugins), "adapter" alone (ambiguous with source adapter)

**Provider Registry**: The component that discovers providers via Python entry points (for listing what's installed) and constructs them via dynamic import + typed config validation. Applies to: Messenger, SourceAdapter, LLMProvider, QueueScorer, ContextEnricher, DocReader, MemoryLayer. Storage is excluded -- it uses its own factory pattern because one storage backend produces multiple repositories in a `Stores` bundle.
_Avoid_: "service locator" (the registry is config-driven, not container-driven)

**ProviderConfig**: A pydantic `BaseModel` subclass declared as `cls.ProviderConfig` on each provider class. The server validates the YAML config section against it at startup. Full type safety -- no untyped dicts in the config pipeline.
_Avoid_: "settings" (reserved for the app-level `Settings` class)

**Config File**: YAML file (`config.yml`) declaring server settings and provider selections. Has a `version` field (semver, e.g. `0.1.0`) for format compatibility -- independent of the app version, bumped only when the config schema changes. Server validates at startup: same major = compatible, different major = hard error, minor/patch mismatch = warn. Sections: `server`, `storage`, `queue`, `triage`, `pipeline`, `scheduler`, `messenger`, `llm`, `sources`, `enrichment`, `memory`, `connections`, `privacy`, `metrics`, `tracing`, `alerting`, `retention`, `debug`. Each provider section has a `class` field (dotted import path) and provider-specific fields validated against the provider's `ProviderConfig`. Missing optional sections fall back to sensible defaults (e.g. no messenger = triage cards queued but not sent, enrichment = StubEnricher, memory = NoopMemoryLayer). Required sections: `storage` and `llm` -- server refuses to start without them. Import failures on any specified `class:` are hard errors. Secrets use OmegaConf `${oc.env:VAR}` interpolation. Layered: a base config is deep-merged with an optional override file (lists replace, dicts merge, scalars replace). The repo ships `config.example.yml` (template); `config.yml` is gitignored and generated by the setup wizard (`workbench init`). Config changes require server restart (no hot reload in Phase 1a).
_Avoid_: "settings file" (settings is the app-level pydantic class), "env file"

**App Version**: Semantic version (`major.minor.patch`) of the Workbench server, stored in `src/workbench/__init__.py` as `__version__`. Exposed in the `/health` endpoint response and docker image tags. Independent of the config file version.
_Avoid_: "release number", "build number"

**Enrichment**: Additional context gathered about entities referenced in an item before triage -- people (org chart), issues (related issues), PRs (CI results). Has depth (shallow/deep) and budget controls.
_Avoid_: "context" alone (too generic), "lookup"

**Morning Briefing**: Daily automated notification summarizing six sections: (1) P0 -- Today, (2) P1 -- This Week, (3) new items since yesterday by source type, (4) pending triage count + oldest card age, (5) queue health -- ingestion queue depth and failed/stuck items (only if non-zero), (6) auto-decisions overnight -- cards that expired and were auto-included at P3 (only if non-zero). Sent by the scheduler at a configurable time.
_Avoid_: "daily digest" (could be confused with preference digest), "summary"

## Relationships

- **Source Adapters** produce **Raw Items** with **Urgency Signals**
- **Raw Items** enter the **Ingestion Queue**, dedup-checked against the **ProcessedStore**
- The **Queue Scorer** (dedicated `QueueScorer` interface, default LLM-based with Haiku) assigns urgency priority inline at enqueue time
- An in-process async queue worker (asyncio task + semaphore) dequeues by priority via `SELECT ... FOR UPDATE SKIP LOCKED` and runs the pipeline
- One **Raw Item** produces multiple **Extracted Items** via LLM extraction
- Each **Extracted Item** gets its own relevance score; items that need triage get an **Item** row (status `pending_triage`) and a **Triage Card**
- Auto-included items get an **Item** row directly (status `active`)
- **Triage Cards** enter the **Triage Queue**, ordered by relevance score (highest first)
- Cards are sent to the configured messenger one at a time
- A **Triage Response** updates the linked **Item** (status, priority), creates an **Interaction Log** entry, and may create a **Filter Rule**
- Skip responses set the **Item** to `archived`
- The **Interaction Log** is dual-written to the **Memory Layer**
- The memory layer extracts **Preference Facts** from interactions continuously
- The **Memory Layer** informs the noise filter, enrichment, triage card generation, and queue scoring
- **Repositories** abstract the **Storage Backend** (PostgreSQL) from all business logic
- The **Provider Registry** resolves all providers (messenger, LLM, queue_scorer, source, enrichment, doc_reader, memory) from YAML config via dynamic import
- **Connections** are initialized first at startup; adapters and enrichers reference them by name and receive them via constructor injection
- **Source Adapters** that need persistent state declare a `state_store` parameter and receive an **Adapter State Store**
- The **Composite Enricher** routes enrichment to source-specific enrichers by `source_type`
- **Enrichers** return `entity_refs` as list of dicts `[{"type": "person", "id": "github:alice-gh"}]`; the **Memory Layer** performs **Identity Resolution** to merge cross-source entities into canonical UUID4-keyed entities
- Free-text **Triage Responses** are interpreted by the LLM into system actions + user todos; user todos create **Action Items**
- **Action Items** link to parent items, have categories, and surface in the morning briefing, API, plugin, and React UI
- **Instrumented Wrappers** are applied to all providers at registry construction time -- adapters and enrichers get Prometheus metrics automatically
- **Alert Manager** evaluates health conditions each scheduler tick and sends alerts via the configured messenger
- **Retention Policy** cleans up expired data daily; **Interaction Log** is exempt

## Example dialogue

> "I got a triage card for a PR but I already reviewed it."
> -> Skip the card. The interaction log records the skip. If this happens often for already-reviewed PRs, the preference facts will learn to deprioritize them.

> "The morning briefing didn't include a critical issue from last night."
> -> Check if the relevant source adapter is enabled and its poll schedule. If the issue was ingested but auto-dropped, check filter rules -- there may be a rule dropping items for that category.

> "The ingestion queue is backing up -- 50 items waiting."
> -> Check queue health. If the LLM provider is rate-limited, the worker can't dequeue fast enough. Consider bumping `queue.worker_concurrency` in config.yml, or check for dead-letter items that may indicate a persistent failure.

## Dropped concepts

- **Workspace** -- single-user tool, no multi-tenant isolation needed. All data is flat, no workspace_id scoping.
- **Credential encryption** -- source adapters reference secrets via env vars or filesystem paths, not stored in the DB.
- **Export** -- no document export. Dashboard lives in the messenger (morning briefing) and CLI (`workbench status`).
- **Preference Summary** (hand-rolled) -- replaced by the memory layer's knowledge graph and automatic fact extraction.
- **pydantic-settings** -- replaced by YAML config with OmegaConf for env var interpolation. All config models are plain `pydantic.BaseModel`, not `BaseSettings`.
- **Heuristic queue scoring** -- replaced by LLM-based queue scoring. Static source-type priority is too blunt; an LLM can weigh contextual urgency signals.
- **POST/DELETE /api/sources** -- source creation/deletion is YAML-config-only. API manages runtime state (enable/disable, schedule) via GET and PATCH.
- **POST /api/reload** -- deferred. Config changes require server restart for Phase 1a.
- **`subprocess.run` for external calls** -- replaced by `asyncio.create_subprocess_exec` in all providers to avoid blocking the event loop.
- **Thread pool executor for pipeline** -- unnecessary since all pipeline code is fully async (AsyncAnthropic, asyncpg, async subprocess). Concurrency controlled by asyncio.Semaphore.
- **`server/` package layout** -- replaced by `src/workbench/` for proper Python packaging. Class paths in YAML config use `workbench.providers...` not `server.providers...`.

## Flagged ambiguities

- **"task"** is ambiguous: external task trackers vs. an action item in Workbench. Use **"item"** for Workbench entities, specify the external system name for the source.
- **"filter"** is ambiguous: the noise filter pipeline stage vs. a filter rule. Use **"noise filter"** for the stage, **"filter rule"** for individual patterns.

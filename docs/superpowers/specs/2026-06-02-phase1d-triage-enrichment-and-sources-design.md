# Phase 1d: Memory-Enriched Triage Cards, Connections, Source Adapters, and Action Items — Design Spec

## Context

Phase 1c delivered entity knowledge, decision recording, relationship querying, and memory rebuild. The memory service now records entities and pipeline decisions, and the noise filter uses entity/relationship context for scoring. However, triage cards are still template-based — they don't leverage memory context — and only two source adapters exist (GitHub in core, Phabricator in workbench-meta). Content from email, calendar, chat, tasks, workplace, and docs doesn't flow into the system.

Phase 1d fills these gaps with three independent tracks:

- **Track A** — Source adapters and enrichers for 6 new content sources, built on a shared connection abstraction
- **Track B** — LLM-generated triage cards with memory context, identity resolution, free-text responses, and dynamic options
- **Track C** — Action items system with categorized todo list, surfaced via API, plugin, morning briefing, and React UI

## Goals

1. **Connections** — First-class config section for shared external system credentials. Adapters and enrichers reference a connection by name instead of managing their own auth.
2. **Source adapters** — 6 new adapters (3 generic in core, 3 Meta-internal in workbench-meta) so email, calendar, chat, tasks, workplace, and docs flow into the ingestion pipeline.
3. **Source-specific enrichers** — Each new source type gets a paired enricher that uses the same connection as its adapter. A `CompositeEnricher` routes to the right enricher by source type. All enrichers return a standardized `entity_refs` field.
4. **Identity resolution** — Automatic entity deduplication across sources using signal-tiered identifying attributes, backed by a PG lookup table in the memory service.
5. **Memory-enriched triage cards** — Replace template-based card generation with an LLM call that synthesizes item summary + enrichment context + entity knowledge + relationships + preference facts into a contextual card body with dynamic options.
6. **Free-text triage responses** — Users can type free-text instructions instead of picking a numbered option. An LLM interprets the instruction into system actions and user todos.
7. **Action items** — User-generated todos from triage responses, linked to parent items, categorized, and surfaced via API, plugin, morning briefing, and a React UI.

## Architecture

### Three Independent Tracks

```
Track A (Sources)                Track B (Cards)                  Track C (Actions)

connections:                     Item + Enrichment Context        "add as P3 and assign to bob"
├── google (OAuth2)                + entity_refs                        │
│   ├── Gmail + Enricher           + identity resolution                ▼
│   ├── GCalendar + Enricher       + query_entity (merged)       LLM interprets
│   └── GChat + Enricher           + query_relationships               │
└── meta_intern                    + query_preferences           ┌─────┴──────┐
    ├── MetaTasks + Enricher            │                        │            │
    ├── Workplace + Enricher            ▼                   System       User todos
    └── MetaDocs + Enricher      LLM card generation        actions      (new Items)
         │                       (always LLM)               (execute)         │
         ▼                             │                                      ▼
    RawItem → Ingestion Queue          ▼                              Action list UI
                                 TriageCard                           (React + API +
                                 + Other / free-text                   briefing + plugin)
                                 + suggested with fact citation
```

## Connections

### Connection ABC

New provider type in `workbench/providers/connection/base.py`:

```python
class Connection(ABC):
    class ProviderConfig(BaseModel):
        pass

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_healthy(self) -> bool: ...
```

Connections are initialized once at startup and shared by all adapters and enrichers that reference them. The provider registry resolves connections before adapters/enrichers, then injects them.

### How connections reach adapters and enrichers

The provider registry resolves connections first (by name from the `connections:` config section). When constructing an adapter or enricher, the registry:

1. Pops the `connection:` field from the config dict (if present)
2. Resolves the named connection from the connections dict
3. Builds the `ProviderConfig` from remaining keys
4. Calls the constructor with two args: `cls(typed_config, connection=resolved_connection)`

Adapter/enricher constructors follow this pattern:

```python
class GmailAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        label_filters: list[str] = ["INBOX", "UNREAD"]
        max_results: int = 50

    def __init__(self, config: ProviderConfig, connection: GoogleConnection | None = None):
        self._config = config
        self._connection = connection
```

Adapters/enrichers that don't need a connection (like `GitHubSourceAdapter` using `gh` CLI) keep the old single-arg signature — the registry only passes `connection` when the config declares one.

### GoogleConnection

`workbench/providers/connection/google.py`

Wraps the Google API client library with auto-refreshing OAuth2 tokens. Manages a single set of credentials with multiple API scopes. Uses a Google Workspace account (@meta.com).

```python
class GoogleConnection(Connection):
    class ProviderConfig(BaseModel):
        credentials_path: str
        token_path: str
        scopes: list[str]

    async def initialize(self) -> None:
        # Load credentials, refresh token if expired
        # Build service clients for each API

    @property
    def gmail(self): ...      # Gmail API service

    @property
    def calendar(self): ...   # Calendar API service

    @property
    def chat(self): ...       # Chat API service
```

**First-time setup:** Requires a one-time interactive OAuth consent flow. The adapter raises a clear error with instructions if `token_path` doesn't exist. Token refresh is automatic thereafter.

**Token persistence in Docker:** The `token_path` must point to a mounted volume, not a container-internal path. Set `GOOGLE_TOKEN_PATH` to a path on the data volume (same volume where PG data lives) so the token survives container restarts.

**Scopes:** Combined into a single OAuth consent. Adding a new Google adapter doesn't require re-consent unless it needs a new scope.

**Async wrapping:** The Google API client library (`google-api-python-client`) is synchronous. Each Google adapter wraps its entire `poll()` and `enrich()` method body in a single `asyncio.to_thread()` call — one thread per adapter per cycle. Internal methods `_poll_sync(since)` and `_enrich_sync(item, ...)` contain all synchronous Google API work; the async public methods delegate to them via `asyncio.to_thread(self._poll_sync, since)`. Per-API-call wrapping is unnecessary since Google API calls within a single poll are sequential (pagination).

**Startup failure:** If `initialize()` fails (bad credentials, expired token, network error), the server refuses to start with a clear error message. Connections must initialize successfully — there is no degraded startup mode. Runtime health checks (`is_healthy()`) handle mid-run failures gracefully (adapters skipped, morning briefing notes unhealthy connections).

**Token expiry recovery:** If the OAuth refresh token expires mid-run (rare — Google refresh tokens last until revoked), `is_healthy()` returns `False`, adapters are skipped, and the morning briefing warns about the unhealthy connection. Recovery: run `workbench init --reauth google` and restart the server.

### InternConnection (workbench-meta)

`workbench_meta/providers/connection/intern.py`

Wraps Intern API / GraphQL authentication. Shared by Meta Tasks, Workplace, and Docs adapters.

**Auth mechanism:** Must be resolved before implementing Meta adapters. Investigate what auth mechanisms are available on devgpu for Intern API and Workplace Graph API. Determine if `meta` CLI authentication can be reused. Implement `InternConnection` with the real auth mechanism before proceeding with Meta adapter implementation. Google adapters and Tracks B+C can proceed in parallel.

### Config

```yaml
connections:
  google:
    class: workbench.providers.connection.google.GoogleConnection
    credentials_path: ${oc.env:GOOGLE_CREDENTIALS_PATH}
    token_path: ${oc.env:GOOGLE_TOKEN_PATH}
    scopes:
      - https://www.googleapis.com/auth/gmail.readonly
      - https://www.googleapis.com/auth/calendar.readonly
      - https://www.googleapis.com/auth/chat.spaces.readonly

  meta_intern:
    class: workbench_meta.providers.connection.intern.InternConnection
```

Adapters and enrichers reference connections by name:

```yaml
sources:
  - class: workbench.providers.source.gmail.GmailAdapter
    connection: google
    label_filters: ["INBOX", "UNREAD"]
```

### Config version bump

Adding the `connections:` section and changing the `enrichment:` section shape are config schema changes. Bump config version to `0.3.0` (from current `0.2.1`). The `enrichment:` change has a backward-compat normalizer (`_normalize_enrichment` model validator) so old-style `{class: ...}` configs still load, but the version bump signals the config evolution. Configs without a `connections:` section are valid — adapters that don't need a connection are unaffected.

## Track A: Source Adapters

All adapters implement the existing `SourceAdapter` ABC: `poll(since: datetime | None) -> list[RawItem]`.

### Adapter error isolation

The scheduler wraps each `source.poll()` call in a try/except, logs the error, and continues to the next adapter. A broken Gmail adapter does not prevent GitHub or Phabricator from polling. Failed adapters retry on the next poll cycle. The scheduler checks `connection.is_healthy()` before polling and skips adapters whose connection is unhealthy with a warning log.

### Adapter state persistence

Adapters that need persistent state across restarts (e.g., GChat's `tracked_threads` map) use an `adapter_state` PG table:

```sql
CREATE TABLE adapter_state (
    adapter_name TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

A new `AdapterStateStore` interface provides `get_state(name) -> dict | None` and `save_state(name, state: dict)`. PG implementation uses the table above.

Adapters that need state declare a `state_store` parameter in their constructor:

```python
class GChatAdapter(SourceAdapter):
    def __init__(self, config: ProviderConfig, connection=None, state_store=None):
        self._state_store = state_store
```

The registry inspects the constructor signature (same pattern as `connection`) and injects the `state_store` if declared.

### Gmail (core)

`workbench/providers/source/gmail.py`

**Connection:** `google`

**Config:**
```yaml
- class: workbench.providers.source.gmail.GmailAdapter
  connection: google
  label_filters: ["INBOX", "UNREAD"]
  max_results: 50
```

**Poll behavior:** Queries Gmail API for messages matching label filters with `after:{since_epoch}`. Each email becomes a `RawItem`:
- `source_type`: `"email"`
- `source_id`: `"email_{message_id}"`
- `raw_text`: JSON with subject, sender, recipients (to/cc), body, snippet, thread_id, attachments metadata
- `urgency_signals`: `{sender: str, is_direct: bool, cc_count: int, thread_depth: int, has_attachments: bool, labels: list[str]}`

**Body extraction:**
1. Prefer `text/plain` MIME part if available
2. Fall back to HTML → strip tags to plain text
3. Strip quoted reply chains (lines starting with `>`)
4. Strip email signatures (content after `--` on its own line)
5. Truncate to 4000 chars after all stripping

**Attachment handling:** The adapter captures attachment metadata in `raw_text`, not content:
```json
{
  "attachments": [
    {"filename": "screenshot.png", "mime_type": "image/png", "size_bytes": 45000, "attachment_id": "ANGj...", "inline": false},
    {"filename": "cid:image001", "mime_type": "image/png", "size_bytes": 12000, "attachment_id": "BNHk...", "inline": true}
  ]
}
```

Inline images (embedded in HTML body) are captured with `inline: true`. Actual attachment content is fetched by the enricher (see GmailEnricher), not the adapter.

**Dedup:** `source_id` uses Gmail's immutable message ID. The existing `ProcessedStore.is_processed()` prevents reprocessing.

### Google Calendar (core)

`workbench/providers/source/gcalendar.py`

**Connection:** `google`

**Config:**
```yaml
- class: workbench.providers.source.gcalendar.GCalendarAdapter
  connection: google
  calendar_ids: ["primary"]
  lookahead_hours: 48
```

**Poll behavior:** Queries Calendar API for events in the lookahead window that are new or updated since `since` (uses `updatedMin` parameter). Each event becomes a `RawItem`:
- `source_type`: `"calendar"`
- `source_id`: `"cal_{event_id}"` (see dedup below)
- `raw_text`: JSON with title, description, attendees, location, start/end times, organizer, conference link
- `urgency_signals`: `{attendee_count: int, is_organizer: bool, starts_within_hours: int, has_agenda: bool, is_recurring: bool, recurring_event_id: str | None}`

**Dedup:** Uses a hash of meaningful fields `(title, description, start_time, end_time, location)` to detect real changes. The adapter maintains a local dict of `event_id → last_hash`. On poll:
1. Compute hash of meaningful fields for each event
2. If hash matches `last_hash[event_id]`, skip (RSVP changes, attendee updates don't trigger re-ingestion)
3. If hash differs or event is new, produce a RawItem and update the hash

**Recurring events:** Each instance of a recurring event has a unique `event_id` with a different start time, so each instance hashes differently and is ingested once. Subsequent instances of "weekly standup" will be auto-dropped by the noise filter as the memory service learns the pattern. `is_recurring: true` and `recurring_event_id` in urgency signals give the filter signal to learn faster.

**All-day events:** Events with `date` instead of `dateTime` are included with adapted signals. Start time is treated as midnight of the event date. `starts_within_hours` is calculated from midnight. Urgency signals include `is_all_day: true`. The noise filter learns from user responses whether all-day events (typically holidays, birthdays, reminders) should be dropped.

### Google Chat (core)

`workbench/providers/source/gchat.py`

**Connection:** `google`

**Config:**
```yaml
- class: workbench.providers.source.gchat.GChatAdapter
  connection: google
  spaces: ["spaces/AAAA..."]
  exclude_spaces: ["spaces/JARVIS..."]   # exclude the messenger/bot space
  track: "participating"   # "participating" | "mentioned" | "all"
```

**Important distinction:** This is the *ingestion* side — reading messages from spaces you want to monitor. The *messenger* provider (sending triage cards via Google Chat) is a separate interface with its own auth, already in workbench-meta as WIB Google Chat. They do NOT share a connection. The `exclude_spaces` list should include the jarvis bot / triage card space to prevent ingesting triage-related messages. If `spaces` is set to `"all"`, the adapter fetches all spaces the user is in via the Chat API and filters out `exclude_spaces`.

**Track modes:**
- `participating` (default) — track threads where you've posted a message or been @mentioned
- `mentioned` — only track threads where you're @mentioned
- `all` — track every thread in the space (for small/important spaces)

**Thread subscription model:** The adapter maintains a persistent map of `thread_id → last_read_timestamp` for threads it's tracking.

1. **Thread enters tracking** when: you post a message in it (participation), you're @mentioned, or it's a DM
2. **On each poll**, the adapter fetches all new messages in configured spaces since last poll. For each message:
   - If you authored it or are @mentioned → ensure that thread is tracked
   - Messages from the bot's own identity are filtered out to avoid feedback loops
3. **For all tracked threads with new messages**, produce a RawItem with the full thread context (all messages, not just delta)
4. **Update `last_read_timestamp`** for that thread
5. **Thread exits tracking** after 48h of inactivity (no new messages)
6. **Thread re-enters tracking** if you participate or are @mentioned again after exit

**RawItem fields:**
- `source_type`: `"gchat_message"`
- `source_id`: `"gchat_{thread_id}_{last_message_timestamp}"`
- `raw_text`: JSON with all thread messages (text, sender, timestamp), space name, thread name, annotations
- `urgency_signals`: `{is_mention: bool, is_direct_message: bool, thread_depth: int, sender: str, space_name: str}`

**Thread state persistence:** The adapter persists its `tracked_threads` map via the `AdapterStateStore` PG table. On each poll, the adapter saves the current `tracked_threads` map as JSON. On startup, it loads from the store (or starts fresh if no state exists).

**Feedback loop prevention (defense-in-depth):** Three layers prevent the GChat adapter from ingesting triage card messages:
1. `exclude_spaces` config — the messenger/bot space must be listed
2. **Startup validation** — the adapter warns if the messenger space is not in `exclude_spaces`
3. **Bot message filtering** — messages from the bot's own identity are always filtered out
4. **Triage response filtering** — purely numeric messages (1-9) are skipped as likely triage responses

### Meta Tasks (workbench-meta)

`workbench_meta/providers/source/meta_tasks.py`

**Connection:** `meta_intern`

**Config:**
```yaml
- class: workbench_meta.providers.source.meta_tasks.MetaTasksAdapter
  connection: meta_intern
  query_filters:
    owner: "anshulverma"
    status: ["open"]
```

**Poll behavior:** Queries tasks assigned to/owned by the configured user, updated since `since`. Uses `meta tasks.task list` CLI or GraphQL Intern API. Each task becomes a `RawItem`:
- `source_type`: `"task"`
- `source_id`: `"task_{task_id}_{updated_timestamp}"`
- `raw_text`: JSON with title, description, status, priority, assignee, tags, parent task, subtasks
- `urgency_signals`: `{priority: str, has_blockers: bool, due_date: str | None, subtask_count: int, is_assigned_to_me: bool}`

### Workplace (workbench-meta)

`workbench_meta/providers/source/workplace.py`

**Connection:** `meta_intern`

**Config:**
```yaml
- class: workbench_meta.providers.source.workplace.WorkplaceAdapter
  connection: meta_intern
  groups: ["group_id_1", "group_id_2"]
```

**Poll behavior:** Queries posts from configured groups since `since`. Each post becomes a `RawItem`:
- `source_type`: `"workplace"`
- `source_id`: `"wp_{post_id}"`
- `raw_text`: JSON with content, author, group name, permalink, attachments
- `urgency_signals`: `{author: str, group_name: str, comment_count: int, is_mention: bool, reaction_count: int}`

**API:** Uses Workplace's own Graph API for data access. Auth is shared via `InternConnection` — the connection provides the auth token/cookie, and the adapter uses it to call Workplace's Graph API endpoints.

### Internal Docs/Wiki (workbench-meta)

`workbench_meta/providers/source/docs.py`

**Connection:** `meta_intern`

**Config:**
```yaml
- class: workbench_meta.providers.source.docs.MetaDocsAdapter
  connection: meta_intern
  wiki_spaces: ["space_1"]
  watch_tags: ["infra", "oncall"]
```

**Poll behavior:** Queries wiki/doc updates in watched spaces since `since` via Intern API / GraphQL. Each doc becomes a `RawItem`:
- `source_type`: `"doc"`
- `source_id`: `"doc_{page_id}_{revision_id}"`
- `raw_text`: JSON with title, content (truncated), author, tags, permalink, last_editor
- `urgency_signals`: `{author: str, is_new: bool, tags: list[str], edit_count: int}`

## Track A: Source-Specific Enrichers

Each source type gets a paired enricher that uses the same connection as its adapter.

### EntityType Enum

All enrichers return entity references using a fixed `EntityType` enum:

```python
class EntityType(str, Enum):
    PERSON = "person"
    REPO = "repo"
    TEAM = "team"
    SPACE = "space"
    GROUP = "group"
```

Extend the enum when new entity types are needed. Enrichers must use these values — free-form strings are not allowed.

### Standardized `entity_refs` output

Every enricher returns an `entity_refs` field in its output dict. Entity IDs are source-qualified to support identity resolution. Uses list of dicts (not tuples) for clean JSON/JSONB round-tripping:

```python
{
    "entity_refs": [
        {"type": "person", "id": "github:alice-gh"},
        {"type": "repo", "id": "github:owner/infra-core"},
    ],
    # ...rest of enrichment context
}
```

Entity ref mapping by source type:

| Source type | Entity refs extracted |
|------------|---------------------|
| `email` | `{type: person, id: "email:{sender}"}`, `{type: person, id: "email:{recipient}"}` per recipient |
| `github` | `{type: person, id: "github:{author}"}`, `{type: repo, id: "github:{repo}"}`, `{type: person, id: "github:{reviewer}"}` per reviewer |
| `calendar` | `{type: person, id: "gcal:{organizer}"}`, `{type: person, id: "gcal:{attendee}"}` per attendee |
| `gchat_message` | `{type: person, id: "gchat:{sender}"}`, `{type: space, id: "gchat:{space_id}"}` |
| `task` | `{type: person, id: "task:{assignee}"}`, `{type: person, id: "task:{reporter}"}`, `{type: team, id: "task:{team_tag}"}` per team tag |
| `workplace` | `{type: person, id: "wp:{author}"}`, `{type: group, id: "wp:{group_id}"}`, `{type: team, id: "wp:{group_name}"}` when group maps to a team |
| `doc` | `{type: person, id: "doc:{author}"}`, `{type: person, id: "doc:{last_editor}"}` |
| `diff` | `{type: person, id: "diff:{author}"}`, `{type: person, id: "diff:{reviewer}"}` per reviewer, `{type: repo, id: "diff:{repo}"}` |

### Enricher identifying attributes

Each enricher extracts identifying attributes as part of entity facts. These are used by the identity resolution system to automatically merge entities across sources:

| Fact key | Signal tier | Description |
|----------|------------|-------------|
| `email` | Strong (auto-merge on single match) | Email address |
| `phone` | Strong | Phone number |
| `platform_uid` | Strong | Platform-unique ID (PHID, GitHub user ID) |
| `name` | Medium (needs 2+ medium matches) | Display name / full name |
| `username` | Medium | Platform username |
| `first_name` | Weak (supporting only) | First name |
| `timezone` | Weak | Timezone |
| `title` | Weak | Job title |

Enrichers include these in the facts dict when available:
```python
await memory.record_entity(
    EntityType.PERSON, "github:alice-gh",
    {"email": "alice@meta.com", "name": "Alice Smith", "team": "infra", "platform_uid": "gh:12345"}
)
```

### CompositeEnricher

New enricher in `workbench/providers/enrichment/composite.py` that routes to the right enricher by source type:

```python
class CompositeEnricher(ContextEnricher):
    def __init__(self, enrichers: dict[str, ContextEnricher], default: ContextEnricher | None = None,
                 budgets: dict[str, EnrichmentBudget] | None = None):
        self.enrichers = enrichers
        self.default = default or StubEnricher()
        self.budgets = budgets or {}

    async def enrich(self, item, depth, budget, memory):
        enricher = self.enrichers.get(item.source_type, self.default)
        effective_budget = self.budgets.get(item.source_type, budget)
        try:
            return await enricher.enrich(item, depth, effective_budget, memory=memory)
        except Exception:
            logger.warning("enricher_failure", extra={
                "source_type": item.source_type,
                "enricher_class": type(enricher).__name__,
                "item_id": item.id,
            }, exc_info=True)
            return {}
```

Constructed by a dedicated `create_composite_enricher(config, connections)` function in `registry.py` — not the generic `create_provider()`. This function:
1. Iterates over `config.enrichment.providers`
2. Pops `source_types`, `connection`, `budget` from each entry before building ProviderConfig
3. Creates each enricher with connection injection
4. Builds the `{source_type: enricher}` mapping and `{source_type: budget}` mapping
5. Resolves the default enricher from `config.enrichment.default` (a class path, not a magic string)
6. Constructs and returns `CompositeEnricher(mapping, default, budgets)`

### Enrichment Config

The `enrichment:` config section changes from a single provider (`dict | None`) to a structured `EnrichmentConfig` model. **This is a breaking change** — existing configs must be migrated.

New config shape:

```yaml
enrichment:
  providers:
    - class: workbench.providers.enrichment.gmail.GmailEnricher
      connection: google
      source_types: ["email"]
      budget:
        max_api_calls: 8
        max_seconds: 20
    - class: workbench.providers.enrichment.github.GitHubEnricher
      source_types: ["github"]
      # uses global default budget: max_api_calls=3, max_seconds=10
    - class: workbench.providers.enrichment.gcalendar.GCalendarEnricher
      connection: google
      source_types: ["calendar"]
    - class: workbench.providers.enrichment.gchat.GChatEnricher
      connection: google
      source_types: ["gchat_message"]
  default:
    class: workbench.providers.enrichment.stub.StubEnricher
```

In `config.py`:

```python
class EnrichmentConfig(BaseModel):
    providers: list[dict] = []
    default: dict = Field(default_factory=lambda: {"class": "workbench.providers.enrichment.stub.StubEnricher"})
```

### Enricher Details

| Enricher | Connection | What it fetches |
|----------|-----------|-----------------|
| `GmailEnricher` | `google` | Full thread (other messages in thread), sender contact info, attachment content via `llm.describe_attachment()`: images described via Claude vision API, PDFs text-extracted via pdfplumber (first 5 pages, configurable). Attachments over 10MB skipped with a note in enrichment context. |
| `GCalendarEnricher` | `google` | Attendee org info (if available), related documents linked in description, recurring event pattern |
| `GChatEnricher` | `google` | Full thread context (prior messages), space description, linked resources |
| `MetaTasksEnricher` | `meta_intern` | Subtask list, blocker details, related diffs, parent task context |
| `WorkplaceEnricher` | `meta_intern` | Top comments, reactions summary, linked resources, author role |
| `MetaDocsEnricher` | `meta_intern` | Doc content summary (longer excerpt), recent edit history, linked tasks, related docs |
| `GitHubEnricher` | (gh CLI) | Existing — unchanged. Files changed, review status, labels, CI status, assignees, comment count |

Each enricher follows the `ContextEnricher` ABC: `async def enrich(self, item, depth, budget, memory) -> dict`. The returned dict is source-type-specific but always contains `entity_refs` and fields the card renderer can use.

### Enricher + Memory Integration

Per Phase 1c design, enrichers now accept a `memory: MemoryLayer` parameter. Source-specific enrichers:
1. Query `memory.query_entity()` for known context about referenced entities (authors, repos, teams) before making external calls
2. Record `memory.record_entity()` with newly discovered facts after enrichment — including identifying attributes for identity resolution

This applies to all new enrichers, not just GitHubEnricher.

## Identity Resolution

### Overview

Automatic entity deduplication across sources. When `GmailEnricher` records `(PERSON, "email:alice@meta.com")` and `GitHubEnricher` records `(PERSON, "github:alice-gh")`, the system detects they're the same person (matching email address) and merges their facts into a single canonical entity.

Identity resolution lives in the **memory service** — the workbench side just sends source-qualified IDs and facts. The memory service handles resolution, merging, and canonical ID management internally.

### Schema

New table in the memory database:

```sql
CREATE TABLE entity_identities (
    entity_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    resolved_by TEXT NOT NULL,       -- "heuristic", "llm", "manual"
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, source_id)
);
CREATE INDEX idx_entity_identities_canonical ON entity_identities(entity_type, canonical_id);
```

The existing `entities` table is keyed by `(entity_type, entity_id)` where `entity_id` = `canonical_id` (a generated UUID, not a source-qualified ID — see Resolution Algorithm below).

### Resolution algorithm

When `POST /record/entity` receives `(PERSON, "github:alice-gh", {email: "alice@meta.com", name: "Alice Smith", team: "infra"})`:

1. **Check identity table** for `(PERSON, "github:alice-gh")` → if found, use existing `canonical_id`, skip to step 3

2. **Search for matches** using identifying attributes with signal-tiered scoring:

   ```
   score = 0
   For each fact in the new entity:
     Search existing entities for matching fact values:
       strong match (email, phone, platform_uid): +10 points each
       medium match (name, username): +5 points each
       weak match (first_name, timezone, title): +1 point each

   if score >= 10 → auto-merge (one strong, or two medium)
   ```

   - **Match found** → use that entity's `canonical_id`, insert identity mapping `(PERSON, "github:alice-gh") → canonical_id`
   - **No match** → generate a new UUID as `canonical_id`, insert identity mapping

3. **UPSERT facts** into `entities` table under `(PERSON, canonical_id)` via JSONB `||` merge

4. **Update Neo4j graph** (best-effort) — create/update node under the canonical identity. If Neo4j fails, log warning and continue — PG is the source of truth for identity resolution.

### Query path

```python
async def query_entity(self, entity_type, source_id):
    canonical = await self._resolve_canonical(entity_type, source_id)
    return await self._fetch_entity(entity_type, canonical or source_id)
```

`query_entity(PERSON, "email:alice@meta.com")` resolves through the identity table to the canonical entity and returns all merged facts from all sources.

### Late discovery merge

When a new identifying attribute is discovered that links two previously separate canonical entities (e.g., you learn on day 5 that `github:alice-gh` has email `alice@meta.com`, matching an existing `email:alice@meta.com` canonical entity):

1. Pick one canonical ID as the survivor (the one with more facts)
2. In a single PG transaction:
   a. Repoint all `entity_identities` rows from the absorbed canonical to the survivor
   b. Merge facts from the absorbed entity into the survivor via JSONB `||`
   c. Delete the absorbed entity row from the `entities` table
3. After PG transaction commits, merge Neo4j graph nodes (best-effort). If Neo4j fails, log warning with both canonical IDs. The query path resolves through PG's identity table, so queries return correct merged facts even if Neo4j is stale.

### Manual override

Two admin endpoints for correcting wrong merges, exposed on both the memory service and proxied through workbench for a single API surface:

- `POST /api/admin/merge-entities` — manually merge two entities. Same process as late discovery merge.
- `POST /api/admin/split-entity` — split a source_id out of a canonical entity into its own canonical entity. Creates a new entity with only the facts from that source, repoints the identity mapping.

Both operations update the identity table and entities table in a single PG transaction, then update Neo4j best-effort. The `HttpMemoryLayer` interface gains `merge_entities()` and `split_entity()` methods. Workbench proxies these calls to the memory service.

### Example lifecycle

```
Day 1: GitHub PR from alice-gh
  record_entity(PERSON, "github:alice-gh", {email: "alice@meta.com", name: "Alice Smith", team: "infra"})
  → no existing match → canonical_id = uuid("a1b2c3d4-...") (generated UUID)
  → identity: (PERSON, "github:alice-gh") → "a1b2c3d4-..."
  → entities: (PERSON, "a1b2c3d4-...") = {email, name, team}

Day 2: Email from alice@meta.com
  record_entity(PERSON, "email:alice@meta.com", {email: "alice@meta.com", name: "Alice Smith"})
  → search: PERSON with email="alice@meta.com"? Yes → canonical_id = "a1b2c3d4-..."
  → identity: (PERSON, "email:alice@meta.com") → "a1b2c3d4-..."
  → entities: facts merged (team preserved from day 1)

Day 3: Phabricator diff from alice
  record_entity(PERSON, "diff:alice", {name: "Alice Smith", reviews: ["infra-core"]})
  → search: PERSON with name="Alice Smith"? Yes, score=5 (medium). Need 10. Not enough alone.
  → BUT if alice has username="alice" matching... depends on available facts.
  → If no auto-merge: new canonical_id = uuid("e5f6g7h8-..."), separate entity
  → If later alice's PHID is discovered matching: late discovery merge kicks in
```

## Track B: Memory-Enriched Triage Cards

### Current State

`generate_card()` in `pipeline/triage.py` delegates to `llm.generate_triage_card()` which is template-based:
- `card_content` = `{summary, source_type, enrichment}`
- Options are hardcoded per source type (Add todo P1, Add todo P2, Skip, Mute)
- No memory context consulted

### New Card Generation Flow

`generate_card()` gains a `memory: MemoryLayer` parameter. The flow:

1. **Extract entity references** from the enrichment context's `entity_refs` field
2. **Query memory** for each referenced entity in parallel (entity IDs resolve through identity table to canonical entities):

```python
entity_refs = enrichment_context.get("entity_refs", [])
entities_and_rels = await asyncio.gather(
    *[memory.query_entity(ref["type"], ref["id"]) for ref in entity_refs],
    *[memory.query_relationships(ref["type"], ref["id"]) for ref in entity_refs],
    memory.query_preferences(item.summary),
)
```

3. **Build memory context** from results:

```python
memory_context = {
    "entity_facts": {f"{ref['type']}:{ref['id']}": e.facts for ref, e in zip(entity_refs, entities) if e},
    "relationships": all_relationships,
    "preference_facts": [f.content for f in preferences],
}
```

4. **No caps on memory context** — send all entity_refs, all relationships, and all preference facts to the LLM. For a single-user tool with bounded daily throughput (10-20 items), prompt sizes are manageable. The LLM decides what's relevant.

5. **Store memory context on card** — save the `memory_context` dict in `card_content["memory_context"]` at generation time. This is used later by `interpret_triage_response()` so the interpreter has the same context the user saw.

6. **Call LLM** for card generation — always, regardless of memory availability. If memory is unavailable, `memory_context` is empty but the LLM still generates a card body from the enrichment context alone. Template fallback is used only when the LLM call itself fails.

### LLM Card Generation

The `LLMProvider` ABC gains an optional `memory_context: dict | None = None` parameter on `generate_triage_card()`. The Anthropic implementation uses it in a structured prompt:

```
You are generating a triage card for a personal intelligence feed.

Item summary: {item.summary}
Source type: {source_type}
Enrichment context: {enrichment_context}

Memory context:
- Entity knowledge: {entity_facts}
- Relationships: {relationship_facts}
- User preferences (indexed):
  [0] {preference_facts[0]}
  [1] {preference_facts[1]}
  ...

Generate a JSON response with:

1. "card_body": A concise card body (2-4 sentences) that:
   - Summarizes what this item is about
   - Explains WHY it might matter to the user, citing entity knowledge and preferences
   - Highlights relevant relationships (e.g., "from alice, who you usually prioritize")

2. "options": A list of 3-5 triage options, each with:
   - "label": Short action phrase
   - "action": One of "add_todo", "skip", "mute_pattern", "defer"
   - "details": Optional context (e.g., priority level for add_todo, snooze hours for defer)
   - "suggested_fact_index": Integer index into the preference_facts list that justifies suggesting this option, or null if no fact supports a suggestion
```

The LLM returns structured JSON via tool use with `action` constrained to an enum of `["add_todo", "skip", "mute_pattern", "defer"]`. If the LLM returns invalid JSON or fails schema validation, retry up to 2 times. If all retries fail, fall back to template options.

### Suggestion Validation

Post-processing validates LLM suggestions against actual preference facts:

1. If `suggested_fact_index` is `null` → `suggested = False`
2. If `suggested_fact_index` is out of bounds (>= len(preference_facts)) → `suggested = False`
3. If valid index → `suggested = True`, `suggestion_reason` is auto-populated from `preference_facts[index]`

This ensures suggestions are always grounded in a real preference fact. The LLM cannot hallucinate patterns.

### Options as TriageOption Objects

LLM-generated option dicts are converted to `TriageOption` objects and stored in `card.options` (the model field). The `card_content` stores the full LLM response including the card body, but the canonical options list is always `card.options: list[TriageOption]`.

`TriageOption` gains new fields:

```python
class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)
    suggested: bool = False
    suggestion_reason: str | None = None
```

An **"Other"** option is always appended as the last option after LLM generation:
```python
TriageOption(label="Other — tell me what you'd like to do", action="other")
```

This means:
- Response handling code always reads `card.options[i].action` — no dual-path handling
- `format_card_for_chat()` reads `card.card_content["card_body"]` for the body and `card.options` for the list
- One source of truth for options

### Defer Action (Snooze)

A new triage action `defer` puts the card back in the queue with a delay. Implementation:

- Add `deferred_until: datetime | None` column to the `triage_cards` table (Alembic migration)
- When the user selects `defer`, set `deferred_until` to now + snooze duration (from `option.details.get("hours", 4)`)
- The triage queue skips cards where `deferred_until > now()`
- When the snooze expires, the scheduler detects cards with `deferred_until <= now()`, re-scores them via `llm.score_relevance()`, and updates `relevance_score`. If the new score falls below `drop_threshold`, the card is auto-skipped (item archived). Otherwise the card status is set to `queued` with the new score, and it re-enters the normal queue ordering.
- Item remains in `pending_triage` status throughout (until auto-skipped or re-triaged)
- Deferred cards pause their expiry clock (expiry is not checked while `deferred_until > now()`)

### Free-Text Triage Responses

Users can respond to triage cards in two ways beyond numbered options:

1. **Pick "Other"** (the last numbered option) → system replies "What would you like to do?" → card enters `awaiting_followup` status → next message is interpreted by LLM
2. **Type free text directly** (instead of a number) → interpreted by LLM immediately, no extra round-trip

Both paths route to the same LLM interpreter.

**Card status lifecycle (updated):**

```
queued → sent → responded / expired
                 ↘ awaiting_followup → responded / expired
                 ↘ awaiting_confirmation → responded / expired
```

**Timeout on pending states:** If no follow-up or confirmation arrives within 1 hour (configurable), the card reverts to `queued` status — `sent_at` and `bot_message_id` are cleared so the card gets re-sent with fresh options when it re-enters the queue. A log entry records the timeout event (useful for learning — "user didn't follow up on this type of card"). The card's `relevance_score` stays the same, so it re-enters at its original priority position.

**Card rendering includes a free-text hint:**

```
1. Add todo P1 (suggested: you usually prioritize alice's PRs)
2. Add todo P2
3. Skip
4. Defer (snooze 4h)
5. Other — tell me what you'd like to do
Or just reply with what you'd like to do.
```

**Consolidated response handling:** All triage response logic (numbered options, free text, defer, other, confirmation) is consolidated into a shared `execute_triage_response(card, message_text, stores, llm, memory, messenger)` function in `pipeline/triage.py`. Both the API endpoint (`api/triage.py`) and the scheduler (`pipeline/scheduler.py`) call this shared function. This eliminates the current duplication of response handling logic between the two paths.

**Response handler logic (inside `execute_triage_response`):**

```python
if card.status == "awaiting_followup":
    interpreted = await llm.interpret_triage_response(card, message_text)
    await execute_interpreted_response(interpreted, card, stores)

elif message_text.strip().isdigit():
    choice = int(message_text.strip())
    option = card.options[choice - 1]
    if option.action == "other":
        card.status = "awaiting_followup"
        await stores.triage.save_card(card)
        await messenger.send_notification("What would you like to do?")
        return
    await execute_option(option, card, stores)

else:
    interpreted = await llm.interpret_triage_response(card, message_text)
    await execute_interpreted_response(interpreted, card, stores)
```

### Interpret Triage Response

New `LLMProvider` method: `interpret_triage_response(card: TriageCard, raw_text: str) -> InterpretedResponse`

The interpreter receives the full context used during card generation: card body, options, enrichment context, entity knowledge, relationships, and preference facts — all read from `card.card_content["memory_context"]` (stored at generation time). This ensures the interpreter has the same context the user saw, enabling nuanced interpretations like "handle this the same way I handled alice's last PR."

```python
class SystemAction(BaseModel):
    action: str          # constrained to "add_todo", "skip", "mute_pattern", "defer"
    details: dict = {}

class UserTodo(BaseModel):
    summary: str
    action_category: str  # "delegation", "communication", "scheduling", "review", "creation", "update"

class InterpretedResponse(BaseModel):
    system_actions: list[SystemAction]
    user_todos: list[UserTodo]
    explanation: str     # what the LLM understood

# triage_cards.response column stores:
# - For numbered options: the option dict (as before)
# - For free-text: the raw text string
# The structured InterpretedResponse is stored in InteractionEntry.interpreted
```

Example: "add as P3 and assign to bob" →
```json
{
  "system_actions": [{"action": "add_todo", "details": {"priority": "P3"}}],
  "user_todos": [{"summary": "Assign task to bob", "action_category": "delegation"}],
  "explanation": "Adding as P3 todo. Created an action item to assign to bob."
}
```

**Confirmation flow:**
- Additive actions (`add_todo`, `defer`, user todos) → execute immediately, show explanation
- Destructive actions (`skip`, `mute_pattern`) → show confirmation: "I understood: Skip this item and mute similar items. Reply 'yes' to confirm." Card enters `awaiting_confirmation` status.

**Executing user todos:** Each `UserTodo` creates a new `Item`:
```python
Item(
    summary=todo.summary,
    category="action_item",
    status="active",
    priority="P2",
    parent_item_id=card.item_id,
    action_source="triage_response",
    action_category=todo.action_category,
)
```

### Interaction Logging for Training

All interpreted responses are logged for future model training (v2):

```python
InteractionEntry(
    type="interpreted_response",
    raw_text="add as P3 and assign to bob",
    interpreted={
        "system_actions": [...],
        "user_todos": [...],
    },
    confirmed=True,
    card_id="...",
    item_id="...",
)
```

This provides a clean training dataset: `(raw_text, card_context) → (actions, todos)`.

### Fallback Behavior

Card generation always attempts the LLM call. If the LLM call fails (timeout, API error, all retries exhausted):
- Fall back to the existing template behavior (static card body + hardcoded options + "Other" option)
- Log the error
- The card is still created and queued — just without memory context or LLM-generated body

### Cost

One additional LLM call per triaged item for card generation. One LLM call per free-text response for interpretation. Auto-included and auto-dropped items don't get cards. For a typical day with 10-20 triaged items, this adds 10-20 card generation calls plus occasional interpretation calls.

### Changes to format_card_for_chat()

`format_card_for_chat()` reads the card body from `card_content["card_body"]` and options from `card.options`:

```python
def format_card_for_chat(card: TriageCard) -> str:
    body = card.card_content.get("card_body", card.card_content.get("summary", ""))
    lines = [f"*{body}*", ""]
    for i, opt in enumerate(card.options, 1):
        suggested = f" _(suggested: {opt.suggestion_reason})_" if opt.suggested else ""
        lines.append(f"{i}. {opt.label}{suggested}")
    lines.append("")
    lines.append("_Or just reply with what you'd like to do._")
    return "\n".join(lines)
```

Always reads from `card.options` (TriageOption objects) — no dual-path handling.

## Track C: Action Items

### Data Model

User-generated action items from triage responses are `Item` objects with additional fields:

```python
class Item(BaseModel):
    # ... existing fields ...
    parent_item_id: str | None = None       # links to the triggering item
    action_source: str | None = None        # "triage_response", "pipeline", "manual"
    action_category: str | None = None      # one of ActionCategory enum values
    snoozed_until: datetime | None = None   # action item snooze — GET /api/actions excludes snoozed items
    completed_at: datetime | None = None    # when the action was marked done (alongside status="done")
```

**Action categories** — fixed enum (8 values), constrained via LLM tool use:

```python
class ActionCategory(str, Enum):
    DELEGATION = "delegation"       # "Assign to bob", "Ask alice to review"
    COMMUNICATION = "communication" # "Forward to alice", "Reply to thread"
    SCHEDULING = "scheduling"       # "Schedule follow-up", "Block 30min for this"
    REVIEW = "review"               # "Review by Friday", "Read the RFC"
    CREATION = "creation"           # "Create task for this", "File a bug"
    UPDATE = "update"               # "Update the doc", "Fix the config"
    DECISION = "decision"           # "Decline the meeting", "Approve the request"
    INVESTIGATION = "investigation" # "Investigate why this failed", "Look into the regression"
```

If the LLM produces an unsupported category (shouldn't happen with tool use constraint, but as a safety net): the user action fails with a message "I couldn't categorize that action. It's been logged for review." The unsupported category is logged with a structured marker (`unsupported_action_category`) for the developer to review and potentially extend the enum.

**Action lifecycle logging:** Action item state changes (created, done, snoozed, priority changed, archived) are logged to the interaction log, same as triage responses. The memory service can extract patterns like "user rarely completes review action items" as preference facts via the normal fact ingestion process. No extra LLM calls needed.

### API Endpoint

`GET /api/actions` — returns active action items grouped by category:

```json
{
  "categories": {
    "delegation": [
      {
        "id": "...",
        "summary": "Assign task to bob",
        "priority": "P2",
        "parent_item": {"id": "...", "summary": "PR #200 rate limiting"},
        "action_source": "triage_response",
        "created_at": "2026-06-02T10:00:00Z"
      }
    ],
    "review": [...],
    "communication": [...]
  },
  "total": 12
}
```

Supports query params: `?status=active`, `?priority=P1`, `?category=delegation`. Excludes items where `snoozed_until > now()` unless `?include_snoozed=true`.

`POST /api/actions/{id}/done` — marks an action item as done. Sets `status = "done"` and `completed_at = now()`.

`POST /api/actions/{id}/priority` — changes priority. Body: `{"priority": "P1"}`.

`POST /api/actions/{id}/snooze` — snoozes an action item. Body: `{"hours": 4}`. Sets `snoozed_until = now() + hours`. When the snooze expires, the item reappears in the active actions list automatically (query-time filter, no background task).

### Plugin Command

`/workbench:actions` — renders the categorized list in the CLI. Calls the API endpoint.

### Morning Briefing

Add a "Pending actions" section to the daily morning briefing at position 5 (after new items by source, before queue health). Updated briefing order: (1) P0 Today, (2) P1 This Week, (3) new items since yesterday, (4) pending triage, (5) **pending actions**, (6) queue health, (7) auto-decisions overnight.

```
Pending actions (5)
  Delegation (2):
    - Assign task to bob — from PR #200 rate limiting
    - Ask alice to review — from infra-core doc update
  Review (2):
    - Review by Friday — from compliance audit
    - Read the RFC — from storage migration proposal
  Communication (1):
    - Reply to thread — from incident #456 discussion
```

### React UI

A simple single-page app served by the FastAPI server at `/ui/actions`.

**Stack:** Vite + React + Tailwind CSS, built as static assets, served by FastAPI's `StaticFiles`. Multi-stage Docker build: Node stage builds React, Python stage copies built assets. During dev, two processes: `make dev-ui` starts Vite dev server with API proxy to FastAPI, `make up` starts FastAPI via Docker.

**Location:** `ui/` directory at project root.

**Features:**
- Categorized list with collapsible sections
- Each item shows: summary, priority badge, parent item link, age
- Actions per item: "Mark done", "Change priority", "Snooze"
- Filter bar: by category, priority, action source
- "Recently completed" section showing items with `completed_at` in the last 24 hours
- Responsive — works on mobile for quick checks

**Styling:** Tailwind CSS via `tailwindcss` dev dependency. Vite integrates Tailwind out of the box.

**No state management library** — React hooks + fetch are sufficient for a single-page categorized list.

**Authentication:** No login page. This is a single-user tool on a devgpu. FastAPI injects the API bearer token into the HTML via a `<meta>` tag at page serve time. The React app reads it and passes it as an Authorization header on all fetch calls. If the tool is ever exposed externally, proper auth can be added then.

### v2 Hook: Action Module

In v2, user todos will go to an action queue instead of directly creating Items. An Action Module will:
- Pick up items from the action queue
- Execute automatable actions (assign tasks, send messages, create calendar events) on behalf of the user
- Surface non-automatable actions as user todos (same as v1)

The `action_source` field on Items and the `InterpretedResponse` logging provide the data model and training data for this transition. The v1 architecture doesn't need to change — the Action Module is an additional consumer of the same data.

## File Changes

### Core `workbench/` — New Files (Observability, Operations, Privacy)

| File | Description |
|------|-------------|
| `middleware.py` | `CorrelationIdMiddleware` — UUID4 per request, bound to structlog contextvars, `X-Request-ID` header |
| `metrics.py` | Prometheus metric definitions (all counters, histograms, gauges) and `/metrics` endpoint |
| `instrumentation.py` | `InstrumentedSourceAdapter`, `InstrumentedLLMProvider`, `InstrumentedContextEnricher` decorator wrappers |
| `privacy.py` | `SanitizingProcessor` — structlog processor for PII redaction; `PrivacyConfig` model |
| `alerting.py` | `AlertManager` — condition evaluation, messenger alerts, cooldown dedup; `AlertConfig` model |
| `api/debug.py` | Diagnostic endpoints: `/api/debug/adapters`, `/api/debug/pipeline`, `/api/debug/connections`, `/api/debug/identity`, `/api/debug/config` |

### Core `workbench/` — New Files (Tracks A/B/C)

| File | Description |
|------|-------------|
| `providers/connection/__init__.py` | Connection package |
| `providers/connection/base.py` | `Connection` ABC |
| `providers/connection/google.py` | `GoogleConnection` — OAuth2 token management, Gmail/Calendar/Chat service accessors, `asyncio.to_thread()` wrapping |
| `providers/source/gmail.py` | `GmailAdapter` — polls Gmail API, multipart MIME extraction, attachment metadata |
| `providers/source/gcalendar.py` | `GCalendarAdapter` — polls Calendar API, meaningful-field hash dedup |
| `providers/source/gchat.py` | `GChatAdapter` — thread subscription model, configurable track mode, bot message filtering |
| `providers/enrichment/gmail.py` | `GmailEnricher` — full thread, sender info, attachment content |
| `providers/enrichment/gcalendar.py` | `GCalendarEnricher` — attendees, linked docs |
| `providers/enrichment/gchat.py` | `GChatEnricher` — thread context, space metadata |
| `providers/enrichment/composite.py` | `CompositeEnricher` — routes by source_type with per-enricher budgets |
| `api/actions.py` | Action items API endpoints |
| `ui/` | React app (Vite + React, static assets served by FastAPI) |

### Core `workbench/` — Modified Files (Observability, Operations, Privacy)

| File | Change |
|------|--------|
| `logging.py` | Rewrite: replace `GlogFormatter` with structlog setup (JSON/console configurable), integrate `SanitizingProcessor`, preserve `AgeRotatingFileHandler` |
| `config.py` | Add `DebugConfig`, `PrivacyConfig`, `MetricsConfig`, `TracingConfig`, `AlertConfig`, `RetentionConfig` models to `AppConfig` |
| `main.py` | Add `CorrelationIdMiddleware`, initialize `AlertManager`, register `/metrics` and `/api/debug/` routes, OTel auto-instrumentation (opt-in) |
| `registry.py` | Wrap providers with instrumented wrappers at construction time |
| `api/health.py` | Return 503 on critical component failure; add component-level checks; add `/health/live` and `/health/ready` |
| `pipeline/scheduler.py` | Call `alert_manager.check_and_alert()` on each tick; call `run_retention_cleanup()` daily after morning briefing |

### Core `workbench/` — Modified Files (Tracks A/B/C)

| File | Change |
|------|--------|
| `models.py` | Add `EntityType` enum, `ActionCategory` enum (8 values incl. decision, investigation); add `suggested`, `suggestion_reason` to `TriageOption`; add `deferred_until` to `TriageCard`; add `parent_item_id`, `action_source`, `action_category`, `snoozed_until`, `completed_at` to `Item`; add `awaiting_followup` and `awaiting_confirmation` to card status; add `InterpretedResponse`, `SystemAction`, `UserTodo` models; change `TriageResponse.choice` from `int` to `int \| None = None` (free-text responses have `choice=None`, `raw_text` populated); add `type`, `interpreted`, `confirmed` fields to `InteractionEntry` |
| `config.py` | Add `connections:` section, new `EnrichmentConfig` model (with backward-compat normalizer), bump config version to `0.3.0` |
| `main.py` | Initialize connections at startup, pass to provider registry with two-arg constructor, use `create_composite_enricher`, serve static UI assets, close on shutdown |
| `registry.py` | Support two-arg constructor for connection injection; add `create_composite_enricher()` function that pops `source_types`/`connection`/`budget` and builds CompositeEnricher |
| `pipeline/triage.py` | `generate_card()` accepts `memory`, extracts entity_refs, gathers memory context (no caps), stores on card, passes to LLM; always append "Other" option; always LLM, template on failure only; simplify `format_card_for_chat()` with free-text hint; add shared `execute_triage_response()` function (consolidates response handling from api/triage.py and scheduler) |
| `pipeline/engine.py` | Pass `self.memory` to `generate_card()` |
| `providers/llm/base.py` | Add `memory_context: dict \| None = None` to `generate_triage_card()`; add `interpret_triage_response()` method; add `describe_attachment(content: bytes, mime_type: str, context: str) -> str` method |
| `providers/llm/anthropic.py` | LLM card generation prompt with all entity_refs/relationships/preference facts (no caps) and tool use enum constraint; suggestion validation; `interpret_triage_response()` with full context from card; `describe_attachment()` routing: `image/*` via Claude vision API, `application/pdf` via pdfplumber text extraction; template fallback on LLM failure only |
| `providers/enrichment/base.py` | Document that enrichers receive connections via two-arg constructor; document `entity_refs` output requirement |
| `config.example.yml` | Add `connections:` section, Gmail/Calendar/GChat source examples, new enrichment provider list format |
| `pipeline/scheduler.py` | Error isolation per adapter (try/except around each `source.poll()`); check `connection.is_healthy()` before polling; re-score deferred cards on snooze expiry (auto-skip if below drop_threshold); timeout handling (revert awaiting cards to queued); add "Pending actions" section to morning briefing (position 5) |
| `api/triage.py` | Delegates to shared `execute_triage_response()` from `pipeline/triage.py`; handle `choice=None` as free-text path; all new actions (defer, other, free-text, confirmation) via the shared function |
| `storage/postgres/triage.py` | Update `get_pending()` to include `awaiting_followup`/`awaiting_confirmation` in status IN clause; update `get_next_unsent()` to add `AND (deferred_until IS NULL OR deferred_until <= NOW())`; update `expire_old_cards()` to exclude `awaiting_followup`/`awaiting_confirmation` (they have their own 1h timeout) |
| `storage/postgres/interactions.py` | Update INSERT and `_row_to_entry()` deserializer for new InteractionEntry fields (`type`, `interpreted`, `confirmed`) |
| `migrations/` | Alembic migration: add `deferred_until` to `triage_cards`; add `parent_item_id`, `action_source`, `action_category`, `snoozed_until`, `completed_at` to `items`; create `adapter_state` table |
| `scripts/regenerate_cards.py` | One-time migration script: re-generates all `queued` cards with new LLM flow (including memory context). Runs after Alembic migration, before server starts. |
| `storage/adapter_state.py` | `AdapterStateStore` interface + `PgAdapterStateStore` implementation |

### Memory service (`src/memory/`) — Modified Files

| File | Change |
|------|--------|
| `queue.py` | Add `entity_identities` table creation in `initialize()` |
| `graphiti_layer.py` | Identity resolution in `record_entity()`: check identity table, score identifying attributes, auto-merge or create new canonical; late discovery merge logic; update `query_entity()` to resolve through identity table |
| `main.py` | Add `POST /admin/merge-entities` and `POST /admin/split-entity` endpoints; UUID generation for canonical IDs |
| `models.py` | Add signal tier constants for identifying attributes |

### `workbench-meta/` — New Files

| File | Description |
|------|-------------|
| `privacy.py` | `META_SANITIZER_PATTERNS` — regex patterns for PHIDs (`D123456`), task IDs (`T123456`), unixnames; loaded at startup into `SanitizingProcessor` |
| `providers/connection/__init__.py` | Connection package |
| `providers/connection/intern.py` | `InternConnection` — Intern API / GraphQL auth (mechanism TBD). Includes `is_healthy()` for health check integration and structlog logging with `auth_method`, `token_expiry` context |
| `providers/source/meta_tasks.py` | `MetaTasksAdapter` — polls tasks via meta CLI or GraphQL. Structured logging with `query_owner`, `task_count`, `query_filters` |
| `providers/source/workplace.py` | `WorkplaceAdapter` — polls Workplace group posts. Structured logging with `group_ids`, `post_count` |
| `providers/source/docs.py` | `MetaDocsAdapter` — polls wiki/doc updates. Structured logging with `wiki_spaces`, `doc_count`, `watch_tags` |
| `providers/enrichment/meta_tasks.py` | `MetaTasksEnricher` — subtasks, blockers, related diffs. Structured logging with `task_id`, `subtask_count`, `blocker_count` |
| `providers/enrichment/workplace.py` | `WorkplaceEnricher` — comments, reactions, author role. Structured logging with `post_id`, `comment_count`, `author_role` |
| `providers/enrichment/docs.py` | `MetaDocsEnricher` — content summary, edit history. Structured logging with `page_id`, `revision_id`, `edit_count` |

### `workbench-meta/` — Modified Files

| File | Change |
|------|--------|
| `config.meta.yml` | Add `connections:`, `privacy:` (max_content_in_logs: 500), `retention:` (365 days all), `alerting:` (stricter thresholds), `logging:` (format: json). Add Meta-internal source and enricher entries, full enricher provider list (core + meta) |
| `docker-compose.override.yml` or entrypoint | Load `META_SANITIZER_PATTERNS` from `workbench_meta.privacy` into `SanitizingProcessor` at startup |
| `providers/llm/meta_anthropic.py` | Inherits LLM card generation and interpret_triage_response from parent — no changes needed |

### Tests (Observability, Operations, Privacy)

| File | Description |
|------|-------------|
| `tests/test_structured_logging.py` | structlog JSON/console output, correlation ID binding, sanitizer integration |
| `tests/test_metrics.py` | Prometheus counters/histograms increment correctly, `/metrics` endpoint returns text |
| `tests/test_instrumentation.py` | Instrumented wrappers track poll/enrich/LLM durations and counts |
| `tests/test_sanitizer.py` | Email/phone redaction, content truncation, extra_patterns extension, PII debug opt-in |
| `tests/test_health_improved.py` | 503 on PG failure, component breakdown, liveness/readiness split |
| `tests/test_alerting.py` | Condition evaluation, cooldown dedup, messenger integration |
| `tests/test_retention.py` | Cleanup deletes expired rows, respects retention periods, skips interaction log |
| `tests/test_debug_endpoints.py` | Diagnostic endpoints return adapter/pipeline/connection/identity/config data |

### Tests (Tracks A/B/C)

| File | Description |
|------|-------------|
| `tests/test_google_connection.py` | OAuth2 token loading, refresh, service accessors, `is_healthy()` |
| `tests/test_gmail_adapter.py` | Poll with label filters, MIME extraction, attachment metadata, RawItem construction, dedup |
| `tests/test_gcalendar_adapter.py` | Poll with lookahead, meaningful-field hash dedup, recurring event signals |
| `tests/test_gchat_adapter.py` | Thread subscription lifecycle (enter/exit/re-enter), track modes, bot message filtering |
| `tests/test_composite_enricher.py` | Routing by source_type, per-enricher budgets, default fallback |
| `tests/test_entity_refs.py` | Each enricher returns correct entity_refs with EntityType enum values and source-qualified IDs |
| `tests/test_identity_resolution.py` | Signal-tiered matching, auto-merge on strong match, no merge on weak-only, late discovery merge, manual merge/split |
| `tests/test_triage_card_enrichment.py` | LLM card generation with/without memory context, suggestion validation (valid index, invalid index, null), template fallback on LLM failure, defer action |
| `tests/test_free_text_response.py` | Free-text interpretation, "Other" flow, awaiting_followup state, confirmation for destructive actions, user todo creation |
| `tests/test_actions_api.py` | GET /api/actions categorization, done/priority/snooze endpoints |
| `tests/test_registry_connection.py` | Two-arg constructor injection, single-arg backward compatibility, create_composite_enricher |

## Resolved Questions (from Grilling Session 2026-06-02)

1. **Workplace API:** → Workplace's own Graph API, with auth shared via InternConnection.
2. **InternConnection auth:** → Must be resolved before implementing Meta adapters. Investigate devgpu auth mechanisms first. Google adapters and Tracks B+C can proceed in parallel.
3. **GChat thread state persistence:** → New `adapter_state` PG table with `AdapterStateStore` interface. Injected via `state_store` constructor arg using `inspect.signature` pattern.

## Resolved Questions (from Grilling Session 2026-06-03)

4. **Track independence:** → Tracks are independent for dev parallelism (separate engineers can work each track concurrently), but integration testing requires A before B. Track B can be built with mock entity_refs and tested in isolation, but end-to-end testing requires at least one Track A enricher.
5. **Identity resolution enricher coverage:** → Built a per-enricher identifying attribute matrix. Gmail/Calendar are the strongest identity anchors (always have emails). GitHubEnricher makes one extra `gh api users/{login}` call to fetch profile email and numeric user ID as `platform_uid`. GChatEnricher extracts `platform_uid` from the sender's user resource name (`users/{userId}`). Meta sources reliably have platform UIDs.
6. **execute_triage_response consolidation:** → Drop `messenger` parameter entirely. Function is pure: updates state, executes actions, returns `TriageResponseResult(explanation, prompt, followup_status, actions_executed)`. API endpoint returns the result as JSON. Scheduler checks result and sends prompt via messenger if needed. No risk of duplicate messages.
7. **Deferred card expiry:** → Add `AND (deferred_until IS NULL OR deferred_until <= NOW())` to `expire_old_cards()`. Deferred cards are excluded from expiry while snoozed.
8. **Deferred card re-scoring:** → Removed. Don't re-score deferred cards on snooze expiry. The user explicitly chose to defer — preserve the original `relevance_score`. Just set the card back to `queued`. Use a separate, longer timeout (30 days) for stale-deferred cleanup rather than re-scoring.
9. **GoogleConnection thread safety:** → `GoogleConnection` uses a `build_service(api, version)` factory method that creates a fresh, thread-local API service with its own `Http` instance per call. Google's `httplib2.Http` is not thread-safe — pre-built service properties would break under concurrent enrichment (worker dequeues 2+ items in parallel, each calling `asyncio.to_thread()` on the same connection).
10. **Enricher return format:** → `entity_refs` is a top-level key in the enricher return dict, alongside existing `calls_made`, `time_ms`, `context`. Metrics are preserved. Card generation extracts via `enrichment_context.get("entity_refs", [])`.
11. **regenerate_cards.py migration script:** → Dropped. Old template-based cards degrade gracefully: `format_card_for_chat()` falls back from `card_body` to `summary`, old options lack `suggested` markers, no `memory_context` → interpreter works with empty context. Cards expire within 7 days. No deployment complexity or partial failure risk.
12. **Attachment processing split:** → `describe_image(content, mime_type, context) -> str` on `LLMProvider` ABC (Claude vision API only). `extract_pdf_text(content, max_pages) -> str` in `workbench/util/attachments.py` (pdfplumber, no LLM). Routing logic lives in the enricher (GmailEnricher checks mime_type and calls the right tool). LLM provider stays clean — only LLM calls.
13. **Awaiting timeout behavior:** → On timeout, revert card to `sent` status (not `queued`). Keep existing `bot_message_id`. Scheduler resumes polling that message. No duplicate messages sent, no late responses lost. For `awaiting_confirmation`, timeout discards the pending action and reverts to `sent`.
14. **LLM output validation:** → Post-processing validates LLM-generated options before converting to TriageOption. Defer hours clamped to [1, 72]. Priority strings normalized (`"urgent"`→P0, `"high"`→P1, etc.). LLM prompt includes instruction: "Do NOT include an 'Other' or open-ended option — one is appended automatically."
15. **Pending confirmation storage:** → Pending `InterpretedResponse` stored in `card_content["pending_interpretation"]` (JSONB, no new column). When "yes" arrives, the function reads and executes the pending interpretation. Stale interpretations (after timeout revert) are harmless — never read again.
16. **Skip all confirmation:** → "Skip all" requires confirmation ("This will skip N pending cards. Reply 'yes' to confirm."). After confirmation, routes through `execute_triage_response()` for each card so interaction logging and memory recording happen. Cards in `awaiting_followup`/`awaiting_confirmation` are excluded from bulk skip.
17. **GChat thread batching:** → Instead of producing a RawItem on every new message, the GChat adapter waits until a thread is idle for `idle_minutes` (default 15) or `max_delay_minutes` (default 120) since last ingestion. State (`last_activity`, `last_ingested` per thread) persisted in `adapter_state`. Prevents duplicate pipeline runs for active threads while ensuring long-running conversations get periodic ingestion.

## Resolved Questions (from Grilling Session 2026-06-03 — Plan Review)

18. **Plan header inconsistencies:** → Fixed 4 stale plan header entries: (a) deferred card re-scoring removed per #8, (b) awaiting timeout reverts to `sent` per #13, (c) `describe_attachment` split per #12, (d) regenerate_cards.py dropped per #11.
19. **expire_old_cards() redundant WHERE clause:** → `status = 'queued' AND status NOT IN ('awaiting_followup', 'awaiting_confirmation')` is redundant — removed second condition. Cards in awaiting states have their own 1-hour timeout.
20. **TriageResponseResult model:** → Missing from Task 1 models. Add `TriageResponseResult(explanation: str, prompt: str | None, followup_status: str | None, actions_executed: list[str])` to `models.py`.
21. **AdapterStateStore.delete_state():** → Add `delete_state(name: str)` method for adapter cleanup. Cheap to add now, avoids migration later.
22. **BearerTokenMiddleware auth exemptions:** → `/metrics`, `/health/live`, `/health/ready` must be exempted alongside `/health`. Update middleware in Tasks 6b and 6d.
23. **React UI token injection:** → `StaticFiles` can't inject dynamic content. Use a dedicated route that serves `index.html` with token replaced via string substitution (`__API_TOKEN__` placeholder), plus `StaticFiles` for other assets at `/ui/assets`.
24. **CompositeEnricher failure metrics:** → Add `workbench_enrichment_errors_total{enricher, source_type}` counter. Increment on enricher exception in `CompositeEnricher.enrich()`.
25. **GoogleConnection factory methods:** → Use `gmail_service()`, `calendar_service()`, `chat_service()` methods (not properties) that return fresh thread-local API services via `build_service(api, version)`. Naming makes the per-call cost explicit.
26. **ActionCategory fallback:** → If LLM produces unsupported category (shouldn't happen with tool use constraint), default to `UPDATE` and log with `unsupported_action_category` marker. Don't fail the user action.
27. **SanitizingProcessor recursion:** → Must recursively walk all string values in nested dicts/lists. Use `_sanitize_value()` recursive helper.
28. **Alert message formatting:** → Prefix alert messages with `⚠️ [ALERT]` to visually distinguish from triage cards.

## Observability, Operations, and Privacy

### Structured Logging

Replace the glog formatter with structlog. Two output modes: JSON in production (`logging.format: json`), human-readable console renderer in dev (`logging.format: console`). See ADR 0010.

**Correlation IDs:** `CorrelationIdMiddleware` in `workbench/middleware.py` generates a UUID4 per HTTP request, binds it to structlog's contextvars, and returns it in `X-Request-ID` response header. Pipeline jobs bind their existing `job_id` to the logging context during processing.

**Migration:** Existing `logging.getLogger(__name__)` calls continue to work via structlog's stdlib integration. New code uses `structlog.get_logger()`. The `AgeRotatingFileHandler` is preserved for file output.

### Metrics

Prometheus metrics via `prometheus-client`. Exposed at `GET /metrics` (unauthenticated, like `/health`).

**Instrumented wrappers** (decorator pattern, SOLID Open/Closed) wrap providers automatically at registry construction time:

- `InstrumentedSourceAdapter` — counters: `workbench_items_ingested_total{source_type, adapter}`, `workbench_adapter_polls_total{adapter, status}`; histograms: `workbench_adapter_poll_seconds{adapter}`
- `InstrumentedLLMProvider` — counters: `workbench_llm_calls_total{method}`, `workbench_llm_errors_total{method, error_type}`; histograms: `workbench_llm_call_seconds{method}`
- `InstrumentedContextEnricher` — histograms: `workbench_enrichment_seconds{enricher}`

**Additional metrics:**
- Counters: `workbench_items_triaged_total{action}`, `workbench_items_dropped_total{reason}`, `workbench_identity_merges_total{resolved_by}`, `workbench_cards_generated_total{method}`, `workbench_alerts_sent_total{alert_type}`
- Gauges: `workbench_ingestion_queue_depth`, `workbench_triage_queue_depth`, `workbench_dead_letter_count`, `workbench_connection_healthy{name}`, `workbench_tracked_threads{adapter}`
- Histograms: `workbench_pipeline_stage_seconds{stage}`

**Config:**
```yaml
metrics:
  enabled: true
  endpoint: /metrics
```

### OpenTelemetry Tracing (Opt-In)

Auto-instrumentation for FastAPI, httpx (memory service calls), and asyncpg. Trace context propagated to the memory service in HTTP headers. Disabled by default.

```yaml
tracing:
  enabled: false
  exporter: console       # "console" | "otlp"
  otlp_endpoint: null
  sample_rate: 1.0
```

### Health Check Improvements

Fix existing bug: return HTTP 503 when critical components are unhealthy (currently returns 200 with `"degraded"`).

Three endpoints:
- `GET /health` — 200 if all critical components healthy, 503 if any critical unhealthy. Returns component-level breakdown.
- `GET /health/live` — 200 always (liveness probe).
- `GET /health/ready` — 200 if ready to serve, 503 if not (readiness probe).

Critical components (503 on failure): PostgreSQL, LLM provider. Non-critical (reported but not 503): memory service, connections, messenger.

Response includes component health, queue stats, and connection details.

### Debug Configuration

Expand from a single `server.debug` boolean (uvicorn reload only) to a structured section controlling diagnostic output:

```yaml
debug:
  sql_queries: false
  llm_prompts: false
  llm_token_usage: true
  request_bodies: false
  enrichment_details: false
  adapter_raw_items: false
```

Fields that would log PII (`llm_prompts`, `request_bodies`, `adapter_raw_items`) require double opt-in: both the debug flag AND `privacy.allow_pii_in_debug_logs: true`.

### Alerting

Messenger-based alerting via `AlertManager`, checked on each scheduler tick.

| Condition | Default threshold | Cooldown |
|---|---|---|
| Connection unhealthy | Immediate (on state change) | 1 hour |
| Dead letters accumulated | >= 3 | 4 hours |
| Adapter consecutive failures | >= 3 | 1 hour |
| LLM provider unreachable | >= 2 consecutive failures | 30 min |
| Ingestion queue depth | >= 50 | 1 hour |
| Triage queue stale | Oldest card > 3 days | 24 hours |

```yaml
alerting:
  enabled: true
  cooldown_minutes: 60
  conditions:
    dead_letter_threshold: 3
    adapter_failure_threshold: 3
    queue_depth_threshold: 50
    stale_card_days: 3
```

### Diagnostic Endpoints

Admin-only endpoints behind bearer auth at `/api/debug/`:

| Endpoint | Returns |
|---|---|
| `GET /api/debug/adapters` | Adapters with last poll time, items found, consecutive errors, connection health |
| `GET /api/debug/pipeline` | Recent pipeline jobs (last 50) with per-stage timing |
| `GET /api/debug/connections` | Connection health details, last initialized |
| `GET /api/debug/identity` | Identity resolution stats: entity count, identity count, merge count |
| `GET /api/debug/config` | Current config with secrets redacted |

### Privacy: Log Sanitization

`SanitizingProcessor` in the structlog processing chain. See ADR 0011.

- Email addresses: always redacted (`[REDACTED:email]`)
- Phone numbers: always redacted (`[REDACTED:phone]`)
- Names: NOT redacted (too many false positives)
- Free-text content: truncated to `max_content_in_logs` (default 200 chars) in log output
- Extensible: workbench-meta adds patterns for PHIDs, employee IDs via `extra_patterns`

```yaml
privacy:
  sanitize_logs: true
  redact_emails: true
  redact_phones: true
  max_content_in_logs: 200
  allow_pii_in_debug_logs: false
```

### Privacy: LLM Prompt Logging

In normal mode, LLM calls log metadata only (item_id, source_type, token counts, duration, model). Content is never logged at INFO level or above.

In debug mode with `debug.llm_prompts: true` AND `privacy.allow_pii_in_debug_logs: true`: full prompt and response logged at DEBUG level.

### Data Retention

Configurable time-based cleanup, executed by daily scheduler task after morning briefing.

| Data type | Default (OSS) | workbench-meta override |
|---|---|---|
| Archived items | 90 days | 365 days |
| Done action items | 90 days | 365 days |
| Expired triage cards | 30 days | 365 days |
| Responded triage cards | 90 days | 365 days |
| Enrichment traces | 30 days | 365 days |
| Dead letters (after purge) | 30 days | 365 days |
| Interaction log | Never pruned | Never pruned |

```yaml
retention:
  archived_items_days: 90
  done_items_days: 90
  expired_cards_days: 30
  responded_cards_days: 90
  enrichment_traces_days: 30
  dead_letters_days: 30
```

workbench-meta config override:
```yaml
retention:
  archived_items_days: 365
  done_items_days: 365
  expired_cards_days: 365
  responded_cards_days: 365
  enrichment_traces_days: 365
  dead_letters_days: 365
```

### OSS / Internal Split

**workbench (OSS)** owns all observability, operations, and privacy infrastructure — interfaces, wrappers, processors, config models, and endpoints. Generic and applied automatically to all providers regardless of origin.

**workbench-meta (internal)** contributes code and config in three categories:

#### 1. Meta Sanitizer Patterns (`workbench_meta/privacy.py`)

A module that defines Meta-internal PII patterns and exposes them for the logging setup:

```python
# workbench_meta/privacy.py
import re

META_SANITIZER_PATTERNS = [
    (re.compile(r'\bD\d{6,}\b'), '[REDACTED:phid]'),         # Phabricator diff IDs
    (re.compile(r'\bT\d{6,}\b'), '[REDACTED:task_id]'),      # Task IDs
    (re.compile(r'\b[a-z]{2,20}\b(?=@fb\.com)'), '[REDACTED:unixname]'),  # unixnames before @fb.com
]
```

Loaded in the Meta entrypoint so the `SanitizingProcessor` includes these patterns from startup.

#### 2. Meta Adapter/Enricher Structured Logging

Meta adapters and enrichers (MetaTasks, Workplace, MetaDocs and their enrichers) use structlog with Meta-specific bound context. This is code within each provider, not a separate module:

```python
# Example: workbench_meta/providers/source/meta_tasks.py
import structlog
logger = structlog.get_logger(__name__)

class MetaTasksAdapter(SourceAdapter):
    async def poll(self, since):
        logger.info("meta_tasks_poll_start", query_owner=self._config.query_filters.get("owner"))
        # ... API calls ...
        logger.info("meta_tasks_poll_complete",
            tasks_found=len(items),
            query_filters=self._config.query_filters,
        )
```

Key context fields logged by Meta adapters/enrichers:

| Provider | Context fields |
|---|---|
| `MetaTasksAdapter` | `query_owner`, `task_count`, `query_filters` |
| `MetaTasksEnricher` | `task_id`, `subtask_count`, `blocker_count` |
| `WorkplaceAdapter` | `group_ids`, `post_count` |
| `WorkplaceEnricher` | `post_id`, `comment_count`, `author_role` |
| `MetaDocsAdapter` | `wiki_spaces`, `doc_count`, `watch_tags` |
| `MetaDocsEnricher` | `page_id`, `revision_id`, `edit_count` |
| `InternConnection` | `auth_method`, `token_expiry` |

These fields are automatically sanitized by the `SanitizingProcessor` (email/phone redaction, content truncation) and further cleaned by the Meta sanitizer patterns (PHID/task ID redaction).

#### 3. Meta Config Overrides (`config.meta.yml`)

Added to the existing config overlay:

```yaml
# config.meta.yml additions

privacy:
  sanitize_logs: true
  redact_emails: true
  redact_phones: true
  max_content_in_logs: 500          # more generous for internal debugging

retention:
  archived_items_days: 365
  done_items_days: 365
  expired_cards_days: 365
  responded_cards_days: 365
  enrichment_traces_days: 365
  dead_letters_days: 365

alerting:
  enabled: true
  cooldown_minutes: 30              # faster alerting for internal use
  conditions:
    dead_letter_threshold: 2
    adapter_failure_threshold: 2     # stricter — detect Intern API issues faster
    queue_depth_threshold: 30

logging:
  format: json                       # JSON for internal log aggregation
  level: INFO
```

#### What stays automatic (no workbench-meta code needed)

- **Prometheus metrics** — `InstrumentedSourceAdapter` wraps Meta adapters at registry construction time. MetaTasksAdapter gets `workbench_adapter_polls_total{adapter="MetaTasksAdapter"}` without any code in workbench-meta.
- **Health checks** — `InternConnection.is_healthy()` is called generically by the health endpoint iterating over `app.state.connections`.
- **Diagnostic endpoints** — Meta adapters appear in `/api/debug/adapters` because they're in `app.state.sources`.
- **AlertManager** — connection unhealthy alerts fire for `meta_intern` automatically.
- **Correlation IDs** — Meta adapters run in the same async context as the pipeline, so request_id/job_id are automatically in their logs.
- **Retention cleanup** — Meta data uses the same PG tables, cleaned by the same scheduler task with Meta-overridden retention periods.

## Verification

Phase 1d is complete when:

### Track A
1. `GoogleConnection` initializes, refreshes tokens, and uses `build_service()` factory for thread-safe API access
2. All Google API calls are wrapped in `asyncio.to_thread()` — no event loop blocking
3. All 3 Google adapters (`Gmail`, `GCalendar`, `GChat`) return `list[RawItem]` from `poll(since)` using the shared connection
4. All 3 Meta adapters (`MetaTasks`, `Workplace`, `MetaDocs`) return `list[RawItem]` from `poll(since)` using the shared connection
5. Each adapter produces correct `source_type`, `source_id`, `raw_text`, and `urgency_signals`
6. Gmail adapter correctly extracts multipart MIME bodies and captures attachment metadata (including inline images)
7. Calendar adapter deduplicates by meaningful-field hash (RSVP changes don't trigger re-ingestion); recurring events include `recurring_event_id` in urgency signals
8. GChat adapter implements thread subscription with configurable track mode, thread re-entry on participation, bot message filtering, and thread batching (idle 15min / max delay 2h)
9. Dedup works correctly for each adapter (unique `source_id` per item, modifications detected where applicable)
10. Scheduler polls all configured adapters on schedule with error isolation (one failure doesn't block others)
11. `CompositeEnricher` routes to the correct enricher by source type with per-enricher budget overrides
12. Each enricher returns useful context using the shared connection and includes `entity_refs` with `EntityType` enum values and source-qualified IDs
13. Each enricher extracts identifying attributes (email, name, platform_uid) for identity resolution
14. All new adapters and enrichers work end-to-end: poll → enqueue → extract → filter → enrich → triage card

### Track B — Identity Resolution
15. `entity_identities` table created and indexed
16. `record_entity` resolves source-qualified IDs to canonical IDs using signal-tiered scoring
17. Strong matches (email, phone, platform_uid) auto-merge on single match
18. Medium matches (name, username) require 2+ to auto-merge
19. Weak matches (first_name, timezone, title) are supporting only, never sufficient alone
20. Late discovery merge correctly repoints identities, merges facts, and merges graph nodes
21. `query_entity` resolves through identity table and returns merged facts
22. Admin merge/split endpoints work correctly

### Track B — Cards and Free-Text
23. Triage cards are always LLM-generated (template only on LLM failure, with up to 2 retries)
24. Card body uses enrichment context, entity knowledge (resolved through identity), relationships, and preference context
25. Card body explains *why* the item matters based on memory
26. LLM options use tool use with enum constraint for action types; invalid actions are retried, not silently accepted
27. LLM options are converted to `TriageOption` objects with `suggested` and `suggestion_reason` fields
28. Suggestion validation: `suggested_fact_index` checked against preference_facts bounds; invalid indices strip the suggestion
29. "Other" option is always appended as the last option
30. Free text (direct or via "Other") routes to `llm.interpret_triage_response()`
31. `InterpretedResponse` correctly separates system actions from user todos
32. Destructive actions (skip, mute) require confirmation; additive actions execute immediately
33. User todos create `Item` objects with `parent_item_id`, `action_source`, and `action_category`
34. Interpreted responses are logged for future model training
35. `defer` action sets `deferred_until`; deferred cards excluded from expiry; on snooze expiry, card reverts to `queued` with original `relevance_score` (no re-scoring)
36. `format_card_for_chat()` renders card body + options with suggestion markers + free-text hint
37. No regression in card rendering for existing GitHub/Phabricator sources

### Track C
38. `GET /api/actions` returns active action items grouped by `action_category`
39. Action API supports done, priority change, and snooze operations
40. `/workbench:actions` plugin command renders categorized list
41. Morning briefing includes "Pending actions" section grouped by category
42. React UI at `/ui/actions` renders categorized action list with mark done, change priority, and snooze
43. React UI is built with Vite, served as static assets by FastAPI

### Observability, Operations, and Privacy
67. structlog replaces glog formatter; JSON output in production, console in dev; `AgeRotatingFileHandler` preserved
68. Correlation ID middleware generates UUID4 per request, bound to structlog context, returned in `X-Request-ID`
69. Prometheus `/metrics` endpoint exposes all defined counters, histograms, and gauges
70. `InstrumentedSourceAdapter`, `InstrumentedLLMProvider`, `InstrumentedContextEnricher` wrappers applied by registry
71. Health check returns 503 when critical components unhealthy; component-level breakdown in response
72. `/health/live` always returns 200; `/health/ready` returns 503 when not ready
73. `DebugConfig` section controls SQL, LLM, request body logging independently
74. PII debug fields require double opt-in (debug flag + `privacy.allow_pii_in_debug_logs`)
75. `SanitizingProcessor` redacts emails and phones in log output; truncates free-text to `max_content_in_logs`
76. workbench-meta can add extra sanitizer patterns without modifying core code
77. `AlertManager` sends messenger alerts for configured conditions with cooldown dedup
78. Diagnostic endpoints (`/api/debug/adapters`, `/api/debug/pipeline`, `/api/debug/connections`, `/api/debug/identity`, `/api/debug/config`) return operational data
79. Data retention scheduler task runs daily; cleans up according to `RetentionConfig`
80. OTel auto-instrumentation works when `tracing.enabled: true`; disabled by default
81. workbench-meta retention defaults are 365 days for all categories

### All Tracks
44. `connections:` config section is parsed, validated, and connections are initialized at startup
45. Registry supports two-arg constructor for connection injection AND `state_store` injection via `inspect.signature`
46. `create_composite_enricher()` correctly pops `source_types`/`connection`/`budget` and builds CompositeEnricher
47. `EnrichmentConfig` model replaces old `dict | None` config (backward-compat normalizer for old format)
48. Config version is bumped to `0.3.0`
49. `Item` model has `parent_item_id`, `action_source`, `action_category`, `snoozed_until`, `completed_at` fields (Alembic migration)
50. All existing tests pass (no regressions)
51. `adapter_state` PG table created; `AdapterStateStore` interface + PG implementation
52. GChat adapter uses `state_store` for thread state persistence
53. Triage response handling consolidated into shared `execute_triage_response()` — no messenger param, returns `TriageResponseResult`
54. `describe_image()` on `LLMProvider` handles images (vision API); `extract_pdf_text()` in `workbench/util/attachments.py` handles PDFs (pdfplumber)
55. Entity admin endpoints (merge/split) proxied through workbench API
56. Connection initialization failure is a hard startup error
57. Old queued cards degrade gracefully — `format_card_for_chat()` falls back from `card_body` to `summary` (no migration script)
58. GChat adapter has defense-in-depth: bot message filtering + exclude_spaces validation + triage response filtering
59. All-day calendar events included with `is_all_day: true` in urgency signals
60. ActionCategory enum has 8 values including decision and investigation
61. GitHubEnricher fetches user profile for email/platform_uid via extra `gh api` call
62. GChatEnricher extracts `platform_uid` from sender user resource name
63. LLM-generated card options validated: defer hours clamped [1,72], priority strings normalized
64. Pending `InterpretedResponse` stored in `card_content["pending_interpretation"]` for confirmation flow
65. "Skip all" requires confirmation and routes through `execute_triage_response()` per card
66. `awaiting_followup`/`awaiting_confirmation` timeout reverts to `sent` (not `queued`), keeps `bot_message_id`
82. `entity_refs` uses list-of-dicts format `[{"type": "person", "id": "github:alice-gh"}]` (not tuples) — all enrichers, card generation, and memory queries use this format
83. Identity resolution canonical IDs are always UUID4 — never source-qualified strings
84. `TriageResponseResult` model exists in `models.py` and is returned by `execute_triage_response()`
85. `GET /api/items` excludes action items by default (`?exclude_actions=true`)
86. React UI index.html served via dedicated route with `__API_TOKEN__` substitution; other assets via `StaticFiles` at `/ui/assets`
87. `InteractionEntry.type` is set for all interactions: `option_selected`, `interpreted_response`, `confirmation`
88. `CompositeEnricher` wraps child enrichers with `InstrumentedContextEnricher` for per-enricher Prometheus metrics
89. `format_card_for_chat` skips raw enrichment context when `card_body` is present (avoids duplication with LLM-generated body)
90. GChat adapter's bot identity is auto-discovered via Chat API and cached on `GoogleConnection.bot_user_id`
91. Config minor version mismatch logs a warning (not a hard error)

## Resolved Questions (from Grilling Session 2026-06-03 — Plan Review Round 2)

29. **Identity resolution canonical IDs in plan:** → Plan's Task 15 tests incorrectly use first source_id as canonical (e.g., `assert canonical == "github:alice-gh"`). Fix to always generate UUID4 for canonical IDs per spec and grilling decision #3. Tests should assert `uuid.UUID(canonical)` succeeds, not equality to source_id.
30. **execute_triage_response consolidation not implemented:** → Plan's Task 18 puts response logic inline in `api/triage.py`, Task 19 puts free-text logic in scheduler — same duplication the spec says to eliminate. Fix: create shared `execute_triage_response()` in `pipeline/triage.py`. Both API route and scheduler call it. Returns `TriageResponseResult`. Matches grilling decision #6.
31. **TriageResponseResult missing from Task 1:** → Add `TriageResponseResult(explanation: str, prompt: str | None, followup_status: str | None, actions_executed: list[str])` to Task 1 model changes. Needed for `execute_triage_response()` return type.
32. **entity_refs as tuples serialize poorly to JSON:** → Change from list of tuples `[(EntityType.PERSON, "id")]` to list of dicts `[{"type": "person", "id": "github:alice-gh"}]`. Clean JSON/JSONB round-tripping, self-documenting, no tuple/list ambiguity. Update spec, enricher docs, card generation code.
33. **React UI token injection contradicts grilling #23:** → Plan's main.py uses `StaticFiles(html=True)` which can't inject tokens. Fix: dedicated route for `/ui` that reads index.html, replaces `__API_TOKEN__` placeholder, returns HTML. Mount `StaticFiles` at `/ui/assets` for JS/CSS bundles.
34. **AdapterStateStore injection missing from registry:** → Plan's Task 4 only adds `connection` injection. Add `state_store` injection alongside it. Registry checks for `state_store` in constructor signature and injects `PgAdapterStateStore` if present. Create `AdapterStateStore` interface + PG implementation in Task 2 (alongside migration).
35. **enrichment_errors_total counter missing from metrics:** → Add `enrichment_errors: Counter` (labels: `enricher`, `source_type`) to `WorkbenchMetrics` in Task 6b. Pass metrics to `CompositeEnricher`, increment on exception. Matches grilling decision #24.
36. **describe_image() and extract_pdf_text() not placed in any task:** → Add `describe_image()` as abstract method on `LLMProvider` base in Task 10 (Gmail Enricher — first consumer). Create `workbench/util/attachments.py` with `extract_pdf_text()` in same task.
37. **GET /api/items returns action items:** → Add `exclude_actions=true` default query param to `GET /api/items`. Action items filtered out by default. `GET /api/actions` is the canonical view. Pass `?exclude_actions=false` to see everything.
38. **BearerTokenMiddleware /metrics exemption:** → Consolidate auth exemptions in Task 6c Step 4: `/health`, `/health/live`, `/health/ready`, `/metrics`. Single auth.py change.
39. **GChat adapter bot identity discovery:** → `GoogleConnection` auto-discovers bot user ID at initialization via Chat API and caches as `bot_user_id` property. GChat adapter uses it to filter bot's own messages. Falls back to explicit `bot_user_id` config if API call fails.
40. **InternConnection auth investigation timing:** → Add investigation task early (before Group A) rather than deferring to Group M. It's on the critical path for 3 Meta adapters. Google adapters and Tracks B+C don't depend on it, but early investigation prevents late surprises.
41. **AdapterStateStore.delete_state() in plan:** → Create `storage/adapter_state.py` in Task 2 with full interface: `get_state(name)`, `save_state(name, state)`, `delete_state(name)`. PG implementation uses `adapter_state` table from same migration. Don't split interface from table creation.
42. **Config version minor version warning:** → When `config.version` minor is less than expected (e.g., 0.2.x with server expecting 0.3.x), log a warning. Don't hard-error — backward-compat normalizer handles it. Gives user visibility.
43. **InteractionEntry type for numbered options:** → Set `type` for all triage interactions. Numbered option: `type="option_selected"`. Free text: `type="interpreted_response"`. Confirmation: `type="confirmation"`. Makes interaction log self-documenting and filterable.
44. **CompositeEnricher per-enricher observability:** → `CompositeEnricher` wraps each individual enricher with `InstrumentedContextEnricher` at construction time. Per-enricher Prometheus metrics automatically. `InstrumentedContextEnricher` wraps the CompositeEnricher's children, not the CompositeEnricher itself.
45. **format_card_for_chat redundant enrichment rendering:** → When `card_body` is present (LLM-generated), skip raw enrichment context rendering. LLM already incorporated that context. Only render raw enrichment context as fallback when `card_body` is absent (template fallback mode).
46. **Leftover authoring commentary in plan:** → Strip debug text from plan markdown (lines like "Now I have everything I need...").
47. **React UI auth approach:** → Plan's Task 23 uses `/api/auth/token` endpoint which has a circular auth dependency (need token to get token). Revert to `__API_TOKEN__` meta tag approach per grilling #23. Server replaces placeholder when serving index.html. React reads from `<meta name="api-token">`. No new endpoint, no bootstrapping problem. Update plan's verification "FIX 19" to match.
48. **Meta sanitizer @fb.com only:** → Pattern `\b[a-z]{2,20}(?=@fb\.com)` misses `@meta.com` addresses. Fix regex to `\b[a-z]{2,20}(?=@(?:fb|meta)\.com)` to cover both.
49. **Tailwind CSS missing from React UI:** → Spec calls for Tailwind CSS but plan's Task 23 uses inline styles. Add `tailwindcss` and `@tailwindcss/vite` to devDependencies. Replace inline styles with Tailwind utility classes.
50. **Meta enrichers use tuple entity_refs:** → All three Meta enrichers in Task 24 use `("person", id)` tuples instead of `{"type": "person", "id": id}` dicts. Fix per decision #32.
51. **config.meta.yml uses old enrichment format:** → Update to new `EnrichmentConfig` format with `providers:` list mapping each enricher to source_types. Otherwise Meta enrichers won't be routed through `CompositeEnricher`. Include both core enrichers and Meta-specific enrichers.

## Out of Scope

- Automatic OAuth setup wizard (manual token setup via `workbench init` instructions)
- Rate limiting per source adapter (rely on poll interval config)
- Multi-account support for Google adapters (single account per adapter)
- Real-time/webhook ingestion (poll-based only)
- Meta-specific overrides of Google adapters (MetaGmailAdapter, etc.) — deferred until needed
- Card template customization per source type (LLM generates source-appropriate cards)
- Action Module for automated action execution (v2 — user todos are manual in v1)
- User preference model training from interaction logs (v2)
- Full entity resolution heuristics beyond signal-tiered attribute matching (v2)

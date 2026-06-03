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

**Async wrapping:** The Google API client library (`google-api-python-client`) is synchronous. All API calls are wrapped in `asyncio.to_thread()` to avoid blocking the event loop. This applies to all adapters and enrichers using the connection.

### InternConnection (workbench-meta)

`workbench_meta/providers/connection/intern.py`

Wraps Intern API / GraphQL authentication. Shared by Meta Tasks, Workplace, and Docs adapters.

**Open question:** The specific auth mechanism (cookie-based, service token, or other) will be determined during implementation based on what's available on devgpu.

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

Adding the `connections:` section and changing the `enrichment:` section shape are config schema changes. Bump config version from `0.1.0` to `0.2.0`. The `enrichment:` change is a **breaking change** — existing configs with the old single-enricher `dict` format must be migrated to the new `EnrichmentConfig` shape (see Enrichment Config section). Configs without a `connections:` section are valid — adapters that don't need a connection are unaffected.

## Track A: Source Adapters

All adapters implement the existing `SourceAdapter` ABC: `poll(since: datetime | None) -> list[RawItem]`.

### Adapter error isolation

The scheduler wraps each `source.poll()` call in a try/except, logs the error, and continues to the next adapter. A broken Gmail adapter does not prevent GitHub or Phabricator from polling. Failed adapters retry on the next poll cycle. The scheduler checks `connection.is_healthy()` before polling and skips adapters whose connection is unhealthy with a warning log.

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

**Thread state persistence:** The adapter persists its `tracked_threads` map across restarts. Implementation approach to be determined during planning (options: config store via stores access, or state file on disk).

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

**Open question:** Whether to use Workplace's own Graph API or Intern API. To be determined during implementation.

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

Every enricher returns an `entity_refs` field in its output dict. Entity IDs are source-qualified to support identity resolution:

```python
{
    "entity_refs": [
        (EntityType.PERSON, "github:alice-gh"),
        (EntityType.REPO, "github:owner/infra-core"),
    ],
    # ...rest of enrichment context
}
```

Entity ref mapping by source type:

| Source type | Entity refs extracted |
|------------|---------------------|
| `email` | `(PERSON, "email:{sender}")`, `(PERSON, "email:{recipient}")` per recipient |
| `github` | `(PERSON, "github:{author}")`, `(REPO, "github:{repo}")`, `(PERSON, "github:{reviewer}")` per reviewer |
| `calendar` | `(PERSON, "gcal:{organizer}")`, `(PERSON, "gcal:{attendee}")` per attendee |
| `gchat_message` | `(PERSON, "gchat:{sender}")`, `(SPACE, "gchat:{space_id}")` |
| `task` | `(PERSON, "task:{assignee}")`, `(PERSON, "task:{reporter}")` |
| `workplace` | `(PERSON, "wp:{author}")`, `(GROUP, "wp:{group_id}")` |
| `doc` | `(PERSON, "doc:{author}")`, `(PERSON, "doc:{last_editor}")` |
| `diff` | `(PERSON, "diff:{author}")`, `(PERSON, "diff:{reviewer}")` per reviewer, `(REPO, "diff:{repo}")` |

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
        return await enricher.enrich(item, depth, effective_budget, memory=memory)
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
| `GmailEnricher` | `google` | Full thread (other messages in thread), sender contact info, attachment content (images → description, PDFs → text extraction) |
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

The existing `entities` table is keyed by `(entity_type, entity_id)` where `entity_id` = `canonical_id`.

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
   - **No match** → new `canonical_id` = `"github:alice-gh"` (first-seen source_id), insert identity mapping

3. **UPSERT facts** into `entities` table under `(PERSON, canonical_id)` via JSONB `||` merge

4. **Update Neo4j graph** — create/update node under the canonical identity

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
2. Repoint all `entity_identities` rows from the absorbed canonical to the survivor
3. Merge facts from the absorbed entity into the survivor via JSONB `||`
4. Merge Neo4j graph nodes
5. Delete the absorbed entity row from the `entities` table

### Manual override

Two admin endpoints for correcting wrong merges:

- `POST /admin/merge-entities` — manually merge two entities. Same process as late discovery merge.
- `POST /admin/split-entity` — split a source_id out of a canonical entity into its own canonical entity. Creates a new entity with only the facts from that source, repoints the identity mapping.

Both operations update the identity table, entities table, and Neo4j graph atomically.

### Example lifecycle

```
Day 1: GitHub PR from alice-gh
  record_entity(PERSON, "github:alice-gh", {email: "alice@meta.com", name: "Alice Smith", team: "infra"})
  → no existing match → canonical_id = "github:alice-gh"
  → identity: (PERSON, "github:alice-gh") → "github:alice-gh"
  → entities: (PERSON, "github:alice-gh") = {email, name, team}

Day 2: Email from alice@meta.com
  record_entity(PERSON, "email:alice@meta.com", {email: "alice@meta.com", name: "Alice Smith"})
  → search: PERSON with email="alice@meta.com"? Yes → canonical_id = "github:alice-gh"
  → identity: (PERSON, "email:alice@meta.com") → "github:alice-gh"
  → entities: facts merged (team preserved from day 1)

Day 3: Phabricator diff from alice
  record_entity(PERSON, "diff:alice", {name: "Alice Smith", reviews: ["infra-core"]})
  → search: PERSON with name="Alice Smith"? Yes, score=5 (medium). Need 10. Not enough alone.
  → BUT if alice has username="alice" matching... depends on available facts.
  → If no auto-merge: new canonical_id = "diff:alice", separate entity
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
entity_ids = enrichment_context.get("entity_refs", [])
entities_and_rels = await asyncio.gather(
    *[memory.query_entity(t, i) for t, i in entity_ids],
    *[memory.query_relationships(t, i) for t, i in entity_ids],
    memory.query_preferences(item.summary),
)
```

3. **Build memory context** from results:

```python
memory_context = {
    "entity_facts": {f"{t}:{i}": e.facts for (t, i), e in zip(entity_ids, entities) if e},
    "relationships": all_relationships,
    "preference_facts": [f.content for f in preferences],
}
```

4. **Cap memory context** to keep the LLM prompt manageable:
   - Top 5 entity_refs by relevance (item author/sender first, then others)
   - Max 10 relationship entries total
   - Max 20 preference facts

5. **Call LLM** for card generation — always, regardless of memory availability. If memory is unavailable, `memory_context` is empty but the LLM still generates a card body from the enrichment context alone. Template fallback is used only when the LLM call itself fails.

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
- When the snooze expires, the card re-enters the queue at its original relevance score
- Item remains in `pending_triage` status throughout
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

**Timeout on pending states:** If no follow-up or confirmation arrives within 1 hour (configurable), the card reverts to `sent` status with response `"timed_out"` and the triage queue advances to the next card. This prevents a forgotten follow-up from blocking the entire triage pipeline. The card can be re-triaged later.

**Card rendering includes a free-text hint:**

```
1. Add todo P1 (suggested: you usually prioritize alice's PRs)
2. Add todo P2
3. Skip
4. Defer (snooze 4h)
5. Other — tell me what you'd like to do
Or just reply with what you'd like to do.
```

**Response handler logic:**

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
    action_category: str | None = None      # "delegation", "communication", "scheduling", "review", "creation", "update"
```

**Action categories** — fixed enum, constrained via LLM tool use:

```python
class ActionCategory(str, Enum):
    DELEGATION = "delegation"       # "Assign to bob", "Ask alice to review"
    COMMUNICATION = "communication" # "Forward to alice", "Reply to thread"
    SCHEDULING = "scheduling"       # "Schedule follow-up", "Block 30min for this"
    REVIEW = "review"               # "Review by Friday", "Read the RFC"
    CREATION = "creation"           # "Create task for this", "File a bug"
    UPDATE = "update"               # "Update the doc", "Fix the config"
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

Supports query params: `?status=active`, `?priority=P1`, `?category=delegation`.

`POST /api/actions/{id}/done` — marks an action item as done.

`POST /api/actions/{id}/priority` — changes priority. Body: `{"priority": "P1"}`.

`POST /api/actions/{id}/snooze` — snoozes an action item. Body: `{"hours": 4}`.

### Plugin Command

`/workbench:actions` — renders the categorized list in the CLI. Calls the API endpoint.

### Morning Briefing

Add a "Pending actions" section to the daily morning briefing, after the existing P0/P1/P2 sections:

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

**Stack:** Vite + React, built as static assets, served by FastAPI's `StaticFiles`. Multi-stage Docker build: Node stage builds React, Python stage copies built assets. During dev, Vite dev server proxies API calls to FastAPI.

**Location:** `ui/` directory at project root.

**Features:**
- Categorized list with collapsible sections
- Each item shows: summary, priority badge, parent item link, age
- Actions per item: "Mark done", "Change priority", "Snooze"
- Filter bar: by category, priority, action source
- Responsive — works on mobile for quick checks

**No state management library** — React hooks + fetch are sufficient for a single-page categorized list.

**Authentication:** No login page. This is a single-user tool on a devgpu. FastAPI injects the API bearer token into the HTML via a `<meta>` tag at page serve time. The React app reads it and passes it as an Authorization header on all fetch calls. If the tool is ever exposed externally, proper auth can be added then.

### v2 Hook: Action Module

In v2, user todos will go to an action queue instead of directly creating Items. An Action Module will:
- Pick up items from the action queue
- Execute automatable actions (assign tasks, send messages, create calendar events) on behalf of the user
- Surface non-automatable actions as user todos (same as v1)

The `action_source` field on Items and the `InterpretedResponse` logging provide the data model and training data for this transition. The v1 architecture doesn't need to change — the Action Module is an additional consumer of the same data.

## File Changes

### Core `workbench/` — New Files

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

### Core `workbench/` — Modified Files

| File | Change |
|------|--------|
| `models.py` | Add `EntityType` enum, `ActionCategory` enum; add `suggested`, `suggestion_reason` to `TriageOption`; add `deferred_until` to `TriageCard`; add `parent_item_id`, `action_source`, `action_category` to `Item`; add `awaiting_followup` and `awaiting_confirmation` to card status; add `InterpretedResponse`, `SystemAction`, `UserTodo` models; change `TriageResponse.choice` from `int` to `int \| None = None` (free-text responses have `choice=None`, `raw_text` populated); add `type`, `interpreted`, `confirmed` fields to `InteractionEntry` |
| `config.py` | Add `connections:` section, new `EnrichmentConfig` model (breaking change from `dict \| None`), bump config version to `0.2.0` |
| `main.py` | Initialize connections at startup, pass to provider registry with two-arg constructor, use `create_composite_enricher`, serve static UI assets, close on shutdown |
| `registry.py` | Support two-arg constructor for connection injection; add `create_composite_enricher()` function that pops `source_types`/`connection`/`budget` and builds CompositeEnricher |
| `pipeline/triage.py` | `generate_card()` accepts `memory`, extracts entity_refs, gathers memory context (resolved through identity), passes to LLM; always append "Other" option; always LLM, template on failure only; simplify `format_card_for_chat()` with free-text hint |
| `pipeline/engine.py` | Pass `self.memory` to `generate_card()` |
| `providers/llm/base.py` | Add `memory_context: dict \| None = None` to `generate_triage_card()`; add `interpret_triage_response()` method |
| `providers/llm/anthropic.py` | LLM card generation prompt with indexed preference facts and tool use enum constraint; suggestion validation; `interpret_triage_response()` with InterpretedResponse schema; template fallback on LLM failure only |
| `providers/enrichment/base.py` | Document that enrichers receive connections via two-arg constructor; document `entity_refs` output requirement |
| `config.example.yml` | Add `connections:` section, Gmail/Calendar/GChat source examples, new enrichment provider list format |
| `pipeline/scheduler.py` | Error isolation per adapter (try/except around each `source.poll()`); check `connection.is_healthy()` before polling; triage queue skips cards with `deferred_until > now()`; skip expiry check for deferred cards; add "Pending actions" section to morning briefing |
| `api/triage.py` | Handle `choice=None` as free-text path; add `defer` action handler; add `other` action handler (set `awaiting_followup`); handle `awaiting_followup` and `awaiting_confirmation` states; execute `InterpretedResponse` (system actions + user todos); confirmation flow for destructive actions; log interpreted responses |
| `storage/postgres/triage.py` | Update `get_pending()` to include `awaiting_followup`/`awaiting_confirmation` in status IN clause; update `get_next_unsent()` to add `AND (deferred_until IS NULL OR deferred_until <= NOW())`; update `expire_old_cards()` to exclude `awaiting_followup`/`awaiting_confirmation` (they have their own 1h timeout) |
| `storage/postgres/interactions.py` | Update INSERT and `_row_to_entry()` deserializer for new InteractionEntry fields (`type`, `interpreted`, `confirmed`) |
| `migrations/` | Alembic migration: add `deferred_until` to `triage_cards`; add `parent_item_id`, `action_source`, `action_category` to `items` |

### Memory service (`src/memory/`) — Modified Files

| File | Change |
|------|--------|
| `queue.py` | Add `entity_identities` table creation in `initialize()` |
| `graphiti_layer.py` | Identity resolution in `record_entity()`: check identity table, score identifying attributes, auto-merge or create new canonical; late discovery merge logic; update `query_entity()` to resolve through identity table |
| `main.py` | Add `POST /admin/merge-entities` and `POST /admin/split-entity` endpoints |
| `models.py` | Add signal tier constants for identifying attributes |

### `workbench-meta/` — New Files

| File | Description |
|------|-------------|
| `providers/connection/__init__.py` | Connection package |
| `providers/connection/intern.py` | `InternConnection` — Intern API / GraphQL auth (mechanism TBD) |
| `providers/source/meta_tasks.py` | `MetaTasksAdapter` — polls tasks via meta CLI or GraphQL |
| `providers/source/workplace.py` | `WorkplaceAdapter` — polls Workplace group posts |
| `providers/source/docs.py` | `MetaDocsAdapter` — polls wiki/doc updates |
| `providers/enrichment/meta_tasks.py` | `MetaTasksEnricher` — subtasks, blockers, related diffs |
| `providers/enrichment/workplace.py` | `WorkplaceEnricher` — comments, reactions, author role |
| `providers/enrichment/docs.py` | `MetaDocsEnricher` — content summary, edit history |

### `workbench-meta/` — Modified Files

| File | Change |
|------|--------|
| config files | Add `connections:` section, Meta-internal source and enricher entries, full enricher provider list (core + meta) |
| `providers/llm/meta_anthropic.py` | Inherits LLM card generation and interpret_triage_response from parent — no changes needed |

### Tests

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

## Open Questions

To be resolved during implementation:

1. **Workplace API:** Whether to use Workplace's own Graph API or Intern API for polling posts.
2. **InternConnection auth:** Specific auth mechanism for Intern API from devgpu (cookie-based, service token, or other).
3. **GChat thread state persistence:** Whether to use the config store (requires stores access in adapter) or a state file on disk.

## Verification

Phase 1d is complete when:

### Track A
1. `GoogleConnection` initializes, refreshes tokens, and exposes service accessors
2. All Google API calls are wrapped in `asyncio.to_thread()` — no event loop blocking
3. All 3 Google adapters (`Gmail`, `GCalendar`, `GChat`) return `list[RawItem]` from `poll(since)` using the shared connection
4. All 3 Meta adapters (`MetaTasks`, `Workplace`, `MetaDocs`) return `list[RawItem]` from `poll(since)` using the shared connection
5. Each adapter produces correct `source_type`, `source_id`, `raw_text`, and `urgency_signals`
6. Gmail adapter correctly extracts multipart MIME bodies and captures attachment metadata (including inline images)
7. Calendar adapter deduplicates by meaningful-field hash (RSVP changes don't trigger re-ingestion); recurring events include `recurring_event_id` in urgency signals
8. GChat adapter implements thread subscription with configurable track mode, thread re-entry on participation, and bot message filtering
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
35. `defer` action sets `deferred_until` and the triage queue respects it; deferred cards pause expiry
36. `format_card_for_chat()` renders card body + options with suggestion markers + free-text hint
37. No regression in card rendering for existing GitHub/Phabricator sources

### Track C
38. `GET /api/actions` returns active action items grouped by `action_category`
39. Action API supports done, priority change, and snooze operations
40. `/workbench:actions` plugin command renders categorized list
41. Morning briefing includes "Pending actions" section grouped by category
42. React UI at `/ui/actions` renders categorized action list with mark done, change priority, and snooze
43. React UI is built with Vite, served as static assets by FastAPI

### All Tracks
44. `connections:` config section is parsed, validated, and connections are initialized at startup
45. Registry supports two-arg constructor for connection injection
46. `create_composite_enricher()` correctly pops `source_types`/`connection`/`budget` and builds CompositeEnricher
47. `EnrichmentConfig` model replaces old `dict | None` config (breaking change documented)
48. Config version is bumped to `0.2.0`
49. `Item` model has `parent_item_id`, `action_source`, `action_category` fields (Alembic migration)
50. All existing tests pass (no regressions)

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

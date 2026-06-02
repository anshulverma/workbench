# Phase 1d: Memory-Enriched Triage Cards, Connections, and Source Adapters — Design Spec

## Context

Phase 1c delivered entity knowledge, decision recording, relationship querying, and memory rebuild. The memory service now records entities and pipeline decisions, and the noise filter uses entity/relationship context for scoring. However, triage cards are still template-based — they don't leverage memory context — and only two source adapters exist (GitHub in core, Phabricator in workbench-meta). Content from email, calendar, chat, tasks, workplace, and docs doesn't flow into the system.

Phase 1d fills both gaps with two independent tracks:

- **Track A** — Source adapters and enrichers for 6 new content sources, built on a shared connection abstraction
- **Track B** — LLM-generated triage cards that explain *why* an item matters using entity knowledge, relationships, and preference facts

## Goals

1. **Connections** — First-class config section for shared external system credentials. Adapters and enrichers reference a connection by name instead of managing their own auth.
2. **Source adapters** — 6 new adapters (3 generic in core, 3 Meta-internal in workbench-meta) so email, calendar, chat, tasks, workplace, and docs flow into the ingestion pipeline.
3. **Source-specific enrichers** — Each new source type gets a paired enricher that uses the same connection as its adapter. A `CompositeEnricher` routes to the right enricher by source type. All enrichers return a standardized `entity_refs` field.
4. **Memory-enriched triage cards** — Replace template-based card generation with an LLM call that synthesizes item summary + enrichment context + entity knowledge + relationships + preference facts into a contextual card body with dynamic options.

## Architecture

### Two Independent Tracks

```
Track A (Sources)                          Track B (Cards)

connections:                               Item + Enrichment Context
├── google (OAuth2)                          + entity_refs from enrichment
│   ├── GmailAdapter + GmailEnricher         + query_entity() per entity_ref
│   ├── GCalendarAdapter + GCalEnricher      + query_relationships() per entity_ref
│   └── GChatAdapter + GChatEnricher         + query_preferences()
└── meta_intern (Intern API)                      │
    ├── MetaTasksAdapter + Enricher               ▼
    ├── WorkplaceAdapter + Enricher        LLM card generation
    └── MetaDocsAdapter + Enricher         (always LLM, template on failure only)
         │                                       │
         ▼                                       ▼
    RawItem → Ingestion Queue              TriageCard
                                           (contextual body + dynamic options
                                            + suggested with fact citation)
```

Track A produces `RawItem` objects that enter the existing pipeline. Track B consumes `Item` objects that come out of the pipeline. They meet at the ingestion queue — completely decoupled.

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
  track: "participating"   # "participating" | "mentioned" | "all"
```

**Important distinction:** This is the *ingestion* side — reading messages from spaces you want to monitor. The *messenger* provider (sending triage cards via Google Chat) is a separate interface with its own auth, already in workbench-meta as WIB Google Chat. They do NOT share a connection.

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

Every enricher returns an `entity_refs` field in its output dict:

```python
{
    "entity_refs": [
        (EntityType.PERSON, "alice"),
        (EntityType.REPO, "infra-core"),
    ],
    # ...rest of enrichment context
}
```

Entity ref mapping by source type:

| Source type | Entity refs extracted |
|------------|---------------------|
| `email` | `(PERSON, sender)`, `(PERSON, each_recipient)` |
| `github` | `(PERSON, author)`, `(REPO, repo_name)`, `(PERSON, each_reviewer)` |
| `calendar` | `(PERSON, organizer)`, `(PERSON, each_attendee)` |
| `gchat_message` | `(PERSON, sender)`, `(SPACE, space_name)` |
| `task` | `(PERSON, assignee)`, `(PERSON, reporter)` |
| `workplace` | `(PERSON, author)`, `(GROUP, group_name)` |
| `doc` | `(PERSON, author)`, `(PERSON, last_editor)` |
| `diff` | `(PERSON, author)`, `(PERSON, each_reviewer)`, `(REPO, repo_name)` |

### CompositeEnricher

New enricher in `workbench/providers/enrichment/composite.py` that routes to the right enricher by source type:

```python
class CompositeEnricher(ContextEnricher):
    def __init__(self, enrichers: dict[str, ContextEnricher], default: ContextEnricher | None = None):
        self.enrichers = enrichers
        self.default = default or StubEnricher()

    async def enrich(self, item, depth, budget, memory):
        enricher = self.enrichers.get(item.source_type, self.default)
        return await enricher.enrich(item, depth, budget, memory)
```

### Enrichment Config

The `enrichment:` config section changes from a single provider (`dict | None`) to a structured `EnrichmentConfig` model. **This is a breaking change** — existing configs must be migrated.

New config shape:

```yaml
enrichment:
  providers:
    - class: workbench.providers.enrichment.gmail.GmailEnricher
      connection: google
      source_types: ["email"]
    - class: workbench.providers.enrichment.github.GitHubEnricher
      source_types: ["github"]
    - class: workbench.providers.enrichment.gcalendar.GCalendarEnricher
      connection: google
      source_types: ["calendar"]
    - class: workbench.providers.enrichment.gchat.GChatEnricher
      connection: google
      source_types: ["gchat_message"]
  default: stub
```

In `config.py`:

```python
class EnrichmentConfig(BaseModel):
    providers: list[dict] = []
    default: str = "stub"
```

The pipeline engine constructs a `CompositeEnricher` from the list, mapping each provider's `source_types` to the enricher instance. The `default` field selects the fallback enricher for unmatched source types.

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
2. Record `memory.record_entity()` with newly discovered facts after enrichment

This applies to all new enrichers, not just GitHubEnricher.

## Track B: Memory-Enriched Triage Cards

### Current State

`generate_card()` in `pipeline/triage.py` delegates to `llm.generate_triage_card()` which is template-based:
- `card_content` = `{summary, source_type, enrichment}`
- Options are hardcoded per source type (Add todo P1, Add todo P2, Skip, Mute)
- No memory context consulted

### New Card Generation Flow

`generate_card()` gains a `memory: MemoryLayer` parameter. The flow:

1. **Extract entity references** from the enrichment context's `entity_refs` field
2. **Query memory** for each referenced entity in parallel:

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

4. **Call LLM** for card generation — always, regardless of memory availability. If memory is unavailable, `memory_context` is empty but the LLM still generates a card body from the enrichment context alone. Template fallback is used only when the LLM call itself fails.

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
   - "details": Optional context (e.g., priority level for add_todo, snooze duration for defer)
   - "suggested_fact_index": Integer index into the preference_facts list that justifies suggesting this option, or null if no fact supports a suggestion
```

The LLM returns structured JSON via tool use.

### Suggestion Validation

Post-processing validates LLM suggestions against actual preference facts:

1. If `suggested_fact_index` is `null` → `suggested = False`
2. If `suggested_fact_index` is out of bounds (>= len(preference_facts)) → `suggested = False`
3. If valid index → `suggested = True`, `suggestion_reason` is auto-populated from `preference_facts[index]`

This ensures suggestions are always grounded in a real preference fact. The LLM cannot hallucinate patterns.

### Options as TriageOption Objects

LLM-generated option dicts are converted to `TriageOption` objects and stored in `card.options` (the model field). The `card_content` stores the full LLM response including the card body, but the canonical options list is always `card.options: list[TriageOption]`.

`TriageOption` gains two new fields:

```python
class TriageOption(BaseModel):
    label: str
    action: str
    details: str = ""
    suggested: bool = False
    suggestion_reason: str | None = None
```

This means:
- Response handling code is unchanged — always reads `card.options[i].action`
- `format_card_for_chat()` reads `card.card_content["card_body"]` for the body and `card.options` for the list
- One source of truth for options, no dual-path handling

### Defer Action (Snooze)

A new triage action `defer` puts the card back in the queue with a delay. Implementation:

- Add `deferred_until: datetime | None` column to the `triage_cards` table (Alembic migration)
- When the user selects `defer`, set `deferred_until` to now + snooze duration (default 4 hours, configurable via option `details`)
- The triage queue skips cards where `deferred_until > now()`
- When the snooze expires, the card re-enters the queue at its original relevance score
- Item remains in `pending_triage` status throughout

### Fallback Behavior

Card generation always attempts the LLM call. If the LLM call fails (timeout, API error, malformed response):
- Fall back to the existing template behavior (static card body + hardcoded options)
- Log the error
- The card is still created and queued — just without memory context or LLM-generated body

### Cost

One additional LLM call per triaged item. Auto-included and auto-dropped items don't get cards. The call uses the same model as extraction and scoring — no new provider needed. For a typical day with 10-20 triaged items, this adds 10-20 LLM calls.

### Changes to format_card_for_chat()

With LLM-generated cards, the card body is pre-formatted. `format_card_for_chat()` reads the card body from `card_content["card_body"]` and options from `card.options`:

```python
def format_card_for_chat(card: TriageCard) -> str:
    body = card.card_content.get("card_body", card.card_content.get("summary", ""))
    lines = [f"*{body}*", ""]
    for i, opt in enumerate(card.options, 1):
        suggested = f" _(suggested: {opt.suggestion_reason})_" if opt.suggested else ""
        lines.append(f"{i}. {opt.label}{suggested}")
    return "\n".join(lines)
```

Always reads from `card.options` (TriageOption objects) — no dual-path handling.

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
| `providers/enrichment/composite.py` | `CompositeEnricher` — routes by source_type |
| `models.py` | `EntityType` enum |

### Core `workbench/` — Modified Files

| File | Change |
|------|--------|
| `config.py` | Add `connections:` section, new `EnrichmentConfig` model (breaking change from `dict \| None`), bump config version to `0.2.0` |
| `main.py` | Initialize connections at startup, pass to provider registry with two-arg constructor, close on shutdown |
| `registry.py` | Support two-arg constructor: `cls(config, connection=resolved_connection)` when config has `connection:` field |
| `pipeline/triage.py` | `generate_card()` accepts `memory`, extracts entity_refs, gathers memory context, passes to LLM; always LLM, template on failure only; simplify `format_card_for_chat()` |
| `pipeline/engine.py` | Pass `self.memory` to `generate_card()` |
| `providers/llm/base.py` | Add `memory_context: dict \| None = None` parameter to `generate_triage_card()` |
| `providers/llm/anthropic.py` | LLM card generation prompt with indexed preference facts; suggestion validation; template fallback on LLM failure only |
| `providers/enrichment/base.py` | Document that enrichers receive connections via two-arg constructor; document `entity_refs` output requirement |
| `models.py` | Add `suggested: bool = False` and `suggestion_reason: str \| None = None` to `TriageOption`; add `deferred_until: datetime \| None` to `TriageCard` |
| `config.example.yml` | Add `connections:` section, Gmail/Calendar/GChat source examples, new enrichment provider list format |
| `pipeline/scheduler.py` | Error isolation per adapter (try/except around each `source.poll()`), check `connection.is_healthy()` before polling |
| `migrations/` | Alembic migration: add `deferred_until` column to `triage_cards` table |
| `api/triage.py` or `pipeline/scheduler.py` | Triage queue skips cards where `deferred_until > now()` |

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
| `providers/llm/meta_anthropic.py` | Inherits LLM card generation from parent — no changes needed |

### Tests

| File | Description |
|------|-------------|
| `tests/test_google_connection.py` | OAuth2 token loading, refresh, service accessors, `is_healthy()` |
| `tests/test_gmail_adapter.py` | Poll with label filters, MIME extraction, attachment metadata, RawItem construction, dedup |
| `tests/test_gcalendar_adapter.py` | Poll with lookahead, meaningful-field hash dedup, recurring event signals |
| `tests/test_gchat_adapter.py` | Thread subscription lifecycle (enter/exit/re-enter), track modes, bot message filtering |
| `tests/test_composite_enricher.py` | Routing by source_type, default fallback |
| `tests/test_entity_refs.py` | Each enricher returns correct entity_refs with EntityType enum values |
| `tests/test_triage_card_enrichment.py` | LLM card generation with/without memory context, suggestion validation (valid index, invalid index, null), template fallback on LLM failure, defer action |
| `tests/test_registry_connection.py` | Two-arg constructor injection, single-arg backward compatibility |

### ABC Changes

- **New ABC:** `Connection` with `initialize()`, `close()`, `is_healthy()`
- **New enum:** `EntityType` with `PERSON`, `REPO`, `TEAM`, `SPACE`, `GROUP`
- **Modified:** `LLMProvider.generate_triage_card()` — add optional `memory_context: dict | None = None`
- **Modified:** `TriageOption` — add `suggested: bool = False`, `suggestion_reason: str | None = None`
- **Modified:** `TriageCard` — add `deferred_until: datetime | None = None`
- **New class:** `CompositeEnricher` (concrete, not ABC) wrapping multiple enrichers

### Config Schema Changes

- **New section:** `connections:` — dict of named connections, each with `class:` and connection-specific config
- **Modified section:** `sources:` entries gain optional `connection:` field (name reference)
- **Breaking change:** `enrichment:` changes from `dict | None` to `EnrichmentConfig` model with `providers: list[dict]` and `default: str`. Existing configs must be migrated.
- **Config version:** `0.1.0` → `0.2.0` (minor bump; enrichment change is breaking and requires manual config update)

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
6. Gmail adapter correctly extracts multipart MIME bodies and captures attachment metadata
7. Calendar adapter deduplicates by meaningful-field hash (RSVP changes don't trigger re-ingestion)
8. GChat adapter implements thread subscription with configurable track mode and bot message filtering
9. Dedup works correctly for each adapter (unique `source_id` per item, modifications detected where applicable)
10. Scheduler polls all configured adapters on schedule with error isolation (one failure doesn't block others)
11. `CompositeEnricher` routes to the correct enricher by source type
12. Each enricher returns useful context using the shared connection and includes `entity_refs` with `EntityType` enum values
13. All new adapters and enrichers work end-to-end: poll → enqueue → extract → filter → enrich → triage card

### Track B
14. Triage cards are always LLM-generated (template only on LLM failure)
15. Card body uses enrichment context, entity knowledge, relationships, and preference context from memory
16. Card body explains *why* the item matters based on memory
17. LLM options are converted to `TriageOption` objects with `suggested` and `suggestion_reason` fields
18. Suggestion validation: `suggested_fact_index` checked against preference_facts bounds; invalid indices strip the suggestion
19. `defer` action sets `deferred_until` and the triage queue respects it
20. `format_card_for_chat()` renders card body + options with suggestion markers
21. No regression in card rendering for existing GitHub/Phabricator sources

### Both
22. `connections:` config section is parsed, validated, and connections are initialized at startup
23. Registry supports two-arg constructor for connection injection
24. `EnrichmentConfig` model replaces old `dict | None` config
25. Config version is bumped to `0.2.0`
26. All existing tests pass (no regressions)

## Out of Scope

- Automatic OAuth setup wizard (manual token setup via `workbench init` instructions)
- Rate limiting per source adapter (rely on poll interval config)
- Multi-account support for Google adapters (single account per adapter)
- Real-time/webhook ingestion (poll-based only)
- Meta-specific overrides of Google adapters (MetaGmailAdapter, etc.) — deferred until needed
- Enricher depth/budget tuning per source type (use global enrichment config)
- Card template customization per source type (LLM generates source-appropriate cards)

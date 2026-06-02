# Phase 1d: Memory-Enriched Triage Cards, Connections, and Source Adapters — Design Spec

## Context

Phase 1c delivered entity knowledge, decision recording, relationship querying, and memory rebuild. The memory service now records entities and pipeline decisions, and the noise filter uses entity/relationship context for scoring. However, triage cards are still template-based — they don't leverage memory context — and only two source adapters exist (GitHub in core, Phabricator in workbench-meta). Content from email, calendar, chat, tasks, workplace, and docs doesn't flow into the system.

Phase 1d fills both gaps with two independent tracks:

- **Track A** — Source adapters and enrichers for 6 new content sources, built on a shared connection abstraction
- **Track B** — LLM-generated triage cards that explain *why* an item matters using entity knowledge, relationships, and preference facts

## Goals

1. **Connections** — First-class config section for shared external system credentials. Adapters and enrichers reference a connection by name instead of managing their own auth.
2. **Source adapters** — 6 new adapters (3 generic in core, 3 Meta-internal in workbench-meta) so email, calendar, chat, tasks, workplace, and docs flow into the ingestion pipeline.
3. **Source-specific enrichers** — Each new source type gets a paired enricher that uses the same connection as its adapter. A `CompositeEnricher` routes to the right enricher by source type.
4. **Memory-enriched triage cards** — Replace template-based card generation with an LLM call that synthesizes item summary + enrichment context + entity knowledge + relationships + preference facts into a contextual card body with dynamic options.

## Architecture

### Two Independent Tracks

```
Track A (Sources)                          Track B (Cards)

connections:                               Item + Enrichment Context
├── google (OAuth2)                          + query_entity()
│   ├── GmailAdapter + GmailEnricher         + query_relationships()
│   ├── GCalendarAdapter + GCalEnricher      + query_preferences()
│   └── GChatAdapter + GChatEnricher              │
└── meta_intern (Intern API)                      ▼
    ├── MetaTasksAdapter + Enricher        LLM card generation
    ├── WorkplaceAdapter + Enricher        (replaces template)
    └── MetaDocsAdapter + Enricher               │
         │                                       ▼
         ▼                                 TriageCard
    RawItem → Ingestion Queue              (contextual body + dynamic options)
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

### GoogleConnection

`workbench/providers/connection/google.py`

Wraps the Google API client library with auto-refreshing OAuth2 tokens. Manages a single set of credentials with multiple API scopes.

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

### InternConnection (workbench-meta)

`workbench_meta/providers/connection/intern.py`

Wraps Intern API / GraphQL authentication. Shared by Meta Tasks, Workplace, and Docs adapters.

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

### How connections reach adapters and enrichers

The provider registry resolves connections first (by name from the `connections:` config section), then passes the resolved connection instance to each adapter/enricher constructor that declares a `connection:` field in its config. Adapters and enrichers store the connection as `self._connection` and use it for API calls.

Adapters/enrichers that don't need a connection (like `GitHubSourceAdapter` using `gh` CLI) simply don't declare a `connection:` field and their constructor is unchanged.

### Config version bump

Adding the `connections:` section is a config schema change. Bump config version from `0.1.0` to `0.2.0` (minor — additive, backward-compatible). Configs without a `connections:` section are valid — adapters that don't need a connection are unaffected.

## Track A: Source Adapters

All adapters implement the existing `SourceAdapter` ABC: `poll(since: datetime | None) -> list[RawItem]`.

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
- `raw_text`: JSON with subject, sender, recipients (to/cc), body (truncated to 4000 chars), snippet, thread_id
- `urgency_signals`: `{sender: str, is_direct: bool, cc_count: int, thread_depth: int, has_attachments: bool, labels: list[str]}`

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
- `source_id`: `"cal_{event_id}_{updated_timestamp}"`
- `raw_text`: JSON with title, description, attendees, location, start/end times, organizer, conference link
- `urgency_signals`: `{attendee_count: int, is_organizer: bool, starts_within_hours: int, has_agenda: bool, is_recurring: bool}`

**Dedup:** `source_id` includes the update timestamp so modifications are re-ingested while the original is deduped.

### Google Chat (core)

`workbench/providers/source/gchat.py`

**Connection:** `google`

**Config:**
```yaml
- class: workbench.providers.source.gchat.GChatAdapter
  connection: google
  spaces: ["spaces/AAAA..."]
```

**Poll behavior:** Queries Chat API for messages in configured spaces since `since`. Each message becomes a `RawItem`:
- `source_type`: `"gchat_message"`
- `source_id`: `"gchat_{message_name}"`
- `raw_text`: JSON with text, sender, space name, thread name, annotations (links, mentions)
- `urgency_signals`: `{is_mention: bool, is_direct_message: bool, thread_depth: int, sender: str, space_name: str}`

**Important distinction:** This is the *ingestion* side — reading messages from spaces you want to monitor. The *messenger* provider (sending triage cards via Google Chat) is a separate interface and already exists in workbench-meta as WIB Google Chat.

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

**Poll behavior:** Queries posts from configured groups since `since` via Intern API / GraphQL. Each post becomes a `RawItem`:
- `source_type`: `"workplace"`
- `source_id`: `"wp_{post_id}"`
- `raw_text`: JSON with content, author, group name, permalink, attachments
- `urgency_signals`: `{author: str, group_name: str, comment_count: int, is_mention: bool, reaction_count: int}`

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

**Config:**
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

The pipeline engine constructs a `CompositeEnricher` from the list, mapping each provider's `source_types` to the enricher instance.

### Enricher Details

| Enricher | Connection | What it fetches |
|----------|-----------|-----------------|
| `GmailEnricher` | `google` | Full thread (other messages in thread), sender contact info, attachment names and sizes |
| `GCalendarEnricher` | `google` | Attendee org info (if available), related documents linked in description, recurring event pattern |
| `GChatEnricher` | `google` | Full thread context (prior messages), space description, linked resources |
| `MetaTasksEnricher` | `meta_intern` | Subtask list, blocker details, related diffs, parent task context |
| `WorkplaceEnricher` | `meta_intern` | Top comments, reactions summary, linked resources, author role |
| `MetaDocsEnricher` | `meta_intern` | Doc content summary (longer excerpt), recent edit history, linked tasks, related docs |
| `GitHubEnricher` | (gh CLI) | Existing — unchanged. Files changed, review status, labels, CI status, assignees, comment count |

Each enricher follows the `ContextEnricher` ABC: `async def enrich(self, item, depth, budget, memory) -> dict`. The returned dict is source-type-specific but always contains fields the card renderer can use.

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

`generate_card()` gains a `memory: MemoryLayer` parameter. Before calling the LLM, it gathers memory context in parallel:

```python
entity, relationships, preferences = await asyncio.gather(
    memory.query_entity(source_type, source_id),
    memory.query_relationships(source_type, source_id),
    memory.query_preferences(item.summary),
)
memory_context = {
    "entity_facts": entity.facts if entity else {},
    "relationships": relationships,
    "preference_facts": [f.content for f in preferences],
}
```

This is passed to `llm.generate_triage_card(item, enrichment_context, source_type, memory_context)`.

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
- User preferences: {preference_facts}

Generate a JSON response with:

1. "card_body": A concise card body (2-4 sentences) that:
   - Summarizes what this item is about
   - Explains WHY it might matter to the user, citing entity knowledge and preferences
   - Highlights relevant relationships (e.g., "from alice, who you usually prioritize")

2. "options": A list of 3-5 triage options, each with:
   - "label": Short action phrase
   - "action": One of "add_todo", "skip", "mute_pattern", "defer"
   - "details": Optional context (e.g., priority level for add_todo)
   - "suggested": Boolean — true if past behavior suggests this is the likely choice
   - "suggestion_reason": If suggested, why (e.g., "you've skipped similar items 4 times")
```

The LLM returns structured JSON via tool use. `card_content` stores the full LLM response. `format_card_for_chat()` renders the `card_body` + numbered options, with a `(suggested)` marker on recommended options.

### Fallback Behavior

If memory is unavailable (`NoopMemoryLayer`, memory service down, or `is_available()` returns `False`):
- Memory queries are skipped entirely
- `memory_context` is passed as `None`
- The LLM call is skipped — card generation falls back to the existing template behavior
- No degraded LLM call with empty memory context

This means cards are always either fully memory-enriched or fully template-based. No half-baked middle ground.

### Cost

One additional LLM call per triaged item. Auto-included and auto-dropped items don't get cards. The call uses the same model as extraction and scoring — no new provider needed. For a typical day with 10-20 triaged items, this adds 10-20 LLM calls.

### Changes to format_card_for_chat()

With LLM-generated cards, the card body is pre-formatted. `format_card_for_chat()` simplifies to:

```python
def format_card_for_chat(card: TriageCard) -> str:
    body = card.card_content.get("card_body", card.card_content.get("summary", ""))
    options = card.card_content.get("options", card.options)
    lines = [f"*{body}*", ""]
    for i, opt in enumerate(options, 1):
        label = opt.get("label", opt) if isinstance(opt, dict) else opt.label
        suggested = " _(suggested)_" if isinstance(opt, dict) and opt.get("suggested") else ""
        lines.append(f"{i}. {label}{suggested}")
    return "\n".join(lines)
```

Handles both LLM-generated (dict options) and template-generated (TriageOption objects) cards for backward compatibility.

## File Changes

### Core `workbench/` — New Files

| File | Description |
|------|-------------|
| `providers/connection/__init__.py` | Connection package |
| `providers/connection/base.py` | `Connection` ABC |
| `providers/connection/google.py` | `GoogleConnection` — OAuth2 token management, Gmail/Calendar/Chat service accessors |
| `providers/source/gmail.py` | `GmailAdapter` — polls Gmail API |
| `providers/source/gcalendar.py` | `GCalendarAdapter` — polls Calendar API |
| `providers/source/gchat.py` | `GChatAdapter` — polls Chat API |
| `providers/enrichment/gmail.py` | `GmailEnricher` — full thread, sender info |
| `providers/enrichment/gcalendar.py` | `GCalendarEnricher` — attendees, linked docs |
| `providers/enrichment/gchat.py` | `GChatEnricher` — thread context, space metadata |
| `providers/enrichment/composite.py` | `CompositeEnricher` — routes by source_type |

### Core `workbench/` — Modified Files

| File | Change |
|------|--------|
| `config.py` | Add `connections:` section to config schema, parse and validate connection configs |
| `main.py` | Initialize connections at startup, pass to provider registry, close on shutdown |
| `pipeline/triage.py` | `generate_card()` accepts `memory`, gathers memory context, passes to LLM; simplify `format_card_for_chat()` |
| `pipeline/engine.py` | Pass `self.memory` to `generate_card()` |
| `providers/llm/base.py` | Add `memory_context: dict | None = None` parameter to `generate_triage_card()` |
| `providers/llm/anthropic.py` | LLM card generation prompt when `memory_context` provided; template fallback when `None` |
| `providers/enrichment/base.py` | Document that enrichers receive connections via constructor |
| `config.example.yml` | Add `connections:` section, Gmail/Calendar/GChat source examples, enrichment provider list |

### `workbench-meta/` — New Files

| File | Description |
|------|-------------|
| `providers/connection/__init__.py` | Connection package |
| `providers/connection/intern.py` | `InternConnection` — Intern API / GraphQL auth |
| `providers/source/meta_tasks.py` | `MetaTasksAdapter` — polls tasks via meta CLI or GraphQL |
| `providers/source/workplace.py` | `WorkplaceAdapter` — polls Workplace group posts |
| `providers/source/docs.py` | `MetaDocsAdapter` — polls wiki/doc updates |
| `providers/enrichment/meta_tasks.py` | `MetaTasksEnricher` — subtasks, blockers, related diffs |
| `providers/enrichment/workplace.py` | `WorkplaceEnricher` — comments, reactions, author role |
| `providers/enrichment/docs.py` | `MetaDocsEnricher` — content summary, edit history |

### `workbench-meta/` — Modified Files

| File | Change |
|------|--------|
| config files | Add `connections:` section, Meta-internal source and enricher entries |
| `providers/llm/meta_anthropic.py` | Inherits LLM card generation from parent — no changes needed |

### Tests

| File | Description |
|------|-------------|
| `tests/test_google_connection.py` | OAuth2 token loading, refresh, service accessors |
| `tests/test_gmail_adapter.py` | Poll with label filters, RawItem construction, dedup |
| `tests/test_gcalendar_adapter.py` | Poll with lookahead, event dedup by update timestamp |
| `tests/test_gchat_adapter.py` | Poll spaces, message dedup |
| `tests/test_composite_enricher.py` | Routing by source_type, default fallback |
| `tests/test_triage_card_enrichment.py` | LLM card generation with memory context, fallback to template |

### ABC Changes

- **New ABC:** `Connection` with `initialize()`, `close()`, `is_healthy()`
- **Modified:** `LLMProvider.generate_triage_card()` — add optional `memory_context: dict | None = None`
- **New class:** `CompositeEnricher` (concrete, not ABC) wrapping multiple enrichers

### Config Schema Changes

- **New section:** `connections:` — dict of named connections, each with `class:` and connection-specific config
- **Modified section:** `sources:` entries gain optional `connection:` field (name reference)
- **Modified section:** `enrichment:` becomes a list of providers with `source_types:` routing, plus `default:`
- **Modified section:** `enrichment:` changes from a single provider (`class:` + config) to a list of providers with `source_types:` routing, plus `default:`. Existing configs with the old single-enricher format are handled by wrapping the single enricher in a `CompositeEnricher` with no routing (it handles all source types). This is a backward-compatible change.
- **Config version:** `0.1.0` → `0.2.0` (minor bump — additive, backward-compatible)

## Verification

Phase 1d is complete when:

### Track A
1. `GoogleConnection` initializes, refreshes tokens, and exposes service accessors
2. All 3 Google adapters (`Gmail`, `GCalendar`, `GChat`) return `list[RawItem]` from `poll(since)` using the shared connection
3. All 3 Meta adapters (`MetaTasks`, `Workplace`, `MetaDocs`) return `list[RawItem]` from `poll(since)` using the shared connection
4. Each adapter produces correct `source_type`, `source_id`, `raw_text`, and `urgency_signals`
5. Dedup works correctly for each adapter (unique `source_id` per item, modifications detected where applicable)
6. Scheduler polls all configured adapters on schedule
7. `CompositeEnricher` routes to the correct enricher by source type
8. Each enricher returns useful context using the shared connection
9. All new adapters and enrichers work end-to-end: poll → enqueue → extract → filter → enrich → triage card

### Track B
10. Triage cards include entity knowledge, relationships, and preference context from memory
11. Card body explains *why* the item matters based on memory
12. Options are dynamic with suggested markers based on learned patterns
13. Fallback to template when memory is unavailable (no degraded middle ground)
14. `format_card_for_chat()` renders both LLM-generated and template-generated cards correctly
15. No regression in card rendering for existing GitHub/Phabricator sources

### Both
16. `connections:` config section is parsed, validated, and connections are initialized at startup
17. Config version is bumped to `0.2.0`
18. All existing tests pass (no regressions)

## Out of Scope

- Automatic OAuth setup wizard (manual token setup via `workbench init` instructions)
- Rate limiting per source adapter (rely on poll interval config)
- Multi-account support for Google adapters (single account per adapter)
- Real-time/webhook ingestion (poll-based only)
- Meta-specific overrides of Google adapters (MetaGmailAdapter, etc.) — deferred until needed
- Enricher depth/budget tuning per source type (use global enrichment config)
- Card template customization per source type (LLM generates source-appropriate cards)

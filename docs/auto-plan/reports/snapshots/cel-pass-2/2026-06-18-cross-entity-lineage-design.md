# Cross-Entity Lineage — Design Spec

## Context

The shipped item-lineage feature (ADR 0062) gives every `Item` a stable materialized `path` (`#123`, `#123.1.2`) backed by migration 014. This feature extends that lineage outward: every OTHER entity the system creates — LLM calls, interactions, plans, triage cards, and a new durable message record — links back to the exact item path(s) it consumed, at true depth. The mechanism is a single generic bidirectional join table (`entity_item_links`), so "what touched this item?" and "what did this entity consume?" become one indexed query each, with no pollution of the item tree.

## Goals

1. **Uniform** — a single generic `entity_item_links` join table is the one bidirectional, many-to-many linkage mechanism for all entity types; the item tree is never used to carry cross-entity edges.
2. **True-depth** — every entity links to EXACTLY the item path(s) it consumed at the real depth (extraction→root `#123`; relevance scoring→the depth-1 children `#123.1..n`; action handling→that action `#123.1.1`; urgency→the root(s) scored).
3. **Async-safe** — entities whose consumed items are minted AFTER the LLM call (batched relevance, batched urgency) link via a client-generated `correlation_id` instead of an entity id that does not yet exist.
4. **Correct** — fix the three latent lineage bugs found while grilling (empty `item_paths` on extraction and simple-site scoring; unstamped `generate_card`; mis-stamped batched-scoring root link).
5. **Durable-messages** — introduce a persisted `messages` entity so every outbound/inbound message (card sends, alerts, briefings, re-triage pings, replies) is a first-class, linkable record rather than an ephemeral render.
6. **Extensible** — a future entity becomes linkable by adding one `entity_type` value and one `record(...)` call at its creation site; no schema change.
7. **Surfaceable** — a `GET /api/items/{path}/related` endpoint and an `ItemPage` "What touched this" section expose the reverse lineage to the operator.
8. **Non-dangling** — entity-side retention pruners call `unlink_entity` so links never dangle (entity side has no DB FK); the item side uses `ON DELETE CASCADE`.

## Architecture

```
                       call-time path                         post-persist path
  (consumed paths known at call site)            (consumed items minted AFTER the call)
  ┌──────────────────────────────┐               ┌─────────────────────────────────────┐
  │ llm_call_context(             │               │ llm_call_context(                    │
  │   item_paths=(p1,p2,...))     │               │   correlation_id="uuid")             │
  └──────────────┬───────────────┘               └──────────────────┬──────────────────┘
                 │ ambient contextvar                                │ ambient contextvar
                 ▼                                                   ▼
        plugboard sink ──► PlugboardCallRecord(context)     plugboard sink ──► record(corr_id)
                 │                                                   │
                 ▼ async drain (runtime/app.py)            llm_calls row gets correlation_id col
        save_many(records):                                         │
          INSERT llm_calls (RETURNING id)            ... children/roots allocated later ...
          + entity_links.record(                              │
              "llm_call", id, items)                          ▼
                 │                                  entity_links.record_by_correlation(
                 ▼                                    entity_type, corr_id, item_paths)
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │                          entity_item_links (join)                             │
        │  id · entity_type · entity_id? · item_id → items(id) · item_path · corr_id?   │
        └───────────────────────────────┬─────────────────────────────────────────────┘
                                         │ for_item(path, subtree?)
                                         ▼
        GET /api/items/{path}/related  ──►  UNION(entity_item_links join, 3 FK tables)
                                         ──►  ItemPage "What touched this"  (useItemRelated)
```

Two recording paths feed one table. The **call-time** path is taken when the consumed item paths are known at the call site (extraction, triage `generate_card`, free-text interpret, re-triage): the caller stamps `LLMCallContext.item_paths`, and the writer derives both `LlmCallRecord.items` and the `entity_item_links` rows inside `save_many` after the `llm_calls` id is assigned. The **post-persist** path is taken when consumed items are born after the call returns (batched/non-batched relevance scoring, batched urgency): the caller stamps a client-generated `correlation_id`, the call persists with that `correlation_id` column, and once the children/roots are allocated the creation site calls `record_by_correlation` to write the link rows (entity_id resolved from `llm_calls.correlation_id`, or joined at query time).

## Design Section 1 — `entity_item_links` table and migration 015

The single source of truth for cross-entity edges. Surrogate PK so the same `(entity_type, entity_id)` can link to many items and the same item to many entities. `entity_id` is nullable to support correlation-id linkage written before the async record id exists; such rows are reconciled (or joined) via `correlation_id`. Both `item_id` (FK, cascade) and `item_path` (stable, depth-aware) are stored: `item_id` gives referential integrity and `ON DELETE CASCADE`; `item_path` gives indexed subtree scans without a recursive join.

```sql
-- migration 015_entity_item_links  (down_revision = "014")
CREATE TABLE entity_item_links (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type   TEXT        NOT NULL,
    entity_id     BIGINT      NULL,          -- nullable: correlation-id rows precede the id
    item_id       BIGINT      NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    item_path     TEXT        NOT NULL,
    correlation_id TEXT       NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotency for id-known rows. A partial unique handles the duplicate-suppression
-- contract while entity_id is NULL (correlation rows are deduped on the corr tuple).
CREATE UNIQUE INDEX uq_eil_entity_item
    ON entity_item_links (entity_type, entity_id, item_path)
    WHERE entity_id IS NOT NULL;
CREATE UNIQUE INDEX uq_eil_corr_item
    ON entity_item_links (entity_type, correlation_id, item_path)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX idx_eil_entity     ON entity_item_links (entity_type, entity_id);
CREATE INDEX idx_eil_path       ON entity_item_links (item_path text_pattern_ops);
CREATE INDEX idx_eil_item       ON entity_item_links (item_id);
CREATE INDEX idx_eil_corr       ON entity_item_links (correlation_id);

-- correlation_id added to llm_calls so the post-persist path can resolve entity_id.
ALTER TABLE llm_calls ADD COLUMN correlation_id TEXT NULL;
CREATE INDEX idx_llm_calls_correlation_id ON llm_calls (correlation_id);
```

`down_revision` is the string `"014"` (verified: latest file is `014_item_lineage.py`, so the new file is `015_entity_item_links.py`). The subtree predicate used by `for_item(path, subtree=True)` is `item_path = $1 OR item_path LIKE $1 || '.%'`, served by `idx_eil_path` (text_pattern_ops). A call/entity that consumed no items writes zero rows — the table is sparse.

### entity_type vocabulary

`entity_type` is TEXT (singular, lowercase, snake_case). Extensible: a new entity adds one value.

| `entity_type` | Source record | Detail view exists? |
|---------------|---------------|---------------------|
| `llm_call`    | `llm_calls` row | yes (`/api/llm/{id}`) |
| `interaction` | `InteractionEntry` | yes |
| `plan`        | `Plan` | non-link (no view yet) |
| `triage_card` | `TriageCard` | non-link |
| `message`     | new `messages` row | yes |

## Design Section 2 — `EntityLinkStore` ABC and `PgEntityLinkStore`

A new store abstraction (`storage/base.py`) wired as `stores.entity_links`, with a Postgres implementation. It is the only writer/reader of `entity_item_links`. `record` is an idempotent upsert that resolves `item_path → item_id` in the database (so the caller passes only paths) using an `INSERT ... SELECT` against `items`, deduped with `ON CONFLICT DO NOTHING`.

```python
class EntityLinkStore(ABC):
    @abstractmethod
    async def record(
        self, entity_type: str, entity_id: int, item_paths: list[str]
    ) -> None:
        """Idempotent upsert. Resolves each path to its item_id in-DB:
           INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path)
             SELECT $1, $2, i.id, i.path FROM items i WHERE i.path = ANY($3)
           ON CONFLICT DO NOTHING.
           Empty item_paths is a no-op."""
        ...

    @abstractmethod
    async def record_by_correlation(
        self, entity_type: str, correlation_id: str, item_paths: list[str]
    ) -> None:
        """Post-persist path. Same in-DB path->id resolve, but entity_id is left
           NULL and correlation_id is stamped. The reverse query resolves entity_id
           by joining llm_calls.correlation_id (or a reconciler backfills it)."""
        ...

    @abstractmethod
    async def unlink_entity(self, entity_type: str, entity_id: int) -> int:
        """Delete all link rows for one entity (retention cascade). Returns count."""
        ...

    @abstractmethod
    async def for_item(
        self, path: str, *, subtree: bool = False
    ) -> list[EntityLink]:
        """All links touching `path` (and descendants when subtree=True)."""
        ...

    @abstractmethod
    async def for_entity(
        self, entity_type: str, entity_id: int
    ) -> list[EntityLink]:
        """All item links an entity consumed."""
        ...
```

`record` resolves paths to ids in a single round trip, so a path that does not (yet) exist is silently skipped (it produces no row) rather than erroring — consistent with the sparse-table contract. `record_by_correlation` is used only by the post-persist callers; its rows carry `entity_id = NULL` and are resolved to a concrete `llm_call` id at query time by joining `llm_calls ON llm_calls.correlation_id = entity_item_links.correlation_id`.

`stores.entity_links` is added to the `Stores` container (optional kwarg, like `llm_calls`) and constructed in `storage/postgres/stores.py`.

## Design Section 3 — call-time recording inside `save_many`

`LlmCallRecord` keeps its `items: list[str]` field as a denormalized read-convenience (the LLM-call detail view reads it directly). `entity_item_links` is the source of truth for cross-entity queries. Both are written from the SAME `item_paths` snapshot so they never diverge.

The plugboard sink (`runtime/app.py::_plugboard_record_to_llm_call`) already copies `rec.context.item_paths` into `LlmCallRecord.items`. It additionally copies `rec.context.correlation_id` into a new `LlmCallRecord.correlation_id` field. `PgLlmCallStore.save_many` is changed from a fire-and-forget `executemany` to an `INSERT ... RETURNING id` loop (or a single multi-row `INSERT ... RETURNING`) so each persisted row's id is known, then:

```python
async def save_many(self, records: list[LlmCallRecord], *, entity_links) -> None:
    # INSERT ... RETURNING id, then for each record with items:
    #   await entity_links.record("llm_call", new_id, rec.items)
    # The correlation_id column is persisted on the llm_calls row regardless;
    # post-persist link rows for that call are written later by the caller.
```

`save_many` writes link rows ONLY for records that carry `items` (the call-time path). Records that instead carry a `correlation_id` (post-persist path) persist the `llm_calls.correlation_id` column and write NO link rows here — those rows arrive via `record_by_correlation` once the items exist. The drain loop (`_drain_once`) passes `stores.entity_links` into `save_many`.

## Design Section 4 — call-site stamping and the three bug fixes

This section enumerates every LLM call site and how it links, including the three latent bugs.

| Call site (file) | Consumed items | Path | What changes |
|------------------|----------------|------|--------------|
| `extraction.py::extract_items` | the root `#123` | call-time | **BUG FIX:** wrapper exists but stamps NO `item_paths`, so it persists empty `items`. Thread the root path in and stamp `item_paths=(root.path,)`. |
| `engine.py` batched `score_relevance_many` | the depth-1 children `#123.1..n` | post-persist | **BUG FIX:** currently mis-stamps `item_paths=(root.path,)`. Replace with `correlation_id=<uuid>`; after children are allocated in `_process_extracted_item`, call `record_by_correlation("llm_call", uuid, child_paths)`. |
| `filter.py::score_and_decide` (non-batched `score_relevance`) | that one child path | post-persist | **BUG FIX:** wrapper exists but stamps NO `item_paths` (the child is born after the call). Stamp `correlation_id=<uuid>`; after `allocate_child`, call `record_by_correlation("llm_call", uuid, (child.path,))`. |
| `triage.py::generate_card` | the card's item path | call-time | **BUG FIX:** stamps no `item_paths` though the path is available at the caller (`scheduler` sets `new_card.item_id = item.id`). Thread `item.path` to `generate_card` and stamp `item_paths=(path,)`; also `record("triage_card", card.id, (path,))` after `save_card`. |
| `engine.py::enqueue` per-item `score_urgency` | the root being enqueued | call-time | Root path is known at enqueue; stamp `item_paths=(root.path,)`. |
| `scheduler.py::_enqueue_with_urgency` batched `score_urgency_many` | the roots scored | post-persist | Roots are born inside `enqueue` AFTER the batched call. Stamp `correlation_id=<uuid>`; plumb each root path out of `enqueue` (see §5) and call `record_by_correlation("llm_call", uuid, root_paths)`. |
| `scheduler.py` free-text `interpret_triage_response` (both sites, lines ~638 and ~687) | the card's item path | call-time | Stamp `item_paths=(card_item_path,)`; the card carries `item_id` → resolve path. The resulting `InteractionEntry` also calls `record("interaction", entry.id, (path,))` at its creation site. |
| re-triage `generate_card` (scheduler line ~499) | the item path being re-triaged | call-time | Same as `generate_card` above (`item.path` is in scope). |

**Note on "NO wrapper":** the decision log says `extract_items` and `score_and_decide` "have NO `llm_call_context` wrapper". The code actually HAS the wrapper but passes NO `item_paths` (so it persists empty `items`). Reconciled in favor of the code: the fix is to add `item_paths` (extraction, call-time) / `correlation_id` (scoring, post-persist) to the EXISTING wrappers, not to add wrappers. The observable defect (empty/missing links) and the fix surface are identical.

`LLMCallContext` gains a `correlation_id: str | None = None` field and the `llm_call_context(...)` helper gains a matching keyword. A call site uses EITHER `item_paths` (call-time) OR `correlation_id` (post-persist), never both.

## Design Section 5 — urgency lineage plumbing

The batched urgency call (`score_urgency_many`) happens in `_enqueue_with_urgency` BEFORE the per-item `enqueue` calls that birth the roots, so the roots do not exist when the batched call is recorded. `enqueue` currently returns a `PipelineJob` and does not surface the root it created.

Change `enqueue` to additionally surface the root path it minted (e.g. return `tuple[PipelineJob, str | None]`, or set a `root_path` on the returned job — the spec picks returning the root path alongside the job). `_enqueue_with_urgency` collects the root paths for the signalled subset that shared one batched call, then calls `record_by_correlation("llm_call", uuid, root_paths)` once after the loop. The `correlation_id` is generated in `_enqueue_with_urgency` and stamped on the `score_urgency_many` context; it flows to the `llm_calls` row via the sink, so the link rows resolve to that call.

## Design Section 6 — durable `messages` entity (NEW)

Messages are currently ephemeral: `CardMessage` (`domain/triage.py`) is a render of a `TriageCard`, and `messenger.send_card(...)` returns only a transport id. To make a message linkable, add a persisted record per sent/received message and link it to the item(s) it concerns.

```python
# domain/messages.py
class Message(BaseModel):
    id: int | None = None
    kind: Literal["card", "alert", "briefing", "retriage", "reply"]
    direction: Literal["outbound", "inbound"]
    bot_message_id: str | None = None      # transport id from the messenger
    body: str | None = None                # rendered text (outbound) / raw (inbound)
    summary: str | None = None             # short label for the related list
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```sql
-- part of migration 015 (same revision)
CREATE TABLE messages (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,
    direction     TEXT NOT NULL,
    bot_message_id TEXT NULL,
    body          TEXT NULL,
    summary       TEXT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

A new `MessageStore` ABC + `PgMessageStore` (`save`, `get_by_id`, `list_recent`, `delete_older_than`) is wired as `stores.messages`. At every send site — `scheduler.send_card` for queued cards (line ~705), alert sends, briefing sends, re-triage pings, and inbound reply capture — the code persists a `Message` and calls `record("message", msg.id, item_paths)` with the path(s) the message concerns (the card/item in scope). Messages link call-time (the item paths are always known at the send site).

## Design Section 7 — existing FK entities stay; reverse lookup UNIONs them

Three entities already carry a depth-0 single-item FK and are NOT migrated into the join table: `TriageCard.item_id`, `EnrichmentTrace.item_id`, `FeedbackCorrection.item_id`. They keep their columns. The reverse-lookup endpoint surfaces them by UNIONing them in alongside `entity_item_links`, so the operator sees a complete picture without a data migration. (`triage_card` therefore appears in `related` results both via its FK and, for the card's generating LLM call, via the join — these are different entity rows and both are correct.)

## Design Section 8 — surfacing API `GET /api/items/{path}/related`

```
GET /api/items/{path}/related?subtree=false&cursor=<opaque>
```

Returns entities that touched `path` (and descendants when `subtree=true`), grouped by `entity_type`. The result is the UNION of (a) `entity_item_links` joined to its entity tables and (b) the three FK tables (`triage_card`, `enrichment_trace`, `feedback_correction`) filtered by item path. Per-type cap ~50 with an optional opaque cursor for paging within a type.

```jsonc
{
  "path": "123.1",
  "subtree": false,
  "counts": { "llm_call": 7, "interaction": 1, "message": 2, "triage_card": 1 },
  "groups": {
    "llm_call":    [ { "entity_type": "llm_call", "id": 991, "label": "score_relevance · ok", "at": "2026-06-18T15:02:11Z", "href": "/llm/991" } ],
    "interaction": [ { "entity_type": "interaction", "id": 12, "label": "chose: snooze", "at": "...", "href": "/interactions/12" } ],
    "message":     [ { "entity_type": "message", "id": 30, "label": "card · outbound", "at": "...", "href": "/messages/30" } ],
    "triage_card": [ { "entity_type": "triage_card", "id": 5, "label": "card #5", "at": "...", "href": null } ]
  }
}
```

Each entry is `{entity_type, id, label, at, href|null}`. `href` is null for types with no detail view (`triage_card`, `plan`). For post-persist `llm_call` rows whose `entity_id` is NULL, the endpoint resolves the id by joining `llm_calls ON correlation_id`.

## Design Section 9 — UI "What touched this"

A new section on `ItemPage.tsx` (`/home/anshulverma/workspace/workbench/ui/src/pages/ItemPage.tsx`) rendered below the existing Children section, backed by a new `useItemRelated(path)` hook in `useItems.ts` hitting `/api/items/{path}/related`. Rows are grouped by `entity_type` with per-group counts. Rows with an `href` (`llm_call`, `interaction`, `message`) render as `<Link>`; rows without (`triage_card`, `plan`) render as plain text. Default `subtree=false`; an "include descendants" toggle re-fetches with `subtree=true`. The hook mirrors the existing `useItem` shape (react-query, `enabled: !!path`).

## Design Section 10 — retention cascade and edge cases

The item side of `entity_item_links` is protected by `ON DELETE CASCADE`. The entity side has NO DB FK (entity tables are heterogeneous), so the cascade is code-owned: every entity pruner calls `unlink_entity(entity_type, entity_id)` (or a bulk variant) before/with deleting the entity. Affected pruners: `PgLlmCallStore.delete_older_than` and `prune_to_max_rows` (entity_type `llm_call`), and `PgMessageStore.delete_older_than` (entity_type `message`).

Edge cases (all from the resolved decision log):

- **Dropped children** are still linked by the scoring call — they WERE scored even though routed to `DROPPED`.
- **Failed simple-site call** still links its consumed items (the link is from `item_paths`/`correlation_id`, independent of call success; the `llm_calls` row is persisted with `status="error"`).
- **Zero-item call/entity** writes zero link rows (sparse table; `record([])` is a no-op).
- **Duplicate links** are idempotent via `ON CONFLICT DO NOTHING` on the partial unique indexes.

## File Changes

### New files

| File | Component | Purpose |
|------|-----------|---------|
| `src/workbench/migrations/versions/015_entity_item_links.py` | Schema | `entity_item_links` + `messages` tables, indexes, `llm_calls.correlation_id` column; `down_revision = "014"`. |
| `src/workbench/domain/messages.py` | Domain | `Message` pydantic model. |
| `src/workbench/storage/postgres/entity_links.py` | Storage | `PgEntityLinkStore`. |
| `src/workbench/storage/postgres/messages.py` | Storage | `PgMessageStore`. |
| `ui/src/hooks/useItemRelated` (in `ui/src/hooks/useItems.ts`) | UI | react-query hook for `/related`. |

### Modified files

| File | Component | Change |
|------|-----------|--------|
| `src/workbench/providers/llm/context.py` | Provenance | Add `correlation_id: str | None = None` to `LLMCallContext` + the `llm_call_context(...)` helper. |
| `src/workbench/providers/llm/plugboard.py` | Provenance | `PlugboardCallRecord` already carries `context`; no change unless surfacing `correlation_id` separately (it rides on `context`). |
| `src/workbench/domain/llm_calls.py` | Domain | Add `correlation_id: str | None = None` to `LlmCallRecord`. |
| `src/workbench/runtime/app.py` | Wiring | Sink copies `context.correlation_id` to the record; `_drain_once` passes `stores.entity_links` into `save_many`. |
| `src/workbench/storage/base.py` | Storage | Add `EntityLinkStore`, `MessageStore` ABCs + `EntityLink` dataclass; add `entity_links`, `messages` to `Stores`; `LlmCallStore.save_many` signature gains `entity_links`. |
| `src/workbench/storage/postgres/llm_calls.py` | Storage | `save_many` → `INSERT ... RETURNING id` + `record("llm_call", id, items)`; persist `correlation_id`; pruners call `unlink_entity`. |
| `src/workbench/storage/postgres/stores.py` | Wiring | Construct `entity_links`, `messages`. |
| `src/workbench/pipeline/extraction.py` | Pipeline | Thread root path; stamp `item_paths=(root.path,)`. |
| `src/workbench/pipeline/filter.py` | Pipeline | Stamp `correlation_id` on `score_relevance`; caller records by correlation after child allocation. |
| `src/workbench/pipeline/engine.py` | Pipeline | Pass root path to `extract_items`; replace batched-scoring `(root.path,)` with `correlation_id` + `record_by_correlation` post-allocation; per-item urgency stamps `item_paths=(root.path,)`; `enqueue` surfaces the root path. |
| `src/workbench/pipeline/triage.py` | Pipeline | `generate_card` takes the item path; stamps `item_paths`; caller records `triage_card` link. |
| `src/workbench/pipeline/scheduler.py` | Pipeline | Batched urgency uses `correlation_id` + `record_by_correlation` with surfaced root paths; interpret sites stamp `item_paths` + record `interaction`; send sites persist `Message` + record `message`. |
| `src/workbench/api/items.py` | API | Add `GET /api/items/{path}/related`. |
| `ui/src/pages/ItemPage.tsx` | UI | Add "What touched this" section + subtree toggle. |

## Verification

1. **Schema migrates** — `alembic upgrade head` from 014 creates `entity_item_links`, `messages`, `llm_calls.correlation_id` and all six `entity_item_links` indexes; `downgrade` drops them cleanly.
2. **Idempotent record** — calling `record("llm_call", 1, ["123"])` twice yields exactly one row (`ON CONFLICT DO NOTHING`).
3. **Path resolution** — `record("llm_call", 1, ["123","123.1"])` writes rows whose `item_id` matches `items.id` for those paths; an unknown path writes no row.
4. **Extraction links root** — running extraction for a raw item with root `#123` produces a `llm_call` link row with `item_path = "123"` (regression for the empty-`items` bug).
5. **Batched scoring links children** — a batched relevance call over children `#123.1..3` produces three `llm_call` link rows at `item_path` `123.1`,`123.2`,`123.3` (NOT `123`) resolved via `correlation_id` (regression for the mis-stamped-root bug).
6. **Simple-site scoring links child** — non-batched `score_and_decide` for child `#123.1` produces one link row at `123.1` (regression for the empty-`items` bug).
7. **generate_card links card item** — `generate_card` produces both a `llm_call` link and a `triage_card` link at the card's item path (regression for the unstamped bug).
8. **Batched urgency links roots** — a batched `score_urgency_many` over roots `#123`,`#124` produces two `llm_call` link rows at `123`,`124` via `correlation_id`.
9. **Message persisted + linked** — `scheduler.send_card` for a queued card writes a `messages` row and a `message` link at the card's item path.
10. **Reverse lookup UNIONs FK tables** — `GET /api/items/123/related` returns the `triage_card`/`enrichment_trace`/`feedback_correction` rows whose `item_id` is `#123` AND the `entity_item_links` rows.
11. **Subtree query** — `GET /api/items/123/related?subtree=true` includes links at `123.1` and `123.1.1`; `subtree=false` does not.
12. **Retention cascade** — `delete_older_than` on `llm_calls` removes the matching `entity_item_links` rows (via `unlink_entity`); deleting an item removes its link rows (via `ON DELETE CASCADE`).
13. **Failed call still links** — a `score_relevance` raising an error persists a `status="error"` `llm_calls` row AND its link rows.
14. **Zero-item no-op** — a context with neither `item_paths` nor `correlation_id` writes no link rows.
15. **UI renders related** — `ItemPage` shows the "What touched this" section grouped by type, links the linkable types, and the "include descendants" toggle re-fetches with `subtree=true`.

## Resolved Questions

1. **Linkage mechanism:** → A single generic `entity_item_links` join table — uniform, bidirectional, many-to-many. Rationale: one indexed table answers both directions and keeps cross-entity edges out of the item tree (no path/tree pollution). (§1)
2. **Table schema & keys:** → Surrogate `id BIGINT IDENTITY` PK; `entity_type TEXT`; `entity_id BIGINT NULL`; `item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE`; `item_path TEXT NOT NULL`; `correlation_id TEXT NULL`; `created_at`. Partial unique on `(entity_type, entity_id, item_path)` and on `(entity_type, correlation_id, item_path)`; indexes on `(entity_type, entity_id)`, `item_path text_pattern_ops`, `item_id`, `correlation_id`. Rationale: nullable `entity_id` supports correlation-first writes; storing both `item_id` and `item_path` gives cascade integrity AND depth-aware subtree scans. (§1)
3. **entity_type values:** → `llm_call`, `interaction`, `plan`, `triage_card`, `message` (TEXT, singular lowercase snake). Rationale: extensible — a future entity adds a value, no schema change. (§1)
4. **Linkage principle:** → An entity links to EXACTLY the items it consumed at true depth (extraction→root; relevance→scored children; action handling→that action; urgency→scored roots). Rationale: lineage must reflect actual consumption, not a coarse root proxy. (§2, §4)
5. **Two recording paths:** → call-time (`item_paths` stamped, links derived in `save_many` after id assignment) and post-persist (`correlation_id` stamped, links written by `record_by_correlation` once items exist; `llm_calls.correlation_id` added). Rationale: some consumed items are minted AFTER the call returns, so no entity id exists yet to link against. (§3, §4, §5)
6. **Latent bug fixes:** → `extract_items` stamps `item_paths=(root.path,)`; `score_and_decide` stamps `correlation_id`; `generate_card` stamps `item_paths`; batched scoring replaces the mis-stamped `(root.path,)` with `correlation_id` child links. Rationale: the current code persists empty/wrong `items` at these sites. (§4 — see reconciliation note: the wrappers exist but lack `item_paths`; we fix the existing wrappers rather than add new ones.)
7. **Urgency lineage:** → Plumb the root path(s) out of `enqueue` so `_enqueue_with_urgency` can `record_by_correlation` the batched `score_urgency_many` against the roots it scored. Rationale: roots are born inside `enqueue`, after the batched call, so correlation-id is required. (§5)
8. **Durable message entity:** → New `messages` table + `Message` domain model + `MessageStore`, persisted at every send/receive site and linked via `entity_type = "message"`. Columns: id, kind, direction, bot_message_id?, body, summary, created_at. Rationale: messages were ephemeral renders of cards and thus unlinkable. (§6)
9. **Keep `LlmCallRecord.items`:** → Kept as a denormalized read-convenience; `entity_item_links` is the source of truth; `save_many` writes both from one snapshot. Rationale: the LLM-call detail view reads `items` directly; one snapshot keeps them consistent. (§3)
10. **Existing FK entities:** → `TriageCard.item_id`, `EnrichmentTrace.item_id`, `FeedbackCorrection.item_id` keep their columns; not migrated; the reverse endpoint UNIONs them in. Rationale: avoid a data migration; depth-0 single-item FKs already work. (§7, §8)
11. **Shared helper / extensibility:** → `EntityLinkStore` ABC + `PgEntityLinkStore` wired as `stores.entity_links` with `record` / `record_by_correlation` / `unlink_entity` / `for_item` / `for_entity`; `record` resolves path→id in-DB via `INSERT...SELECT ... WHERE path = ANY($paths) ON CONFLICT DO NOTHING`. Rationale: a future entity becomes linkable with one `record(...)` call. (§2)
12. **Retention cascade:** → Entity pruners call `unlink_entity` (code-owned cascade); the item side uses `ON DELETE CASCADE`. Rationale: the entity side has no DB FK across heterogeneous tables. (§10)
13. **Surfacing API:** → `GET /api/items/{path}/related?subtree=false` returns entities grouped by type (UNION of join + 3 FK tables) with `counts`, a per-type cap ~50, and an optional cursor; each entry `{entity_type, id, label, at, href|null}`. Rationale: one endpoint answers "what touched this" across all entity types. (§8)
14. **UI:** → A "What touched this" section on `ItemPage.tsx` backed by `useItemRelated(path)`; linkable types render as links, others as text; default `subtree=false` with an "include descendants" toggle. Rationale: expose reverse lineage to the operator where they already inspect an item. (§9)
15. **No backfill:** → Start fresh; historical `llm_calls.items` already carries paths and can be read directly or copied later. Rationale: backfill is low-value and risky relative to forward correctness. (Out of Scope)
16. **Edge cases:** → Dropped children still linked (they were scored); failed simple-site calls still link consumed items; zero-item calls write zero rows; duplicates are idempotent. Rationale: lineage reflects consumption, not outcome; the table is intentionally sparse and dedup-safe. (§10)

## Out of Scope

- Implementation plan (a separate pass).
- Migrating the three existing FK entities (`TriageCard`, `EnrichmentTrace`, `FeedbackCorrection`) into the join table.
- Backfilling historical links (start fresh; `llm_calls.items` already carries paths).
- Wiring Plans end-to-end — `Plan` creation has no caller/API yet, so plan linkage is a one-line `record("plan", plan.id, item_paths)` stub at the future creation site.

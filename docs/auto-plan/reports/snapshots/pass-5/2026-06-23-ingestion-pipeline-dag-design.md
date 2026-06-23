# Ingestion Pipeline DAG & Configurable Stages — Design Spec

## Context

Today Workbench's ingestion pipeline executes a **hardcoded** sequence in
`pipeline/engine.py`: `enqueue` (dedup gate → root item → LLM urgency score → queue),
then `process_raw_item` (extract → optional batch relevance pre-pass → per-item LLM
relevance score → threshold decision → enrich only on the triage branch → card). Filter
rules are **advisory only** — every `FilterRule` is rendered into the LLM scoring prompt as
a hint (`"- {pattern} → {action}"`) and nothing is applied deterministically. The UI has a
`funnel_order` table and `enrichers`/`filter_rules` tables with `order_index`, plus funnel
cards, but **none of it drives execution** — reordering is cosmetic, enrichers are
read-only, and there is no way to express deterministic if-then-else filtering or to filter
before the first LLM call.

This work makes the pipeline a **user-authored, DB-authoritative Routing DAG of typed
stages** that the engine actually executes, adds **deterministic rule-based filtering**
(nested boolean trees) including a **pre-extraction segment** that gates before any LLM
cost, makes **enrichers fully configurable with hot-apply**, and surfaces the whole thing
as a **visual DAG diagram + builder** sub-tab on the Ingestion page.

## Goals

1. **Executable pipeline graph** — a Routing DAG of typed stages stored in the DB drives
   ingestion; the authored graph is the execution order, not a cosmetic display.
2. **Deterministic rule filtering** — author if-then-else rules as nested AND/OR/NOT
   boolean trees that gate items deterministically, alongside (not replacing) the existing
   advisory LLM filter.
3. **Pre-extraction filtering** — drop items before the first LLM call (urgency scoring),
   using only data available pre-extraction.
4. **Per-modality extensibility** — each source adapter declares its filterable fields;
   the rule builder adapts automatically when a new modality is added.
5. **Configurable enrichers** — add/remove/toggle/reorder enrichers and set depth + budget
   from the UI, applied without a restart (hot-apply); enrichers become DB-authoritative.
6. **Routing by source type and state** — a diff and a task take different paths through
   the graph, can converge on a shared node, and diverge again, with single-path
   per-item execution.
7. **Visual pipeline** — a DAG diagram + builder on the Ingestion page that both
   visualizes live per-node funnel counts and edits the graph.
8. **Zero-behavior-change migration** — existing rules/enrichers/order migrate into a
   default graph that reproduces today's exact pipeline behavior (including triage-only
   enrichment, per-source-type depth, and the auto-include / auto-drop / triage branches).

## Glossary (CONTEXT.md)

- **Stage** — one processing unit in the pipeline with a typed behavior. Stage types:
  `pre_filter`, `rule_filter`, `llm_filter`, `enricher`, `loopback`. `loopback` is
  **defined for forward-compatibility but rejected by validation in v1** (not seeded, not
  offered in the builder, never walked by the executor). _Avoid_: "step", "processor",
  "filter" (when meaning a stage generally).
- **Node** — a vertex in the pipeline DAG. Carries one stage (or a reserved special role:
  `source`, `extraction`, or a sink). _Avoid_: "box", "block".
- **Edge** — a directed connection between two nodes carrying a **route predicate**.
  _Avoid_: "link", "arrow", "connection".
- **Route predicate** — the condition on an edge that decides whether an item traverses
  that edge. Default predicate is `always`. Same shape as a rule condition tree.
  _Avoid_: "guard", "filter", "rule" (for edges).
- **Sink** — a terminal node representing a pipeline outcome: `drop`, `auto_include`, or
  `triage`. Every path ends in exactly one sink. _Avoid_: "end", "leaf".
- **Articulation node** — the single mandatory `extraction` node that every path must
  cross; it separates the pre-extraction segment from the post-extraction segment.
- **Pre-extraction segment** — the set of nodes reachable before the `extraction` node.
  Only `pre_filter` stages (and `source`) may appear here. _Avoid_: "phase A".
- **Post-extraction segment** — nodes after `extraction`; only `rule_filter`, `llm_filter`,
  and `enricher` may appear here (`loopback` is classified to this segment but rejected by
  validation in v1, so it never legally appears — see rule 9). _Avoid_: "phase B".
- **Verdict** — a stage's terminal outcome that routes the item to a sink:
  `DROP`, `INCLUDE`, `TRIAGE`, or the non-terminal `CONTINUE`. _Avoid_: "decision",
  "result" (use Verdict).
- **Condition tree** — a nested boolean expression: `Group{op: AND|OR|NOT, children}` or
  `Condition{field, operator, value}`. Used by `rule_filter`/`pre_filter` and by route
  predicates. _Avoid_: "expression", "query", "criteria".
- **Field schema** — an adapter-declared list of `FieldSpec` describing which fields a
  rule may reference for that source type, their types, allowed operators, enum values,
  and segment availability (`pre`/`post`). _Avoid_: "field list", "columns".
- **Stage executor** — the engine component that walks the DAG for one item, selects one
  outgoing edge per node, runs each visited stage, and resolves the final verdict.
  _Avoid_: "runner", "engine" (reserve "engine" for `PipelineEngine`).
- **Composite enricher** — the `CompositeEnricher` that dispatches to a per-`source_type`
  enricher; now built from enricher nodes in the DAG, not YAML. _Avoid_: "enricher chain".
- **Hot-apply** — re-reading the DAG and rebuilding the executor + composite enricher
  under `app.state.reload_lock` without a process restart. _Avoid_: "hot-reload", "live
  reload".
- **Graph snapshot** — the immutable `PipelineGraph` object an item is bound to for the
  whole duration of its walk; `reload_graph()` swaps the engine's active snapshot for
  *new* items only and never mutates a snapshot an in-flight item is using.

## Architecture

The pipeline is a directed acyclic graph of **nodes** connected by **edges**. A single
`source` entry node fans out by `source_type`; every path crosses one mandatory
`extraction` node (the articulation point); every path terminates in one `drop`,
`auto_include`, or `triage` **sink**.

```
                         pre-extraction segment        |  post-extraction segment
                                                        |
                 [type==diff]→ pre:drop-draft ──┐       |
 (source) ──┬────────────────────────────────── ▼      |
            │    [type==task]──────────────→ (extraction) ──┬[type==diff]→ enr:diff-meta → rule:diff-author → llm_filter ─┐
            │                                            │                                                                ▼
            └─ [type==email]→ pre:drop-notif → (extraction)                          ┌──────── llm_filter ──────────→ (triage)
                                                         └[type==task]→ rule:task-prio ┘                          (auto_include)
                                                                                                                       (drop)
```

For one item the **stage executor** starts at `source`, and at each node selects the
single outgoing edge whose route predicate matches (edges are ordered; the last edge may
be a default), runs the destination node's stage, and continues until a stage emits a
terminal **verdict** or the item reaches a **sink**. Execution is **single-path** (one
node at a time, no concurrency) and **deterministic** (exactly one edge selected per node).
The graph is authored, validated, and persisted in `pipeline_nodes` + `pipeline_edges`,
is DB-authoritative, and hot-applies on edit. An item binds to one **graph snapshot** at
the start of its walk and uses it to completion (see Concurrency & reload).

## Design: Pipeline DAG data model

Two tables are the source of truth for execution.

```sql
CREATE TABLE pipeline_nodes (
    id           BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    type         TEXT NOT NULL,              -- source|extraction|sink|pre_filter|
                                             --   rule_filter|llm_filter|enricher|loopback
    role         TEXT,                       -- for type=sink: drop|auto_include|triage;
                                             --   for type=source/extraction: NULL
    label        TEXT NOT NULL,
    source_scope JSONB,                      -- ['diff','task'] or NULL = all source types
    config       JSONB NOT NULL DEFAULT '{}',-- type-specific (see Stage Types)
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    ui_x         INTEGER NOT NULL DEFAULT 0, -- builder layout
    ui_y         INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE pipeline_edges (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    from_node   BIGINT NOT NULL REFERENCES pipeline_nodes(id) ON DELETE CASCADE,
    to_node     BIGINT NOT NULL REFERENCES pipeline_nodes(id) ON DELETE CASCADE,
    predicate   JSONB NOT NULL DEFAULT '{"op":"always"}',  -- condition tree or {"op":"always"}
    order_index INTEGER NOT NULL DEFAULT 0,                -- evaluation order on from_node
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX pipeline_edges_from_idx ON pipeline_edges(from_node, order_index);
```

Reserved nodes (exactly one each, not user-deletable): `source`, `extraction`, and three
sinks `drop`/`auto_include`/`triage`. The five reserved nodes are seeded by the migration
with **IDENTITY-assigned IDs** (captured via `RETURNING` at seed time to wire their seed
edges) and are never deleted or re-created by any write path; the engine and every write
path resolve them by `(type, role)`, so their integer IDs are never hardcoded anywhere
outside the store. `source_scope` is **forbidden on reserved nodes** (`source`, `extraction`, sinks) —
allowing it on `extraction` could let an item bypass the articulation node and violate the
articulation invariant; `validate_graph` rejects a non-null `source_scope` on any reserved
node. `source_scope`, when set on a non-reserved node, means an item whose `source_type` is
not in the list **bypasses** the node — the executor follows the node's own outgoing edges
as if the stage returned `CONTINUE` (the node is skipped, not a dead end). An empty list
`[]` is **rejected** by validation (a never-runnable node is an authoring error — use
`enabled=false` to disable a node). `pre_filter` nodes have `source_scope` enforced; routing
by type is normally expressed on edges, with `source_scope` as a convenience skip.

Domain models (`domain/pipeline.py`):

```python
class PipelineNode(BaseModel):
    id: int | None = None
    type: NodeType                 # enum
    role: SinkRole | None = None   # enum, only for type==sink
    label: str
    source_scope: list[str] | None = None
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    ui_x: int = 0
    ui_y: int = 0

class PipelineEdge(BaseModel):
    id: int | None = None
    from_node: int
    to_node: int
    predicate: ConditionTree       # default {"op": "always"}
    order_index: int = 0

class PipelineGraph(BaseModel):    # immutable in-memory snapshot used by the executor
    nodes: dict[int, PipelineNode]
    out_edges: dict[int, list[PipelineEdge]]  # keyed by from_node, sorted by order_index
    source_id: int
    extraction_id: int
    sinks: dict[SinkRole, int]
```

### Graph validation

`validate_graph(graph)` runs on every save (API 422 on failure) and at load:

1. **Single reserved set** — exactly one `source`, one `extraction`, one of each sink.
2. **Acyclic** — DFS over **all** edges finds no cycle (there is no loopback exclusion;
   loopback nodes are rejected by rule 9, so no back-edges exist in v1).
3. **Extraction is an articulation node** — every path from `source` to any sink crosses
   `extraction`; no sink is reachable from `source` without it.
4. **Segment legality** — only `pre_filter` (and `source`) nodes appear before
   `extraction`; only `rule_filter`/`llm_filter`/`enricher` after.
5. **Reachability** — every non-source node is reachable from `source`; every node can
   reach a sink (no traps).
6. **Determinism** — for any node, the set of outgoing edges either ends in an `always`
   default edge or is exhaustive by construction; if no edge matches at runtime the
   executor falls to the implicit default (see Executor). Validation warns (not errors)
   when a node has no `always`/default outgoing edge.
7. **Field validity** — every `Condition.field` in a node's rule resolves against the field
   schema for that node's source scope, and the field's declared `segment` includes the
   node's segment. For an **edge predicate**, the relevant segment is the **`from_node`'s
   segment** (the predicate is evaluated at `select_next_edge` when leaving `from_node`, so
   only `from_node`-segment fields are in scope): a `post`-only field on a pre-extraction
   edge — and a `pre`-only field on a post-extraction edge — is rejected. A `both` field is
   valid anywhere (see `segment` semantics). Operators are legal for the field type;
   `matches` regexes compile and pass the length cap.
8. **Reserved-node constraints** — reserved nodes carry no `source_scope`, no `config`
   beyond `{}`, the correct `role` (sinks) / `NULL` role (source, extraction), and are
   always `enabled=true`. A disabled reserved node — especially `extraction` — would let the
   executor's `if node.enabled` guard skip `extract_items` and break the articulation
   invariant at runtime, so write paths ignore an incoming `enabled` for reserved nodes and
   validation rejects `enabled=false` on them.
9. **Loopback rejected (v1)** — a graph containing any `loopback` node is rejected (error).
   The type exists for forward-compatibility only.
10. **Enrichment provenance (warning)** — a `rule_filter`/predicate referencing an
    `enrichment.<key>` not produced by any `enricher` upstream on all paths reaching it
    produces a **warning** (never an error); at runtime the missing field evaluates `False`
    per the evaluator's missing-field rule.

If validation fails **at load** (e.g. a corrupted or empty graph on a fresh or
partially-migrated DB), the engine logs the error and **bootstraps the default graph in
memory** (the same shape the migration seeds) so ingestion never starts with no executable
pipeline; the persisted rows are left untouched for the operator to inspect. See Bootstrap.

## Design: Stage types

Each node's `config` shape and behavior by `type`:

| Type | `config` keys | Verdict capability | Segment |
|------|---------------|--------------------|---------|
| `source` | — | routing only | entry |
| `extraction` | — | none (runs `extract_items`) | articulation |
| `pre_filter` | `tree`, `action` (drop only) | DROP / CONTINUE | pre |
| `rule_filter` | `tree`, `action` (drop\|include) | DROP / INCLUDE / CONTINUE | post |
| `llm_filter` | `prompt_overrides?`, `thresholds?` | sets score (no verdict by itself) | post |
| `enricher` | `provider`, `depth`, `budget` | CONTINUE (side-effect) | post |
| `loopback` | — | **rejected in v1** (type reserved for forward-compat) | post |
| `sink` | — | terminal (`role`) | terminal |

- **`pre_filter`** evaluates its `tree` against the **pre-extraction field map**
  (`urgency_signals` + `source_*`). A match with `action=drop` ends the item with verdict
  `DROP` (recorded, not enqueued). Only `drop` is meaningful pre-extraction (there is no
  card to include yet). Runs inside `enqueue` (see Pre-extraction filtering).
- **`rule_filter`** evaluates its `tree` against the **post-extraction field map**
  (extracted fields + accumulated enrichment context + current score). On match, emits the
  configured `action` verdict (`DROP` or `INCLUDE`); otherwise `CONTINUE`.
- **`llm_filter`** runs the existing LLM relevance scoring (`llm.score_relevance`), setting
  `ctx.score`/`ctx.confidence`. It emits no terminal verdict on its own; the final verdict
  falls out of the executor's threshold fallback (see Verdict resolution). `thresholds`
  override the global `include_threshold`/`drop_threshold`/`confidence_threshold` for this
  node; advisory `FilterRule`s continue to feed this stage as prompt context. The existing
  batch-relevance pre-pass (`process_raw_item`'s optional batch `score_relevance` over a
  page of extracted items) is preserved and runs **once, before the per-item walk**, seeding
  `ctx.score`/`ctx.confidence` so a per-item `llm_filter` reuses the batch score instead of
  re-calling the LLM; see Stage executor.
- **`enricher`** invokes the resolved enricher provider via the composite enricher with the
  node's `depth` and `budget`, merging returned context into `ctx.enrichment`. Always
  `CONTINUE`. Enrichers may now appear on **any** post-extraction path, not only the triage
  path; the default migrated graph keeps them on the triage path only to preserve current
  behavior (see Migration & ADR 0070).
- **`loopback`** is **defined for forward-compatibility but not supported in v1**:
  `validate_graph` rejects any graph containing a `loopback` node (rule 9), the migration
  seeds none, the builder does not offer it, and the executor never walks one. Full
  re-processing semantics (and the dedup-gate bypass for re-enqueue) are deferred to a
  future release (see Out of Scope).

## Design: Stage executor

`StageExecutor.run(graph, item_ctx) -> Verdict` (in `pipeline/executor.py`):

```
node = graph.source
visited_guard = 0
while node is not a sink:
    if node.enabled and node applies to item (source_scope):
        result = run_stage(node, item_ctx)     # CONTINUE | DROP | INCLUDE | TRIAGE
        log_funnel_stage(item, node, result)   # per-node trace + counts
        if result is terminal:
            return result
    node = select_next_edge(graph, node, item_ctx)   # first predicate match by order_index;
                                                      #   else implicit default → triage sink fallback
    visited_guard += 1
    if visited_guard > MAX_NODES_PER_ITEM: raise PipelineLoopError   # safety backstop
return sink.role                                # DROP | INCLUDE(auto_include) | TRIAGE
```

`MAX_NODES_PER_ITEM = 256` — a constant in `pipeline/executor.py`. It is a defensive
backstop only; a valid acyclic graph (loopback is rejected in v1, so all graphs are
acyclic) can never approach it. Hitting it raises `PipelineLoopError`, which the caller logs
and treats as a `triage` outcome (fail-safe, never silent drop).

**Verdict resolution (backward-compatible).** A stage's explicit terminal verdict wins
immediately (first-terminal-wins, short-circuit). If the executor reaches the `triage` sink
with no explicit verdict, the **threshold fallback** resolves the outcome by this ordered
3-case rule:
1. If at least one `llm_filter` node actually **executed** on the item's path (enabled and
   in-scope), apply `decide_from_score(score, confidence, thresholds)` using the thresholds
   of the **most-recently-executed** `llm_filter` node (`ctx.last_llm_filter_id`). A
   `llm_filter` skipped via `source_scope` or `enabled=false` does **not** count.
2. Else, if no `llm_filter` executed but the batch-relevance pre-pass seeded a score
   (`ctx.score_source == "batch"`), apply `decide_from_score` using the **global** thresholds
   resolved via `thresholds_for(source_type)` (incl. per-source `SourceRelevanceConfig`).
3. Else (no score at all), the item routes to `triage` as-is — no threshold decision.

`decide_from_score` maps to `auto_include` / `drop` / `triage` exactly as today
(`filter.decide_from_score`). A graph of just `source → extraction → llm_filter → triage`
therefore reproduces today's threshold routing exactly (case 1); the full migrated graph
(with the triage-only enricher) reproduces today's end-to-end behavior (see Migration).

**`item_ctx`** (`ExecutionContext`) carries: the `ExtractedItem` (post-extraction) or
`RawItem` (pre), accumulated `enrichment: dict`, `score`/`confidence`,
`score_source: "batch"|"llm_filter"|None`, `last_llm_filter_id: int|None` (the most-recently
executed `llm_filter` node, for threshold resolution), the resolved `thresholds`, and a
`funnel_log: list[dict]`. The pre-extraction sub-walk (inside
`enqueue`) uses the same executor restricted to the pre segment, operating on a
`RawItem`-backed context.

**Post-extraction integration.** `process_raw_item` calls `extract_items`, then the
optional batch relevance pre-pass (unchanged), then for each `ExtractedItem` builds an
`ExecutionContext` and calls `StageExecutor.run(snapshot, ctx)`. The executor's final
verdict maps to the existing branches: `INCLUDE`→ACTIVE/P2 (auto_include), `DROP`→DROPPED/P3
(auto_drop), `TRIAGE`→PENDING_TRIAGE → (enricher nodes on the triage path already ran during
the walk) → `generate_card` → `triage.save_card`. Card generation and `expires_at` remain in
`process_raw_item` after the verdict, not inside the executor.

**Pre-extraction sub-walk placement.** `enqueue` builds the pre-segment context and walks
`source → … → extraction`. If a `pre_filter` returns `DROP`, `enqueue` records a DROPPED
funnel entry, marks the item processed, and returns a COMPLETED job **without** calling the
urgency scorer or `ingestion_queue.enqueue` — saving the LLM urgency call and queue space.
Reaching `extraction` means "admit to queue": run urgency scoring and enqueue as today.

**Concurrency & reload.** Each item is bound at walk start to the engine's current
`PipelineGraph` **snapshot** and uses it to completion; the pre-walk (in `enqueue`) and the
post-walk (in `process_raw_item`) for the same item may bind to different snapshots (they are
separate operations across the queue boundary) — this is acceptable because each walk is
internally consistent and the segments are independent. `reload_graph()` builds a new
validated snapshot and atomically swaps the engine's reference under `app.state.reload_lock`;
in-flight walks keep their old snapshot, new walks pick up the new one. Snapshots are
immutable, so no walk observes a half-applied edit.

## Design: Rule model & evaluator

A condition tree (`domain/rules.py`):

```python
class Condition(BaseModel):
    field: str            # FieldSpec.key
    operator: Operator    # enum (see below)
    value: Any            # scalar or list, type per FieldSpec

class Group(BaseModel):
    op: Literal["AND", "OR", "NOT"]
    children: list[ConditionTree]   # NOT has exactly one child

ConditionTree = Condition | Group
# Special predicate value {"op": "always"} matches unconditionally (edges only).
```

**Operators** (type-gated by `FieldSpec.type`):

| Field type | Operators |
|------------|-----------|
| `enum`, `string` | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` |
| `string` (extra) | `contains`, `not_contains`, `matches` (regex, anchored, size-limited) |
| `int`, `float` | `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `exists`, `not_exists` |
| `datetime` | `before`, `after`, `within_hours`, `older_than_hours`, `exists` |
| `bool` | `is_true`, `is_false`, `exists` |
| `list` | `contains`, `not_contains`, `len_gt`, `len_lt`, `exists` |

`evaluate(tree, field_map) -> bool` (`pipeline/rule_eval.py`) recursively evaluates against
a flattened `field_map: dict[str, Any]`. Semantics: a missing field makes value-comparisons
`False` (except `not_exists`→`True`, `exists`→`False`); `NOT` negates its single child;
empty `AND`→`True`, empty `OR`→`False`. `matches` compiles the regex once with a length cap
(`MATCHES_MAX_PATTERN_LEN = 512`) and rejects patterns the validator flags as
catastrophic-backtracking-prone; invalid or oversized regex fails validation at save time so
it can never reach the evaluator. Evaluation is pure (no I/O), side-effect free, and
deterministic.

**Field map construction** (`pipeline/field_map.py`):
- Pre segment: `pre_filter_fields(raw_item)` per adapter (defaults to `urgency_signals`),
  plus universal `source_type`/`source_label`/`source_ref`/`source_url`.
- Post segment: extracted fields (`summary`, `category`, `source_context`), universal
  source fields, accumulated `enrichment.*` (dotted keys), and `score`/`confidence`.

## Design: Field schema (per-modality, adapter-declared)

Each `SourceAdapter` declares filterable fields:

```python
class FieldSpec(BaseModel):
    key: str
    label: str
    type: Literal["enum","string","int","float","bool","datetime","list"]
    operators: list[Operator]
    enum_values: list[str] | None = None
    segment: Literal["pre","post","both"]
    description: str | None = None

class SourceAdapter(ABC):
    @classmethod
    def filterable_fields(cls) -> list[FieldSpec]: ...        # default: [] + universal
    @classmethod
    def pre_filter_fields(cls, raw_item: RawItem) -> dict: ... # default: urgency_signals copy
```

Declared per modality (initial set, drawn from existing `urgency_signals` keys):

| Modality | `pre` fields | `post` fields (beyond universal/enrichment) |
|----------|--------------|---------------------------------------------|
| diff | `status`(enum), `author`, `comment_count`(int), `line_count`(int), `file_count`(int), `review_stage`(enum) | `category`(enum) |
| task (meta_tasks) | `priority`(enum), `status`(enum) | `category` |
| email | `sender`, `is_direct`(bool), `cc_count`(int), `thread_depth`(int), `has_attachments`(bool), `labels`(list) | `category` |
| calendar | `is_recurring`(bool), `starts_within_hours`(int), `attendee_count`(int), `organizer` | `category` |
| chat | `space`, `is_direct_message`(bool), `participant_count`(int) | `category` |
| github | `type`(enum: pull_request\|issue) | `category` |
| universal (all) | `source_type`(enum), `source_label`(string), `source_ref`(string), `source_url`(string) | same + `summary`(string), `score`(int), `confidence`(int) |

`source_type` enum values are the live set of registered adapter `adapter_type()` strings
(there is no `SourceType` enum in `domain/enums.py`); the field-schema endpoint enumerates
them from the registry at request time, so adding an adapter extends the routing/`in` value
set automatically. `diff`/`meta_tasks` field declarations live in the workbench-meta repo
adapters (so do their `pre`/`post` rows above), not the base repo.

**`segment` semantics.** A `FieldSpec.segment` of `pre`/`post` makes the field available
only in that segment; `both` makes it available in either (the universal `source_*` fields
are declared `segment: both`, so they can be referenced in pre_filters and post-extraction
rules/predicates alike). The field-schema endpoint includes a `both` field for either
`segment` query value; validation rule 7 accepts a field whose declared `segment` includes
the node's segment; a field's declared operators apply identically in both segments.

`GET /api/pipeline/field-schema?source_type=diff&segment=pre` returns the merged universal
+ adapter `FieldSpec`s available in the requested segment (including `both` fields). The
rule builder renders controls from this; a new modality only needs its adapter to declare
`filterable_fields`.

## Design: Pre-extraction filtering

`pre_filter` nodes live in the pre-extraction segment and run inside `engine.enqueue`,
**before** the urgency scoring LLM call. The pre-segment sub-walk (Stage executor) drops on
match. Recorded outcomes:
- DROP → `funnel_stages` entry `{node, verdict: "drop", segment: "pre"}`, item marked
  processed, NOT enqueued, NO urgency LLM call. The funnel/diagram counts it.
- Reach `extraction` → proceed to urgency scoring + enqueue unchanged.

The pre-walk runs **after** the existing dedup gate (`processed.is_processed`) and root-item
creation, so a re-polled item that is already processed is still short-circuited as today
before any pre_filter runs. For monitoring sources, change detection in `scheduler.py`
(`ChangeDetector.detect`) still gates re-poll re-ingestion upstream of `enqueue`; the
pre-walk therefore sees only first-seen-or-changed raw items, exactly as urgency scoring does
today, and the batch urgency path (`_enqueue_with_urgency`) only runs for items that reach
`extraction`.

Example pre-filters expressible from the schema: drop draft diffs
(`type==diff AND status==draft`); drop notification email
(`type==email AND is_direct==false AND labels contains "notifications"`); drop recurring
calendar events (`type==calendar AND is_recurring==true`).

## Design: Enricher configuration & DB-authoritative composite

- Enricher nodes carry `config = {provider, depth: shallow|deep, budget: {max_api_calls,
  max_seconds}}`; `source_scope` selects which types they apply to.
- **Enricher write authority.** Enrichers are **graph nodes** (`pipeline_nodes` with
  `type='enricher'`). The legacy `enrichers` table is retired as a write target; the
  `PgEnrichersStore`-backed `GET /api/enrichers` and `POST/PATCH/DELETE /api/enrichers`
  endpoints are **compat shims** that read/write the corresponding `pipeline_nodes` rows
  (translating between the old `EnricherConfig` shape and the node `config`). There is one
  authoritative store of enricher state — the graph — and no dual-write.
- **`EnricherConfig.stage` → node depth mapping.** The existing `EnricherConfig.stage`
  (a free label like `context`/`summary`/`risk`) is **not** the same axis as the new
  `depth: shallow|deep`. The migration carries the old `stage` value forward into the node
  `label` (preserving the human name) and sets the node `depth` from the provider's current
  effective depth (`deep` for the `diff`-scoped enricher and `shallow` otherwise — matching
  today's `enrich depth = deep if source_type=="diff" else shallow`). The `EnricherConfig`
  model gains a `depth` field; `stage` is retained for the compat view only.
- **Composite is DB-authoritative**: `create_composite_enricher`
  (`runtime/app.py:201`, currently YAML-driven) reads enricher nodes from the DAG and maps
  `source_type → enricher` plus a default; per-node budgets override the global. If the DAG
  has no enricher node for a `source_type`, the composite falls back to `StubEnricher`
  (today's default), so removing all enricher nodes degrades gracefully rather than erroring.
- **Hot-apply**: `PipelineEngine.reload_graph()` re-reads `pipeline_nodes`/`pipeline_edges`,
  re-validates, rebuilds the executor's `PipelineGraph` and the composite enricher under
  `app.state.reload_lock` (mirrors the existing `set_source_thresholds` hot path). All graph
  edits (nodes, edges, enabled toggles, enricher config) call `reload_graph()`.

## Design: Routing predicates & determinism

- Edge `predicate` is a `ConditionTree` or `{"op": "always"}`. Edges from a node are
  evaluated in `order_index` order; the **first match wins**; an `always` edge acts as the
  default and is conventionally placed last.
- Re-divergence after convergence is supported: a shared node's outgoing edges may
  re-split by `source_type` (always available, immutable) or by accumulated state (`score`,
  `enrichment.*`) that an upstream node produced.
- If no outgoing edge matches at runtime (no default present), the executor routes to the
  `triage` sink and logs a `funnel_stages` warning entry (defensive; validation warns at
  save time).

## Design: API surface

All under `/api`, bearer-auth (except `/health`), `request.app.state.stores`. All write
paths enforce the same bearer auth as existing routers; there is no anonymous access to graph
mutation. All mutations re-validate and `reload_graph()` only after the DB write commits.

| Method & path | Purpose |
|---------------|---------|
| `GET /api/pipeline/graph` | full graph (nodes + edges) for builder + diagram |
| `PUT /api/pipeline/graph` | replace graph atomically; validate → 422 on failure → `reload_graph()` |
| `POST /api/pipeline/nodes` / `PATCH .../{id}` / `DELETE .../{id}` | node CRUD (validate + reload) |
| `POST /api/pipeline/edges` / `PATCH .../{id}` / `DELETE .../{id}` | edge CRUD (validate + reload) |
| `POST /api/pipeline/validate` | dry-run validation of a proposed graph (no write) |
| `GET /api/pipeline/field-schema?source_type=&segment=` | adapter field schema for the builder |
| `GET /api/pipeline/stats?window=` | per-node entered/dropped/passed counts for the diagram overlay |
| `POST/PATCH/DELETE /api/enrichers` | enricher node CRUD compat shim over `pipeline_nodes` |
| `GET /api/filter-rules`, `GET /api/enrichers` | retained as compat views over graph nodes |

`PUT /api/pipeline/graph` is the builder's primary save path. It replaces **only the
user-editable nodes and edges** inside one DB transaction: reserved nodes are matched by
`(type, role)` and preserved (their stable IDs are kept; incoming payload reserved nodes are
reconciled by role, never deleted-and-recreated), so edges referencing reserved nodes never
dangle through `ON DELETE CASCADE`. Non-reserved nodes/edges absent from the payload are
deleted; present ones are upserted; a **reserved node omitted from the payload is preserved
unchanged** (never deleted), and an incoming `enabled=false` on a reserved node is ignored.
The whole replace + validation happens before commit;
on validation failure the transaction rolls back (422) and `reload_graph()` is not called.
Node/edge CRUD endpoints support incremental edits with the same validate-then-reload rule.
`DELETE` of a node cascades its edges (FK `ON DELETE CASCADE`); deleting a reserved node is
rejected 422 before any write.

`GET /api/pipeline/stats?window=` defaults to a 24h window if `window` is omitted; accepts a
duration (e.g. `24h`, `7d`) and aggregates `funnel_stages` rows whose `created_at` falls in
the window. A malformed `window` value returns **422** (not a silent fallback).

`GET /api/pipeline/field-schema` returns **422** for an unknown `source_type` (not registered
in the adapter registry) or a malformed `segment` value, rather than an empty or
silently-defaulted result, so authoring typos surface immediately.

## Design: UI — Pipeline DAG diagram + builder sub-tab

The Ingestion page gains a `Tabs` control: **Overview** (today's content) | **Pipeline**.
The Pipeline tab is both visualization and editor:

- Node-link DAG rendered as hand-rolled SVG (codebase convention; `Topology.tsx` node-link
  is the precedent — no graph library is added). Left-to-right: `Source` → pre-extraction
  `pre_filter`s → `Extraction` → interleaved `rule`/`llm`/`enricher` nodes with
  diverge/converge → `Triage`/`Auto-include`/`Drop` sinks.
- Each node shows a type icon, label, enabled switch, `source_scope` chips, and **live
  funnel counts** (entered / dropped / passed) from `GET /api/pipeline/stats`. Edges show
  their route predicate as a badge.
- Clicking a node opens its config dialog: `RuleBuilderDialog` (nested AND/OR/NOT tree with
  field controls from the field schema), `EnricherConfigDialog`, `PreFilterDialog`, or an
  `LlmFilterDialog` (thresholds). Edits hit the API and hot-apply. Reserved nodes open a
  read-only inspector (no delete, no `source_scope`).
- The builder edits topology (add node, connect/disconnect edges, set predicate, reorder
  outgoing edges, toggle, set `source_scope`). Client-side validation mirrors the server
  rules; save uses `PUT /api/pipeline/graph`. An accessible fallback table lists
  nodes/edges/predicates.
- Data hooks follow the TanStack Query pattern in `hooks/useFunnel.ts`
  (`pollWhenVisible`, centralized keys, mutations invalidate + toast).

**Claude Design prompt deliverable.** The implementation plan phase is preceded by a
Claude Design step. A complete, paste-ready prompt is maintained at
`docs/auto-plan/specs/2026-06-23-ingestion-pipeline-dag-claude-design-prompt.md`, covering:
`PipelineCanvas` (DAG render + reorder/connect + pan/zoom), `StageNode` variants (one per
stage type, with enabled/disabled/selected/error states and live counts),
`EdgePredicateBadge`, `RuleBuilderDialog` (nested tree, dynamic field controls, add/remove
group/condition, AND/OR/NOT), `EnricherConfigDialog` (provider, depth, budget),
`PreFilterDialog`, `LlmFilterDialog`, and the a11y fallback table — each with props, states
(empty/loading/error/disabled), data shapes, and the dark shadcn/Tailwind-v4 conventions
already used in `ui/`.

## Design: Funnel tracing & observability

- `funnel_stages` (existing: `item_id`, `stage_data jsonb`, `created_at`) logs one entry
  per visited node: `{node_id, type, label, verdict, segment, score?, dropped_by?}`. The
  `item_id` column is BIGINT (converted in migration 011 to reference `items.id`) and matches
  `Item.id: int`; this work introduces no `item_id` type change.
- `GET /api/pipeline/stats` aggregates `funnel_stages` over a window into per-node
  `entered`/`dropped`/`passed` and per-edge traversal counts for the diagram overlay.
- Per-item trace (existing `GET /api/items/{id}/funnel`) renders the path the item took
  through the graph.
- Retention reuses `RetentionConfig` (`funnel_stages` already swept by
  `delete_older_than`).

## Design: Migration & bootstrap

### Default graph (behavior parity)

The migration is `018_pipeline_dag.py` (`down_revision="017"`). It creates the two tables,
seeds the five reserved nodes (their IDs are IDENTITY-assigned and captured via `RETURNING`
to wire the seed edges — never literal in code), and builds the **default graph** that
reproduces today's end-to-end behavior, not merely threshold routing:

```
source ──[type==diff]──→ extraction ──→ llm_filter ──┬─(INCLUDE via threshold)─→ auto_include
       └─[always]──────→ extraction          │       ├─(DROP via threshold)─────→ drop
                                              │       └─(TRIAGE)→ enr:default(depth per source_type) → triage
```

- One `llm_filter` node holds the global thresholds and is fed every existing advisory
  `FilterRule` (migrated as prompt context, unchanged) — reproducing today's single LLM
  relevance scoring.
- The threshold fallback at the `triage` sink reproduces `decide_from_score`, so
  `auto_include`/`drop`/`triage` split exactly as today.
- Enricher nodes are placed **only on the triage path** (matching today's "enrich only on
  triage" behavior). The migration creates one enricher node per existing `enrichers` row;
  `depth` is set to `deep` for the `diff`-scoped enricher and `shallow` otherwise (today's
  rule), and the node `label` carries the old `stage` value. See ADR 0070.
- No `pre_filter` or `rule_filter` nodes are seeded (today has none); `funnel_order` is
  superseded and not carried into the graph as routing.

The migration is deterministic: given today's `enrichers`/`filter_rules` rows it always
produces the same node/edge set (parity test V1).

### Bootstrap on a fresh / empty DB

If `pipeline_nodes` is empty at engine startup (fresh DB, or the migration has not run),
`reload_graph()` constructs the default graph in memory and the engine proceeds; a startup
log records that the in-memory default is in use. The first successful graph `PUT` persists
a user-authored graph thereafter. This guarantees ingestion is never blocked by a missing or
empty graph.

## File Changes

### New files
| File | Description |
|------|-------------|
| `src/workbench/domain/pipeline.py` | `PipelineNode`, `PipelineEdge`, `PipelineGraph`, `NodeType`, `SinkRole` |
| `src/workbench/domain/rules.py` | `Condition`, `Group`, `ConditionTree`, `Operator`, `FieldSpec` |
| `src/workbench/pipeline/executor.py` | `StageExecutor`, `ExecutionContext`, verdict resolution, `MAX_NODES_PER_ITEM`, `PipelineLoopError` |
| `src/workbench/pipeline/rule_eval.py` | `evaluate(tree, field_map)`, `MATCHES_MAX_PATTERN_LEN` |
| `src/workbench/pipeline/field_map.py` | pre/post field-map builders |
| `src/workbench/pipeline/graph_validation.py` | `validate_graph`, default-graph builder |
| `src/workbench/storage/postgres/pipeline_graph.py` | `PgPipelineGraphStore` (nodes + edges) |
| `src/workbench/api/pipeline.py` | graph/node/edge/validate/field-schema/stats routes |
| `src/workbench/migrations/versions/018_pipeline_dag.py` | tables + reserved-node seed + data migration (`down_revision="017"`) |
| `docs/auto-plan/specs/2026-06-23-ingestion-pipeline-dag-claude-design-prompt.md` | Claude Design prompt |
| `ui/src/pages/PipelineTab.tsx` | Pipeline sub-tab container |
| `ui/src/components/pipeline/PipelineCanvas.tsx` | DAG SVG render + builder |
| `ui/src/components/pipeline/StageNode.tsx` | node renderer (variants) |
| `ui/src/components/pipeline/RuleBuilderDialog.tsx` | nested condition-tree builder |
| `ui/src/components/pipeline/EnricherConfigDialog.tsx` | enricher config |
| `ui/src/components/pipeline/PreFilterDialog.tsx` | pre-filter rule |
| `ui/src/components/pipeline/LlmFilterDialog.tsx` | llm-filter thresholds |
| `ui/src/hooks/usePipeline.ts` | graph/stats/field-schema queries + mutations |
| `ui/src/lib/types/pipeline.ts` | TS types mirroring domain models |

### Modified files
| File | Description |
|------|-------------|
| `src/workbench/pipeline/engine.py` | `enqueue` runs pre-segment sub-walk before urgency scoring; `process_raw_item` keeps batch-relevance pre-pass then delegates per-item post-extraction to `StageExecutor`; `reload_graph()` |
| `src/workbench/providers/source/base.py` | `filterable_fields`, `pre_filter_fields` classmethods |
| `src/workbench/providers/source/*.py`, `workbench-meta/.../source/*.py` | declare field schemas (diff/meta_tasks land in workbench-meta) |
| `src/workbench/domain/enrichment.py` | `EnricherConfig` gains `depth`; `stage` retained for compat view |
| `src/workbench/runtime/app.py` | `create_composite_enricher` reads DAG; wire `PgPipelineGraphStore`; mount `api/pipeline.py`; `reload_graph` on startup (default-graph bootstrap if empty) |
| `src/workbench/storage/base.py`, `storage/postgres/stores.py` | `PipelineGraphStore` interface + wiring |
| `src/workbench/api/enrichers.py` | add POST/PATCH/DELETE as compat shim over `pipeline_nodes` |
| `ui/src/pages/Ingestion.tsx` | introduce `Tabs`; mount Pipeline tab |
| package `README.md`s (touched dirs) | per CLAUDE.md convention |

## Verification

1. A graph of `source → extraction → llm_filter → triage` produces byte-identical
   **threshold routing** outcomes to the current pipeline for a fixed input corpus; the full
   **migrated default graph** (with the triage-only enricher and auto_include/drop/triage
   branches) reproduces today's end-to-end behavior including enrichment depth (migration
   parity test).
2. `validate_graph` rejects: missing/duplicate reserved nodes, cycles, a sink reachable
   without `extraction`, a `pre_filter` in the post segment (and vice-versa), unreachable
   nodes, traps, `source_scope` on a reserved node, an empty `source_scope` `[]`,
   `enabled=false` on a reserved node, any `loopback` node, an illegal operator
   for a field type, a field whose declared `segment` excludes the node's segment, a
   `post`-only field on a pre-extraction edge predicate (and a `pre`-only field on a
   post-extraction edge), an invalid/oversized `matches` regex, and conditions referencing
   fields absent from the schema. It emits a **warning** (not rejection) for a `rule_filter`
   referencing an `enrichment.<key>` not produced by an upstream enricher on all reaching
   paths.
3. `evaluate` returns correct truth values for a table of nested AND/OR/NOT trees including
   missing-field, empty-group, and `NOT` cases.
4. A `pre_filter` matching `type==diff AND status==draft` drops the item with **zero** LLM
   calls (assert urgency scorer not invoked) and records a DROPPED pre-segment funnel entry.
5. A diff and a task converge on a shared `llm_filter` node and diverge back to
   type-specific nodes; each item's `funnel_stages` trace shows exactly one path.
6. First-terminal-verdict-wins: a `rule_filter` returning DROP short-circuits before a later
   `llm_filter` runs (assert the LLM is not called).
7. Editing an enricher's depth/budget via `PATCH /api/enrichers/{id}` changes enrichment
   behavior on the next item with no restart (hot-apply), and writes to `pipeline_nodes`
   (compat shim), not the legacy `enrichers` table.
8. `GET /api/pipeline/field-schema?source_type=diff&segment=pre` returns diff pre fields;
   adding a new adapter with `filterable_fields` surfaces its fields and its `source_type`
   in the universal enum without UI changes.
9. `GET /api/pipeline/stats` per-node counts equal the `funnel_stages` aggregation for a
   seeded run over the requested window.
10. The Pipeline tab renders the graph, overlays live counts, opens each node's config
    dialog, and saves a valid edited graph via `PUT /api/pipeline/graph`; reserved nodes are
    not deletable.
11. `reload_graph()` swaps the snapshot under `reload_lock`: an item whose walk started
    before an edit completes on the old snapshot; the next item uses the new one.
12. Empty `pipeline_nodes` at startup bootstraps the in-memory default graph and ingestion
    proceeds (no crash, log emitted).
13. Threshold resolution: (a) a path with one executed `llm_filter` uses that node's
    thresholds; (b) a path with no executed `llm_filter` but a batch-seeded score uses global
    `thresholds_for(source_type)`; (c) a path with no score routes to `triage` as-is; a
    disabled/out-of-scope `llm_filter` is not counted as "most recent".
14. `tests/test_folder_docs.py` passes (READMEs updated for new package dirs).

## Resolved Questions

1. **Execution model:** → Real ordered stage executor; the authored graph is the
   execution order (not cosmetic). Source: brainstorming decision.
2. **Pipeline shape:** → Routing DAG with single-path per-item execution (not a linear
   list, not a concurrent DAG). Source: brainstorming decision.
3. **Concurrency:** → Sequential execution now (one node at a time); node/edge model
   designed so parallel fan-out can be added later without a rewrite. Source: brainstorming.
4. **Re-divergence after convergence:** → Supported; shared nodes have multiple outgoing
   edges re-split by `source_type` or accumulated state. Source: brainstorming.
5. **Rule expressiveness:** → Nested boolean tree (AND/OR/NOT). Source: brainstorming.
6. **Field schema source:** → Backend-declared per adapter, served to the UI. Source:
   brainstorming.
7. **Enricher UI gap:** → Make enrichers fully configurable (CRUD, depth, budget) and
   DB-authoritative with hot-apply; enrichers are graph nodes, `/api/enrichers` is a compat
   shim. Source: brainstorming.
8. **Pre-extraction filtering point:** → Inside `enqueue`, before urgency LLM scoring;
   drop skips both the LLM call and enqueue. Source: brainstorming + code trace.
9. **Decision resolution:** → First-terminal-verdict-wins with threshold fallback on the
   last `llm_filter` score (preserves current behavior). Source: brainstorming.
10. **Storage authority:** → DB-authoritative `pipeline_nodes` + `pipeline_edges` (resolves
    the YAML-vs-DB discrepancy for this surface); migration reproduces today's behavior.
    Source: brainstorming + code trace.
11. **Advisory vs deterministic rules:** → Keep advisory `FilterRule`s feeding `llm_filter`
    as prompt context; add deterministic `rule_filter`/`pre_filter` as new gates. Source:
    code trace + brainstorming.
12. **Diagram technology:** → Hand-rolled SVG (no graph library), per codebase convention.
    Source: code trace.
13. **Enrichment beyond the triage branch:** → Enricher nodes may appear on any
    post-extraction path; the migrated default keeps them triage-only for parity. Source:
    ADR 0070.
14. **MAX_NODES_PER_ITEM backstop:** → 256, defensive only; overflow raises
    `PipelineLoopError` treated as a fail-safe `triage`. Source: best-judgment.
15. **Snapshot/reload concurrency:** → Each walk binds one immutable `PipelineGraph`
    snapshot to completion; `reload_graph()` swaps the engine reference under `reload_lock`
    for new walks only. Source: code trace (`set_source_thresholds` pattern) + best-judgment.
16. **`funnel_stages.item_id` type:** → BIGINT (migration 011 → `items.id`), matches
    `Item.id: int`; no type change introduced. Source: code trace (migrations 009/011,
    `domain/items.py`).
17. **Loopback in v1:** → `loopback` is a defined-but-rejected node type — present in the
    enum for forward-compat, rejected by `validate_graph` (rule 9), never seeded, never
    offered in the builder, never walked. Full loopback is deferred. Source: ADR 0065
    (single-path acyclic) + scope decision.
18. **`FieldSpec.segment=both` enforcement:** → `both` fields are offered in either segment;
    validation rule 7 accepts a field whose declared segment includes the node's segment;
    operators apply identically in both. Source: design hardening.
19. **Migration number:** → `018_pipeline_dag.py`, `down_revision="017"`; reserved-node IDs
    are IDENTITY-assigned (captured via `RETURNING`), resolved by `(type, role)`, never
    hardcoded. Source: code trace (latest migration 017; BIGINT IDENTITY since 011).
20. **Reserved nodes always enabled:** → reserved nodes are pinned `enabled=true`; a disabled
    `extraction` would skip `extract_items` at runtime, so validation rejects `enabled=false`
    on any reserved node and write paths ignore an incoming `enabled` for them. Source:
    executor `if node.enabled` guard + articulation invariant.
21. **Empty `source_scope`:** → `[]` is rejected (a never-runnable node is an authoring
    error; use `enabled=false`). Source: design hardening.
22. **Edge-predicate segment:** → a predicate's field-validity segment is its `from_node`'s
    segment; a `post`-only field on a pre-extraction edge (or `pre`-only on a post edge) is
    rejected. Source: evaluation-point reasoning (predicate runs at `select_next_edge`).
23. **Invalid query params:** → unknown `source_type`, malformed `segment`, and malformed
    `window` all return 422 rather than silently defaulting. Source: best-judgment consistent
    with the spec's 422-on-invalid stance.

## Out of Scope

- Concurrent/parallel branch execution and fan-out/fan-in joins (model supports it later).
- `loopback` is defined as a node type for forward-compatibility but **rejected by
  validation in v1** (not seeded, not offered in the builder, never walked). Full loopback
  re-processing — including the dedup-gate bypass for re-enqueue (an internal re-enqueue
  flag bounded by `max_iterations`, distinct from the source-id dedup key) — is deferred to
  a future release.
- Migrating source configs off YAML write-back (only the pipeline graph becomes
  DB-authoritative here).
- LLM-authored or auto-suggested rules (the feedback/tuning loop stays as-is).
- Versioning/history of graph edits and rollback UI.
- Drag-and-drop auto-layout beyond stored `ui_x`/`ui_y` and manual positioning.

# ADR 0063 — Cross-entity lineage via a generic path-keyed `entity_item_links` join table

Status: Accepted
Date: 2026-06-18

## Context

Entities created across the system (LLM calls, interactions, plans, triage cards,
messages) derive from specific items in the lineage tree (ADR 0062). We need
bidirectional, many-to-many, depth-aware links from any such entity back to the
exact item(s) it consumed — without polluting the item tree, and extensible to
future entity types with minimal effort.

## Decision

Add one generic join table
`entity_item_links(id, entity_type TEXT, entity_id BIGINT NULL, item_id BIGINT
NOT NULL REFERENCES items(id) ON DELETE CASCADE, item_path TEXT NOT NULL,
correlation_id TEXT NULL, created_at)`. Links are keyed/queried by the immutable
materialized `item_path` (enabling subtree scans `item_path = '123' OR item_path
LIKE '123.%'` via a `text_pattern_ops` index) and also carry `item_id` for FK
cascade. A shared `EntityLinkStore.record(entity_type, entity_id, item_paths)`
helper makes a new entity link in one line. The three existing depth-0 FK
entities (`TriageCard`/`EnrichmentTrace`/`FeedbackCorrection`) keep their
`item_id` columns; the reverse-lookup endpoint UNIONs them in. `LlmCallRecord.items`
stays as a denormalized read-convenience; the join table is the source of truth
for cross-entity queries.

## Alternatives rejected

- **Per-entity FK columns / tables** — not extensible, no many-to-many, no
  multi-item links for batched LLM calls.
- **Entity nodes inside the item tree** (`#123.1.L1`) — pollutes the lineage tree
  with non-items and breaks path/feed semantics.
- **Store only `item_id`** — loses cheap depth-aware subtree queries and diverges
  from producers that already speak in paths (`LlmCallRecord.items`).
- **Migrate the 3 existing FK entities into the table** — dual-source-of-truth
  churn for no query gain; they are strictly depth-0 single-item.
- **Native Postgres enum for `entity_type`** — `ALTER TYPE ADD VALUE` DDL churn;
  rejected per the migration-014 TEXT precedent.

## Entity-side integrity

`(entity_type, entity_id)` has no DB foreign key (the target set is
polymorphic/open). Cascade on entity deletion is owned by the deleting code:
retention pruners call `EntityLinkStore.unlink_entity(entity_type, entity_id)`.
The item side uses `ON DELETE CASCADE`.

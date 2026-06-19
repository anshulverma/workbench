# ADR 0064 — Correlation-id linkage for LLM calls whose consumed items are minted after the call

Status: Accepted
Date: 2026-06-18

## Context

An LLM call links to exactly the item(s) it consumed, at their true depth
(ADR 0063): the extraction call consumes the raw source → links the root `#123`;
the relevance-scoring call consumes the extracted items → links the scored
children `#123.1..#123.n`; an action-handling call links that action `#123.1.1`.
But `LlmCallRecord` ids are assigned asynchronously by the background writer
(`save_many`), and for relevance scoring (batched and non-batched) and batched
urgency scoring, the consumed children/roots are minted by `allocate_child` /
`create_root` *after* the call returns. So neither the record id nor the consumed
item paths exist at the call site for those calls.

## Decision

Use two recording paths:

1. **Call-time** — when consumed item paths are known at the call site
   (extraction, triage `generate_card`, free-text interpret, re-triage), stamp
   `LLMCallContext.item_paths`. The writer derives both `LlmCallRecord.items` and
   `entity_item_links` rows inside `save_many` (changed to `INSERT … RETURNING id`)
   once ids exist.
2. **Post-persist via correlation_id** — for relevance scoring and batched
   urgency, stamp a client-generated `correlation_id` in `LLMCallContext` (and a
   new `llm_calls.correlation_id` column). After the children/roots are allocated,
   write `entity_item_links` rows keyed by `correlation_id` (with `entity_id`
   NULL); the surfacing query resolves `entity_id` by joining
   `llm_calls.correlation_id`. Two partial unique indexes keep both id-known and
   correlation-only rows idempotent.

## Alternatives rejected

- **Pre-allocate children before the scoring call** so paths exist at call time —
  breaks the append-only seq-allocation seam and mints rows for items that may be
  auto-dropped (violates ADR 0062 D1/D4).
- **Make `save_many` synchronous to return ids on the hot path** — violates the
  non-blocking sink (ADR 0057).
- **Link scoring calls to the root only** — simpler, but violates the
  "link to exactly what it consumed" principle the user required.

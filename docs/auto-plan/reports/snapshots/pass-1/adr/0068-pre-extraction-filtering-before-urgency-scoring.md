# 0068 — Pre-extraction filters run before urgency LLM scoring

**Status:** Accepted

**Context:** The first LLM cost in ingestion is urgency scoring inside `engine.enqueue`.
Some items (draft diffs, notification email, recurring calendar events) can be dropped from
structured signals alone, before any LLM call, saving cost and queue space.

**Decision:** `pre_filter` stages form a pre-extraction segment walked inside `enqueue`
before urgency scoring. They evaluate only pre-extraction data (`urgency_signals` +
`source_*`, via each adapter's `pre_filter_fields`). A match drops the item: it is recorded
as a DROPPED funnel entry, marked processed, and is **not** urgency-scored or enqueued.

**Alternatives:** Filter after dequeue with the post-extraction stages (rejected: wastes
the urgency LLM call and queue slot). Parse `raw_text` JSON for richer pre fields by default
(rejected: `urgency_signals` is the reliable structured surface; adapters may opt into
parsing via `pre_filter_fields`).

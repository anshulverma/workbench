# 0070 — Enrichment is generalized to any post-extraction path (default stays triage-only)

**Status:** Accepted

**Context:** Today enrichment runs **only** on the triage branch of `process_raw_item`
(`enrich_item` is called just before card generation), with depth fixed by source type
(`deep` for `diff`, `shallow` otherwise). Moving enrichers into the DAG as nodes means an
`enricher` node can be placed anywhere in the post-extraction segment — including on a path
that ends at `auto_include` or upstream of a `rule_filter` that may later drop the item.
This changes the cost profile (items that get auto-included or dropped could now be
enriched) and is not reversible once users author such graphs.

**Decision:** Allow `enricher` nodes on any post-extraction path; their placement (and thus
when enrichment runs and at what cost) is user-authored. The migrated **default graph**
deliberately places enricher nodes **only on the triage path**, reproducing today's
behavior exactly, so the generalization is opt-in via graph edits. Per-node `budget` caps
(`max_api_calls`, `max_seconds`) bound the cost of any placement.

**Alternatives:** Keep enrichment hardcoded to the triage path (rejected: contradicts the
goal of a fully user-authored executable graph and a configurable enricher stage).
Auto-enrich every item regardless of outcome (rejected: wastes API budget on items that are
auto-included or dropped without ever being read in a card).

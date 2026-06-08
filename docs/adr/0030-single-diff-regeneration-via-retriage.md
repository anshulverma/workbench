# ADR 0030: Diff Card Regeneration Happens Only Through the Change-Monitoring Re-Triage Path

When the review-grade diff cards feature (ADRs 0022–0029) and the change-monitoring & re-triage feature are combined, diff card content is regenerated **only** through change-monitoring's `_fire_retriage` path. The diff-cards design's standalone `revision_id` staleness check (its decision d46 — "regenerate when the fetched revision is newer than the stored one") is **dropped**: there is one regeneration mechanism, not two.

We chose this because d46 was explicitly flagged as depending on a re-triage trigger that did not exist in the engine — and change-monitoring builds exactly that trigger. Keeping both would mean two independent code paths deciding when to regenerate a diff card, which drift apart and double the LLM cost. `_fire_retriage` already re-reads the item, re-runs `enrich_item` (which re-invokes the `DiffEnricher` and re-fetches the diff), and calls `generate_card`, so it subsumes d46 entirely.

**Consequence:** The `DiffEnricher` still captures `revision_id`/`diff_version` into enrichment context, but it is used for display and for the `ChangeDetector`'s comparison — not for a separate polling check. `generate_card` gains a `change_context` parameter threaded into the `CardContentGenerator`. No standalone revision-polling code is written.

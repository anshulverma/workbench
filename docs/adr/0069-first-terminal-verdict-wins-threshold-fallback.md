# 0069 — Verdict resolution: first-terminal-wins with threshold fallback

**Status:** Accepted

**Context:** The new executor lets multiple stages (deterministic rules, LLM filter) each
potentially decide an item's outcome. We need a single, predictable resolution rule that
also preserves today's threshold-based behavior so the migration is behavior-neutral.

**Decision:** A stage's explicit terminal verdict (`DROP`/`INCLUDE`/`TRIAGE`) wins
immediately and short-circuits the rest of the path (first-terminal-wins). If the item
reaches the `triage` sink with no explicit verdict, an ordered 3-case threshold fallback
applies: (1) if a `llm_filter` actually executed on the path, `decide_from_score` uses the
**most-recently-executed** `llm_filter` node's thresholds (a skipped/disabled one does not
count); (2) else if only the batch-relevance pre-pass seeded a score, `decide_from_score`
uses the global `thresholds_for(source_type)`; (3) else the item routes to `triage` as-is.
A graph of `source → extraction → llm_filter → triage` therefore reproduces today's pipeline
exactly (case 1).

**Alternatives:** Last-verdict-wins (rejected: a cheap upstream gate should short-circuit
expensive downstream LLM work). Accumulate/vote across stages (rejected: opaque and harder
to reason about than first-wins).

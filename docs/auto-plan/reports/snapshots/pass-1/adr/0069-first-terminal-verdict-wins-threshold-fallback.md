# 0069 — Verdict resolution: first-terminal-wins with threshold fallback

**Status:** Accepted

**Context:** The new executor lets multiple stages (deterministic rules, LLM filter) each
potentially decide an item's outcome. We need a single, predictable resolution rule that
also preserves today's threshold-based behavior so the migration is behavior-neutral.

**Decision:** A stage's explicit terminal verdict (`DROP`/`INCLUDE`/`TRIAGE`) wins
immediately and short-circuits the rest of the path (first-terminal-wins). If the item
reaches the `triage` sink with no explicit verdict but an `llm_filter` set a score, the
threshold fallback applies `decide_from_score` on the most recent `llm_filter` thresholds —
identical to current behavior. A graph of `source → extraction → llm_filter → triage`
therefore reproduces today's pipeline exactly.

**Alternatives:** Last-verdict-wins (rejected: a cheap upstream gate should short-circuit
expensive downstream LLM work). Accumulate/vote across stages (rejected: opaque and harder
to reason about than first-wins).

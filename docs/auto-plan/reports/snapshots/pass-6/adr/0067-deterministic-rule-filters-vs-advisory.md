# 0067 — Deterministic rule filters coexist with advisory LLM rules

**Status:** Accepted

**Context:** Today every `FilterRule` is advisory — rendered into the LLM scoring prompt as
a hint, never applied deterministically. Users need hard if-then-else gates (e.g.
`type==diff AND status==draft → drop`) that do not depend on LLM judgment.

**Decision:** Add deterministic `rule_filter` (post-extraction) and `pre_filter`
(pre-extraction) stages whose nested boolean condition trees gate items by exact
evaluation, emitting terminal verdicts. Keep the existing advisory `FilterRule`s feeding
the `llm_filter` stage as prompt context unchanged. The two mechanisms coexist: deterministic
gates short-circuit; the LLM filter scores what survives.

**Alternatives:** Replace advisory rules with deterministic ones (rejected: loses the
adaptive natural-language filtering the product relies on). Make advisory rules also act as
gates (rejected: surprising — a soft hint silently becoming a hard drop).

# 0058 — Per-call `llm_calls` log is the source of truth for the LLM Infra page

**Status:** Accepted (2026-06-17)

## Context

LLM usage is observable today only as cumulative Prometheus counters and a periodic `llm_usage_summary` log line; `UsageAggregator` drains/resets per interval and drops cache tokens, latency, and item_count. The LLM Infra UI needs a queryable per-call log plus rolling 24h metrics.

## Decision

Add a durable `llm_calls` table as the per-call source of truth. The four UI stat cards are computed from it via SQL over a rolling 24h UTC window. Existing Prometheus families and `llm_usage_summary` are kept unchanged as the ops view (additive, no refactor). High-cardinality fields (`origin`, item ids, prompts) live only in the table; Prometheus stays low-cardinality (`client`, `model`, optionally `stage`).

## Alternatives

- Compute cards from Prometheus/`UsageAggregator` — no PromQL server here, and the aggregator drops needed fields (rejected).
- Replace `plugboard_*` with table-derived exports — breaks ops scrapers, raises cardinality (rejected).

## Consequences

Two sinks fed from the same event compute over different windows (Prometheus cumulative since process start; table rolling 24h), so their numbers are not expected to match exactly — documented to avoid "the numbers disagree" confusion.

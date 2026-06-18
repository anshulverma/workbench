# 0057 — Sync sink → async durable LLM-call writer bridge

**Status:** Accepted (2026-06-17)

## Context

`PlugboardSink` is synchronous, fire-and-forget (`Callable[[PlugboardCallRecord], None]`) and runs in the LLM call path. Durable per-call persistence requires async DB writes that must never block or fail an LLM call. Today the sink and its wiring onto the providers (`inner_llm._sink = ...`, `queue_scorer._sink = ...`) are created **only** inside `if config.metrics.enabled:` in `runtime/app.py`. Since LLM tracking must be independent of `metrics.enabled` (decision d14), the sink wiring can no longer be gated solely on `metrics.enabled` — otherwise with `metrics.enabled=false, llm_tracking.enabled=true` no sink is attached and `record_plugboard_call` fans out to nothing, capturing zero rows.

## Decision

`_plugboard_sink` fans out: (1) the existing `UsageAggregator` + Prometheus path, executed only when `config.metrics.enabled`; (2) `queue.put_nowait(rec)` onto a bounded `asyncio.Queue` (maxsize 1000) drained by a new `_llm_writer_loop` task that batch-inserts via `stores.llm_calls.save_many`, executed only when `config.llm_tracking.enabled and stores.llm_calls is not None`. The sink closure and its wiring onto the providers are created whenever **either** subsystem is enabled (`config.metrics.enabled or config.llm_tracking.enabled`); each branch inside the sink self-guards so an enabled-but-unused path is a no-op. On `QueueFull` or any writer/DB error the record is logged and dropped. The writer task lifecycle mirrors `_summary_loop` (created in lifespan, cancelled on shutdown) and is gated on `llm_tracking.enabled`.

## Alternatives

- Synchronous DB write inside the sink — blocks/fails the LLM call (rejected).
- A new async-capable sink interface — changes the sink contract everywhere (rejected).
- Unbounded queue — risks unbounded memory growth during a Postgres outage (rejected).
- Keep the whole sink under `metrics.enabled` and require `metrics.enabled=true` for tracking — couples the two flags, contradicting d14 (rejected).

## Consequences

At-most-once semantics: under sustained backpressure or DB outage some records are dropped (acceptable for a tracking feature; surfaced via a dropped-records counter). The LLM call path stays non-blocking and failure-isolated. The sink wiring is now driven by `metrics.enabled OR llm_tracking.enabled`; when only one is on, the other branch is a guarded no-op (e.g. `usage_agg`/Prometheus objects are not constructed when `metrics.enabled=false`).

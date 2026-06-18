# 0061 — In-flight (`running`) LLM calls are not persisted

**Status:** Accepted (2026-06-17)

## Context

The LLM Infra UI defines a `running` status (in-flight calls with null tokens/latency). A durable `llm_calls` row is written only after a call returns, and capture spans two processes (workbench + memory subservice) with no shared in-memory state.

## Decision

Persist only terminal rows (`status ∈ {ok, error}`). `running` is never written; the DB-backed tail shows completed calls streaming in as they finish. The UI keeps `running` in its type for back-compat but the API never emits it.

## Alternatives

- Write a pre-call `running` row and `UPDATE` on completion — doubles writes, complicates the fire-and-forget sink, and leaves orphaned rows on crash (rejected).
- Maintain a process-local in-flight registry merged into the poll response — would not see the memory subservice's in-flight calls and adds complexity (deferred as a possible future enhancement).

## Consequences

The tail shows completed calls only (still "live" — new completions stream in). Verified safe: the UI is fully null-tolerant (keyed status lookups fall back to `ok`; `tokens_out`/`latency_ms` use `??`/`!= null` guards), so omitting `running` and always sending concrete tokens/latency requires no UI change.

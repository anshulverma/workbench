# 0059 — Cross-service LLM capture: memory subservice writes to the workbench-owned table

**Status:** Accepted (2026-06-17)

## Context

"Capture everything" includes the memory subservice (`src/memory/`), a separate process on a separate database whose LLM calls are owned by Graphiti. The user chose full fidelity for memory. The subservice has no access to workbench `app.state.stores`, and its calls (and tokens) are not captured today.

## Decision

Wrap the memory subservice's Graphiti `AnthropicClient` to capture system/input prompt, completion, structured result, and tokens (best-effort; `tokens_estimated=true` when Graphiti omits `usage`). The memory process writes **full rows directly to the workbench-owned `llm_calls` table** via its own `asyncpg` pool using a configured **workbench Postgres DSN**, tagged `origin=memory_subservice`, `stage=memory`. Workbench is the sole schema owner (migration 013); memory is an INSERT-only writer pinned to a documented column contract. Rollout (per ADR 0053) applies migration 013 to the workbench DB before the memory writer deploys; the writer is behind an off-by-default flag with a table-presence preflight.

## Alternatives

- Memory POSTs to a new authenticated workbench endpoint — adds a network hop + auth surface and fails when workbench is down (rejected; shared-DB write survives workbench downtime).
- Shared writer library imported by both repos — cleaner ownership but heavier for a single-user tool (deferred).
- Defer memory to v2 — rejected by the user (wants everything).

## Consequences

Two processes write one table; concurrent inserts are safe (identity PK + MVCC). Schema changes require coordinated deploy (migration-before-writer). Memory keeps its existing Prometheus emission; the DB row is additive (no double count, since the UI reads the table and ops reads Prometheus). Graphiti-internal wrapping is brittle to Graphiti upgrades — accepted cost of full fidelity.

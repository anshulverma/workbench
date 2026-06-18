# 0060 — Polling (not SSE) for live tails

**Status:** Accepted (2026-06-17)

## Context

The LLM Infra tab presents a "live" tail of LLM calls. WorkBench has no streaming infrastructure (no `StreamingResponse`/SSE/WebSocket anywhere); every "live" surface uses TanStack Query `pollWhenVisible()` polling, and `LiveTail` is built for parent-driven poll-and-append.

## Decision

Drive the LLM tail with TanStack Query polling: `useLLMCalls` at `pollWhenVisible(5_000)` (tighter than the 15s norm for a tail), `useLLMMetrics` at 15s, `useLLMCallDetail` fetched lazily on row click. The component renders the newest-N from each poll (full-array replace) and applies the existing flash/cap; no client-side append/diff, no `setInterval`.

## Alternatives

- SSE/WebSocket streaming — a brand-new transport pattern requiring middleware changes, unjustified for a single-user loopback tool (rejected; may be revisited if a true push surface is needed).

## Consequences

Up to ~5s tail latency; polling pauses on hidden tabs (`pollWhenVisible`). Consistent with every other live surface in the app. Detail bodies are fetched on demand, keeping the polled list payload small.

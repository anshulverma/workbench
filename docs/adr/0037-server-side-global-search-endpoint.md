# ADR 0037: Global Search Is a Server-Side ILIKE Endpoint With a Grouped Envelope, Driven by a cmdk Palette

**Status:** Accepted — 2026-06-08

**Context.** The ⌘K command palette needs to search across items, action items, sources, and facts. Facts live in the separate memory service (ADR 0009), which may be `NoopMemoryLayer` or unreachable.

**Decision.** Add a server endpoint **`GET /api/search?q=&limit=`** (default 20, cap 50), bearer-authed, returning a **grouped envelope** `{q, groups:{items,actions,sources,facts}, truncated}` of `SearchHit={id,kind,label,sublabel?,route}`. Matching is **parameterized `ILIKE`** across `items.summary`, `actions.summary`, and `sources` id/adapter_type, with ILIKE wildcards escaped; ranking is exact/prefix before substring, then recency. Facts are proxied from the memory service and **omitted (degraded) when memory is noop or unreachable**. The client uses `cmdk` + shadcn `command` (vendored, offline) with a `(meta|ctrl)+k` listener; nav Commands resolve client-side; the palette honors the five-state taxonomy internally.

**Consequences / Alternatives.** We rejected Postgres FTS/`tsvector` because at single-user scale `ILIKE` is simple and sufficient — no index maintenance or ranking-config surface. Facts being a degradable group (not an error) keeps search useful when the memory service is down. Item hits route to `/triage` (if pending) or `/`, since no item-detail route exists yet (flagged future).

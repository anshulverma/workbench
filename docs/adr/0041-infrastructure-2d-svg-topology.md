# ADR 0041: Infrastructure Visualization Is a 2D SVG Topology Composed From Health Probes

**Status:** Accepted — 2026-06-08

**Context.** The Overview hero wants an "infrastructure" panel. The design suggests something visually rich (3D-ish), but Workbench's real signal is a set of component health probes, and the bundle must stay offline and light.

**Decision.** Add **`GET /api/topology`** that composes the existing health probes into `{nodes:[{id,label,kind,status}], edges:[{from,to,kind}]}`, with `kind ∈ {app,storage,memory_service,connection,adapter,messenger}` and `status ∈ {healthy,degraded,unhealthy,unknown,not_configured}`, polled every 15s. Render it as a **hand-rolled 2D SVG node-link graph** — **no react-three-fiber, no reactflow** — with a visually-hidden table fallback (`role="img"`) for accessibility. neo4j is folded into the `memory_service` node; no meta-only/dcat nodes.

**Consequences / Alternatives.** We rejected 3D (react-three-fiber) and a graph library (reactflow) because they add large dependencies for a small, fixed topology and don't map to real data — a few nodes from health probes don't need a layout engine. The trade-off is that node positions are hand-placed rather than auto-laid-out, which is fine for a small, stable graph.

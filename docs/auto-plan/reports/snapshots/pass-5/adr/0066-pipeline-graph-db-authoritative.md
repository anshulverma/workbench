# 0066 — Pipeline graph is DB-authoritative (pipeline_nodes + pipeline_edges)

**Status:** Accepted

**Context:** The existing `funnel_order`/`enrichers`/`filter_rules` tables carry order but
don't drive execution; source config still uses YAML write-back. The pipeline graph is
edited live from the UI and must hot-apply, which argues against YAML authority for this
surface.

**Decision:** Store the executable pipeline as `pipeline_nodes` + `pipeline_edges`,
DB-authoritative, validated on save, and hot-applied via `reload_graph()` under
`app.state.reload_lock`. The legacy `enrichers`/`filter_rules` content migrates into graph
nodes; `funnel_order` is superseded. Old resource routers become compat views.

**Alternatives:** YAML write-back like sources (rejected: live graph editing + hot-apply
fits DB better, and the funnel is already DB-backed). Reuse `funnel_order` as an index over
detail tables (rejected: a confusing dual model vs one unified graph). This intentionally
scopes the DB-vs-YAML authority change to the pipeline graph only, not source configs.

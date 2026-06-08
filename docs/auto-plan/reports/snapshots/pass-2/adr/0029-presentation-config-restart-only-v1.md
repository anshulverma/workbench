# ADR 0029: Presentation Config Is Restart-Only in v1 (Not on the ADR 0013 Hot-Reload Path)

The new top-level `presentation:` config section (mapping `source_type` to a presenter class plus per-source UX config) is **restart-only** in v1. It is deliberately not wired into the ADR 0013 write-back + targeted hot-reload machinery, which currently covers `sources` and `messenger` only.

We chose restart-only over full ADR 0013 parity because presentation config is a pure rendering concern with no live connections or sockets to swap, so a restart is cheap and safe, and extending the copy-on-write swap path (plus its swap-state testing) is real scope the v1 Phabricator goal does not need. We rejected hardcoding presentation entirely (no YAML), because that violates the explicit requirement to control card treatment as a per-source UX layer.

**Consequence:** Editing `presentation` requires a server restart to take effect; `sources` and `messenger` edits keep hot-reloading per ADR 0013. Because the `CompositeCardPresenter` is built from a config list like the Composite Enricher, adding a copy-on-write hot-reload later is a straightforward extension. Adding the optional `presentation` section bumps the Config File version a minor; when absent, every `source_type` routes to `PlainCardPresenter` (today's rendering).

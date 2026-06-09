# ADR 0045: Manually Created Preference Facts Are a Distinct 'manual' Origin Coexisting With Learned Facts and Tombstones

**Status:** Accepted — 2026-06-08

**Context.** The Knowledge page gains an "Add Fact" button so the user can author a Preference Fact directly, rather than only having facts synthesized from the Interaction Log. Workbench continuously re-synthesizes learned facts, and curation deletes are tombstones (ADR 0019).

**Decision.** Manual facts carry a distinct **`manual` origin** that coexists with **learned** facts. They are authored through a new create path and stored as authoritative entries the synthesis pipeline does not overwrite — the same pinning principle ADR 0019 applies to edited/tombstoned facts. Manual creation, like curation, is recorded via structured app logging with the Correlation ID, **not** appended to the Interaction Log (which is reserved for triage responses feeding synthesis).

**Consequences / Alternatives.** We rejected treating manual facts as ordinary learned facts (re-synthesis could silently overwrite or duplicate them) and rejected a separate store (it would fragment the fact list the dashboard shows). The `manual` origin lets the UI distinguish authored from learned facts and protects them from re-extraction, extending ADR 0019's tombstone/override model to a third fact provenance.

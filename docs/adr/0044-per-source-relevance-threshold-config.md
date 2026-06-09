# ADR 0044: Per-Source Relevance/Noise Thresholds Are Real Source Config (Auto-Include vs Triage vs Drop) With Hot-Reload

**Status:** Accepted — 2026-06-08

**Context.** The Sources page Config Drawer shows noise/relevance sliders. These could be purely cosmetic, or they could control real ingestion behavior. The user asked to build the real noise filter.

**Decision.** Make the sliders **real per-source Source config fields**: relevance/noise thresholds that partition scored items into **auto-include vs triage vs drop**. The new fields participate in the existing config **write-back + targeted hot-reload** path (ADR 0013), so editing a source's thresholds takes effect without a restart.

**Consequences / Alternatives.** We rejected cosmetic-only sliders (they would be dishonest UI) and rejected a global threshold (different sources have very different signal/noise profiles, so the control belongs per-source). Because thresholds ride the ADR 0013 hot-reload machinery, changing them re-scores subsequent ingestion immediately; already-stored items are not retroactively reclassified.

# ADR 0040: The "Uptime" Widget Is Backed by Ingestion Success Rate, and Triage Time Comes from triage_cards

**Status:** Accepted — 2026-06-08

**Context.** The design shows an "Uptime 99.98%" tile and an average-triage-time metric. Workbench persists **no** uptime/health history, and `items` carry **no** `triaged_at` timestamp — so both numbers would have to be fabricated to match the mockup.

**Decision.** Relabel the tile **"Ingestion success rate"** = `success_runs / total_runs` over the window, computed from the existing `ingestion_runs` table (ADR 0015). Do **not** fabricate or persist an uptime figure. Compute **average triage time as `avg(triage_cards.responded_at - sent_at)`**, since there is no `triaged_at` on items. Other derivations stay honest too (signal velocity = items/bucket; throughput = actions `completed_at`/hour; auto_resolved% = `auto_included / all`).

**Consequences / Alternatives.** We rejected showing a fabricated 99.98% uptime (the user explicitly asked for the honest version) and rejected adding a `triaged_at` column just to mirror the mockup — `triage_cards` already records the request/response timestamps. The cost is that the widget reflects ingestion reliability, not process uptime, and avg triage time only covers cards that received a response.

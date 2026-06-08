# Planning Report: Combined Diff Cards + Change Monitoring & Re-Triage

## What this is
A single, dependency-ordered execution plan that merges two already-grilled features so they can be built together:
- **Feature A** — review-grade diff triage cards (spec + plan + ADRs 0022–0029)
- **Feature B** — change monitoring & re-triage (spec + plan)

The two features were planned independently but collide on shared files (`generate_card`, the Messenger interface, `scheduler.py`, `models.py`, `config`, `gchat.py`, the Phabricator adapter). This run resolved the integration seams and produced one combined plan.

## Execution Stats
- Mode: integration-merge (no `--harden`)
- Sub-agents spawned: 5 (3 integration grillers, 1 combined-plan writer, 1 combined-plan reviewer)
- Integration decisions resolved: 21 (i1–i21)
- Integration ADRs written: 3 (0030–0032)
- Combined plan: 31 tasks across 6 phases — PASS (1 load-bearing logic bug found and fixed: `enrich_item` deep-mode in the `code_updated` path)
- Deferred to implementation: exact `diff_version` field name + `meta phabricator.diff` schema (verification task gates Phase 4); two-tier regen gate marked as a discrete task

## The integration seams (and how they were resolved)
1. **`generate_card`** — one merged signature: `generate_card(llm, item, enrichment, source_type, *, memory=None, change_context=None)`; `CardContentGenerator.generate(..., change_context=None)`. Diff generator folds change-awareness into its single Opus call.
2. **`_fire_retriage`** — drives the `CompositeCardPresenter → CardMessage` path (not `format_card_for_chat`); re-runs `enrich_item` (deep) → `generate_card` → presenter → send/update.
3. **Single regeneration mechanism** — Feature A's standalone `revision_id` polling (d46) dropped; regeneration happens only via Feature B's `_fire_retriage` (ADR 0030).
4. **Messenger** — `update_message(message_id, card: CardMessage) -> bool`, symmetric with `send_card`; reuse `TriageCard.bot_message_id`, add `thread_name`; on `False` → `send_card` + re-persist id; v1 patches parent cardsV2 only, hunks left stale, "[Updated]" in header; new `update_card_message` cardsV2-patch helper in `workbench_meta/lib/google_api.py` (ADR 0031).
5. **Diff code changes** — new `diff_version` poll signal → `change_type="code_updated"`; two-tier regen: code change → full re-fetch + regenerate hunks; status/CI/comment → reuse stored hunks, refresh copy only (ADR 0032).
6. **Config** — single minor bump 0.3.0 → 0.4.0 carrying both `presentation:` (A) and per-source `change_detector:` (B).

## Unified phases
1. Shared foundational (models, Messenger ABC, store methods + migration, SourceAdapter base)
2. Presentation layer (Feature A foundational)
3. Change-monitoring engine (Feature B foundational; merged `generate_card`, `_fire_retriage` with presenter + two-tier gate)
4. Meta overlay (DiffEnricher + diff_version, change-aware DiffCardContentGenerator, DiffCardPresenter, change detectors, adapters, gchat cardsV2 + cardsV2-patch); **starts with the `meta phabricator.diff` schema verification task**
5. UI (detail view + "what changed since last triage" callout, DiffHunks, route, type-gen)
6. Cross-cutting (combined config/version, CONTEXT.md glossary, memory-caps doc fix)

## Artifacts Produced
- Combined plan: `docs/auto-plan/plans/2026-06-08-combined-diff-cards-and-change-monitoring.md` (PASS)
- Integration ADRs: `docs/adr/0030`, `0031`, `0032`
- State: `docs/auto-plan/reports/2026-06-08-combined-diff-cards-and-change-monitoring-state.json`
- The two source plans/specs remain as the per-feature design backing (referenced, not duplicated)

## Notes for execution
- Build top-to-bottom; unchanged tasks point to the source plans, integration-changed/new tasks carry complete TDD code.
- Phase 4 is blocked until the `meta phabricator.diff` schema (incl. `diff_version`) is confirmed in the cert-equipped container; fallback is a line-count/files-changed proxy.

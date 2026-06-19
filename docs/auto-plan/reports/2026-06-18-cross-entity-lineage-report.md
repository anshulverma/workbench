# Planning Report: cross-entity-lineage

## Execution Stats
- Mode: `--skip-plan` (brainstorm → grilled spec + ADRs; no implementation plan)
- Sub-agents spawned: 5 (3 grillers, 1 spec writer, 1 spec reviewer)
- Grilling iterations: 1 (3 branches converged in one round)
- Questions auto-answered: ~20 (from codebase + settled decisions)
- Questions asked to user: 6 (3 Phase-0.5 framing + 3 Phase-2 product calls)
- Branches explored: 3
- Conflicts detected: 0 (one grill error self-corrected by the writer: `extract_items`/`score_and_decide` DO have context wrappers)

## Decision Log
| # | Question | Answer | Source |
|---|----------|--------|--------|
| 1 | Linkage mechanism | Generic path-keyed `entity_item_links` join table | user |
| 2 | Schema | id PK; entity_type TEXT; entity_id BIGINT NULL; item_id FK CASCADE; item_path; correlation_id; two partial unique indexes; migration 015 | griller+writer |
| 3 | entity_type values | llm_call, interaction, plan, triage_card, message (extensible) | griller |
| 4 | Linkage principle | Link to exactly consumed item(s) at true depth | user |
| 5 | Recording paths | call-time (item_paths) + post-persist (correlation_id) | griller |
| 6 | Bug fixes | stamp paths in existing wrappers; fix generate_card; fix batched scoring | griller+writer |
| 7 | Scoring linkage | Add correlation_id → link to scored children | user |
| 8 | Urgency linkage | Include; plumb roots out of enqueue | user |
| 9 | Messages | New durable message-audit entity | user |
| 10 | Existing FK entities | Keep columns; UNION in surfacing; don't migrate | griller |
| 11 | Shared helper | `EntityLinkStore` one-line `record()` | griller+pref |
| 12 | Retention cascade | Pruners call `unlink_entity` | griller |
| 13 | Surfacing API | `GET /api/items/{path}/related?subtree=` | griller |
| 14 | UI | "What touched this" section + `useItemRelated` | griller |
| 15 | Backfill | None — start fresh | griller |
| 16 | LlmCallRecord.items | Keep denormalized; table is source of truth | griller |

## Branch Tree
```
cross-entity-lineage (3 branches)
├── b1 link mechanism / schema ............ [user + griller]  resolved
├── b2 LLM-call linkage & timing .......... [griller + user]  resolved  (correlation_id ADR)
└── b3 other entities + helper + surfacing  [griller + user]  resolved  (message entity, /related API, UI)
```

## Key Findings
1. **Messenger messages aren't persisted** today (ephemeral `CardMessage` render) — user chose to add a **durable message-audit entity**.
2. **Latent bugs** surfaced for the implementation pass: `extract_items` & `score_and_decide` stamp no `item_paths` (record empty `items`); `generate_card` stamps none though the path is available; the batched scoring call mis-stamps `(root.path,)`.
3. **Async record ids** force a **correlation_id** mechanism for calls whose consumed items are minted after the call (relevance/urgency scoring) — ADR 0064.
4. The correlation_id flow needs **two partial unique indexes** (id-known vs correlation-only) to dedupe correctly — captured in the spec.

## Artifacts Produced
- Spec: `docs/auto-plan/specs/2026-06-18-cross-entity-lineage-design.md`
- ADR 0063: `docs/adr/0063-entity-item-links-join-table.md`
- ADR 0064: `docs/adr/0064-correlation-id-llm-call-linkage.md`
- State: `docs/auto-plan/reports/2026-06-18-cross-entity-lineage-state.json`
- (No implementation plan — `--skip-plan`)

## Next Step
Re-invoke auto-plan on the spec to produce + harden an implementation plan, then subagent-driven execution (same flow as the item-lineage feature). Memory: [[project-cross-entity-lineage]], [[preference-lineage-extensible]].

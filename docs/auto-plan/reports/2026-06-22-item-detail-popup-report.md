# Planning Report: Item-Detail Popup (hardening)

Mode: auto-plan `--harden` over the existing spec + plan.
**Convergence: `converged` after 2 passes** (instability 9 → 0).

## Hardening Passes

| Pass | Material? | Instability | Key changes | Snapshot |
|------|-----------|-------------|-------------|----------|
| 1 | yes | 9 | Rewrote the backend test off a nonexistent `client_app` fixture to the real `stores` + `ASGITransport` + `create_root(Item(...))` pattern (raw INSERT violated `items.path NOT NULL`/identity id); made `processing_log→FunnelStage` a per-entry mapping (`filterId` from `stage`, etc.) instead of a blind cast; fixed MSW (`SEARCH_RESULTS` real array shape + locally-started `setupServer` + `/api/auth/token`); corrected route-ordering note; documented the `ItemKind` cast + KINDS filter; completed the `ItemDetailBody` import list; grounded the `Search.test.tsx` rework in the real file. | `snapshots/popup-pass-2/` |
| 2 | no | 0 | Convergence check — verified `Item` model fields + enums (`ItemCategory.ACTION_ITEM`, `ItemOrigin.AUTO_INCLUDED`, `Priority.P2`, `ItemStatus.ACTIVE`), `create_root`, the `_row_to_search_item` extraction (byte-for-byte match), `FunnelStage` fields + `funnel-helpers` usage, and all cross-doc symbols/surfaces against the real code. No defect found. | `snapshots/popup-pass-2/` |

Convergence data: `2026-06-22-item-detail-popup-convergence.csv`.

## Carry-forward note (out of scope, not blocking)
The dialog reuses the existing `useItemActions`/`useSnoozeItem` hooks, whose calls
(`POST /api/items/{id}/archive`, `duration_minutes`) may not match the real backend
(`DELETE /api/items/{id}`, `SnoozeBody{hours}`). This is a pre-existing discrepancy in the
reused hooks, not introduced by this feature — worth a separate fix later.

## Artifacts
- Hardened spec: `docs/superpowers/specs/2026-06-22-item-detail-popup-design.md`
- Hardened plan: `docs/superpowers/plans/2026-06-22-item-detail-popup.md`
- Convergence CSV + snapshots under `docs/auto-plan/reports/`.

## Next
Subagent-driven execution of Tasks 1–6 on `feature/item-detail-popup`.

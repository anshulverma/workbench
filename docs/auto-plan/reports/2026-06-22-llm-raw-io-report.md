# Planning Report: Raw LLM Input/Output in the Call Popup (hardening)

Hardening of the pre-existing spec (`docs/superpowers/specs/2026-06-22-llm-raw-io-design.md`)
and plan (`docs/superpowers/plans/2026-06-22-llm-raw-io.md`). Mode: `--harden`,
`--max-passes 10`, `--confidence-threshold low`. Settled design decisions were frozen
and passed as constraints to every pass (no re-litigation).

## Execution Stats
- Hardening passes run: 3 of 10 max (stopped at convergence)
- Sub-agents spawned: 3 hardening-pass agents (opus), each fresh-context with full repo read access
- Convergence: **converged** after pass 2 (instability 0), confirmed stable by an adversarial pass 3
- Questions bubbled up to user: 0 (the one raised in pass 1 was resolved by widening scope, not deferred)
- Material edits applied: pass 1 only

## Convergence

| Pass | Material? | What changed | Verdict |
|------|-----------|--------------|---------|
| 1 | yes (6) | Fixed 4 blind-execution-breaking defects + 2 clarifying notes; added 4th call-site coverage | NOT CONVERGED |
| 2 | no | Independently verified 8 deep concerns against real code (ran anthropic/pydantic to confirm `model_dump(mode="json")` is json-safe; confirmed asyncpg returns JSONB as `str`) | CONVERGED |
| 3 | no | Adversarial edit-by-edit mental execution against the live repo; all anchors match, ordering commit-safe, fixtures function-scoped, JSX in scope | CONVERGED (stable) |

Instability score: 6 → 0 → 0 (see `2026-06-22-llm-raw-io-convergence.csv`).

```
instability  6 |#
             0 |   .   .
               +-----------
                 1   2   3   pass
```

## Material changes applied (pass 1)

1. **Test-helper name collision** — the plan's new `_ctx()` in `test_llm_writer.py` would have
   shadowed the existing module-level `_ctx()` (no `item_paths`) and broken 3 existing tests.
   Renamed to `_ctx_with_item()` (tuple `item_paths`).
2. **Wrong test fixtures (Task 7)** — plan used non-existent `stores, app_client`; corrected to the
   real `(client, app_with_state)` pattern with `@pytest.mark.asyncio` and
   `stores = app_with_state.state.stores`.
3. **Undefined `getIcon` (Task 8)** — `getIcon` is private to `EnricherCard.tsx`; replaced with
   direct `lucide-react` `ChevronRight`/`ChevronDown` added to the existing import block.
4. **Impossible insertion point (Task 8)** — "after the closing `</div>`, still inside the
   container" was self-contradictory; corrected to "immediately before the body grid's closing
   `</div>`".
5. **Incomplete call-site coverage (Task 6)** — added step 3d for `queue_scorer.score_urgency`
   (single-item), the 4th and final real `messages.create` site, so every non-memory LLM call
   carries `raw_request`. Spec section 2 updated to enumerate all four sites.
6. **Clarifying notes** — retry-loop `request` scoping; verified-fixture notes replacing
   read-the-file caveats.

## Verified-clean (passes 2–3, no change needed)

- asyncpg returns JSONB as `str` (no codec) → `_row`'s `isinstance(val, str)` guard is correct and
  matches the `items`/`subcalls` pattern.
- `anthropic==0.104.1` `Message.model_dump(mode="json")` is fully `json.dumps`-safe → no `default=str`
  needed.
- Single-call synthesis fires correctly on the error path (shows the input even on failure); inert
  for existing `_to_llm_record` tests (no regression).
- No existing backend/UI test asserts INSERT arity, `_detail_view` strict schema, or popup
  "Completion" text → dedup + additive columns are safe.
- `_detail_view` is not OpenAPI-generated; hand-written `LLMCallDetailData` is authoritative → no
  `gen:api` step needed.
- Migration `down_revision="015"` correct; per-test `TRUNCATE` makes `list_calls(limit=1)`
  deterministic; each task is independently green at its commit boundary.

## Artifacts
- Hardened spec: `docs/superpowers/specs/2026-06-22-llm-raw-io-design.md`
- Hardened plan: `docs/superpowers/plans/2026-06-22-llm-raw-io.md`
- Snapshots: `docs/auto-plan/reports/snapshots/{baseline,hpass-1,hpass-2,hpass-3}/`
- Convergence CSV: `docs/auto-plan/reports/2026-06-22-llm-raw-io-convergence.csv`

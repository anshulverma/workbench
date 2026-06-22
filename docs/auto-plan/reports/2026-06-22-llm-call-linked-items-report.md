# Planning Report: LLM-Call Linked Items (hardening)

Mode: auto-plan --harden over the existing spec + plan.
**Convergence: `converged` after 2 passes** (instability 6 → 0; budget was 10).

| Pass | Material? | Key changes |
|------|-----------|-------------|
| 1 | yes | Store API is `save_many` (not `save`), returns no id → recover via `list_calls(limit=1)`; documented real LlmCallRecord required fields (started_at/origin/purpose/stage/model/status); corrected "add a router" (renderPage already wraps MemoryRouter); concrete JSX insertion anchor (after header, before system-prompt block, top-level); LinkedItem.path is non-null str. |
| 2 | no | Convergence check — verified save_many signature, list_calls DESC ordering, correlation_id round-trip (save_many→get_by_id), create_root path assignment, frontend anchor + both fixtures + ItemLink props, cross-doc type consistency. No defect. |

Convergence CSV: 2026-06-22-llm-call-linked-items-convergence.csv. Next: subagent-driven execution of Tasks 1-4.

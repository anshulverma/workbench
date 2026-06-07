# Workbench Management Dashboard (full-stack)

Implements the full-stack management dashboard for Workbench. Master task: T274645839.
Spec: `docs/auto-plan/specs/2026-06-05-workbench-dashboard-design.md` · ADRs 0013–0019 · Plan: `docs/auto-plan/plans/2026-06-05-workbench-dashboard.md`.

## What's included (17 ready-for-agent subtasks)
**Backend foundation**
- `redact_secrets` shared util + `/health` `queue_depth()`/`count_dead_letters()` fixes (T274645939)
- Scheduler core: `ingestion_runs` table (migration 004) + per-source cron jobs + per-`source_id` watermark (T274646038)
- `config_writer.py` — ruamel YAML write-back preserving `${oc.env}`/comments (T274646097)

**Backend APIs**
- Stats/aggregation `/api/stats/*` + `GET /api/jobs` list + `/api/activity` (migration 005) (T274646257)
- Source management POST/PATCH/DELETE/poll + targeted hot-reload + `/api/connections` (T274646306)
- Messenger info/edit `GET/PATCH /api/messenger` + hot-swap (T274646332)
- Facts read envelope + curation `DELETE/PATCH /api/memory/facts/{id}` (T274646371)
- Triage web-respond: 409 guard + `/api/triage/confirm` + audit fix (T274646406)

**Frontend** (Tailwind v4 + React 19 + Vite 7 + shadcn/ui + TanStack Query + Recharts, HashRouter)
- Foundation/app shell (T274645984), Overview (T274646470), Ingestion (T274646514), Sources + add/edit form (T274646566), Messenger (T274646603), Knowledge + Fact Curation (T274646648), Triage (T274646673), Action Items migration + Settings (T274646726), accessibility pass (T274646772)

Plus: planning artifacts (CONTEXT glossary, spec, ADRs 0013–0019, plan, report) and a logging safety-net refinement.

## Verification
- Backend: `python -m pytest tests/` → 368 passed (+ Alembic migrations 004/005). 6 pre-existing unrelated failures (test_api items-auth, test_config poll-interval, test_defer_action, test_gchat 48h, test_registry x2) predate this branch.
- Frontend: `cd ui && npm run build` + `npm run test` (vitest) → 85 passed.

## Not included (follow-ups, ready-for-human)
- T274646168 — memory-service Graphiti `DELETE/PATCH /facts/{id}` + tombstone (workbench-meta repo); makes Fact Curation fully live.
- T274646800 — README UI docs + loopback bind (deployment-topology decision).

## Closes
Closes T274645939, T274645984, T274646038, T274646097, T274646257, T274646306, T274646332, T274646371, T274646406, T274646470, T274646514, T274646566, T274646603, T274646648, T274646673, T274646726, T274646772

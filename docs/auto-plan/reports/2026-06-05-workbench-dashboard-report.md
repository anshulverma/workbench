# Planning Report: Workbench Management Dashboard

**Date:** 2026-06-05
**Domains:** frontend, api-design, backend
**Flags:** `--max-iterations 20 --max-depth 10 --harden --max-passes 10`
**Branch:** `docs/dashboard-design`

## Execution Stats

- Sub-agents spawned: **17** — 1 codebase API-inventory (code-search), 10 grillers (7 in iter 1, 3 in iter 2), 1 spec writer, 1 spec reviewer, 1 plan writer, 1 plan reviewer, 1 final cross-artifact reviewer, 1 plan-patch writer.
- Grilling iterations: **2**
- Decisions resolved: **~115** (auto-answered by grillers from user model + codebase + ADRs)
- Questions asked to user: **11** (4 idea-clarification, 4 conflict-resolution, 2 blocker-resolution, 1 commit-strategy) across 4 batched prompts
- Branches explored: **13 initial + 9 discovered = 22**
- Max depth reached: **3**
- Conflicts detected: **5** (all resolved by user decision in iter 1)
- Review passes: spec 1 (FAIL→fixed→PASS), plan 1 (FAIL→fixed→PASS), final 1 (FAIL→fixed→PASS)

## What's Being Built

A professional, full-stack management dashboard for Workbench (React 19 + Vite 7 + Tailwind v4 + shadcn/ui, dark-mode, HashRouter, TanStack Query, Recharts) replacing today's single Action-Items list. It surfaces ingestion-per-source, source management (add/edit/enable-disable/delete/poll with **config write-back to YAML + targeted hot-reload**), the configured messenger (view + edit), and learned facts (view + curate), plus queue/job health, triage response, and a settings page. Because most data had no backend endpoint, the plan is full-stack: new `/api/stats/*` aggregation, `ingestion_runs` tracking, per-source cron scheduling, messenger/facts endpoints, and a memory-service fact-curation contract.

## Key Decisions (selected)

| # | Question | Answer | Source |
|---|----------|--------|--------|
| 1 | "graymem" naming | Typo — product is "Workbench" | user |
| 2 | Scope | Full-stack (UI + new backend endpoints) | user |
| 3 | UI stack | shadcn/ui + Tailwind v4, dark, sidebar, Recharts | user |
| 4 | Library versions | Latest: React 19, Vite 7, Tailwind v4, react-router 7, TanStack Query v5, Recharts 3, Zod 4 | user |
| 5 | Source activation | Write back to `config.yml` (ruamel round-trip) **and** hot-reload at runtime | user |
| 6 | Per-source stats storage | New `ingestion_runs` table | user (rec) |
| 7 | Scheduling | Real per-source cron jobs + per-`source_id` watermarks | user |
| 8 | Write scope | Full management incl. dead-letter retry/purge, triage respond, messenger edit, facts curation | user |
| 9 | Facts curation | Build end-to-end incl. memory-service mutation + tombstones (Graphiti) | user |
| 10 | Web triage | Numbered + free-text with web-native confirmation + 409 guard | user |
| 11 | Routing | HashRouter (no server catch-all) | griller (ADR 0018) |
| 12 | Data layer | TanStack Query v5 + openapi-typescript codegen | griller |
| 13 | Secrets | Never in DB/YAML values; sources reference connections / ambient gh; allowlist-on-output redaction | griller (ADR 0017) |
| 14 | Read empty-states | 200 + envelope, never 5xx for "not configured" | griller (ADR 0016) |
| 15 | Auth | Existing `/api/auth/token` exempt works; recommend loopback bind | griller (ADR 0017) |

## Branch Tree

```
Workbench Management Dashboard (13 branches, 9 discovered)
├── Backend [api-design/backend]
│   ├── B1 Stats & aggregation API ............. [griller] → ADR 0015
│   │   └── /health bug-fixes (get_depth, dead-letter scan) [discovered]
│   ├── B2 Source-creation API + secrets ....... [user conflict] → ADR 0013
│   │   ├── Config write-back to YAML (ruamel) [discovered, iter2] → ADR 0013
│   │   ├── Stable source identity / id-in-YAML [discovered]
│   │   └── app.state.sources mutation safety [discovered]
│   ├── B3 Messenger-info + facts read API ...... [griller] → ADR 0016
│   │   └── Memory "list all facts" contract [discovered]
│   ├── B4 Job/activity history API ............. [griller]
│   ├── Per-source cron scheduler ............... [user] → ADR 0014
│   │   ├── Watermark redesign (per source_id) [discovered] → ADR 0014
│   │   └── Manual-vs-scheduled poll concurrency [discovered]
│   ├── Facts curation write path .............. [user] → ADR 0019
│   │   └── Memory-service mutation+tombstone (workbench-meta) [discovered, blocked-external]
│   └── Triage web-respond (409 + confirm) ...... [user]
├── Frontend [frontend]
│   ├── F1 App shell / routing / shadcn ......... [griller] → ADR 0018
│   ├── F2 Data layer (TanStack Query) .......... [griller]
│   ├── F3 Overview page ........................ [griller]
│   ├── F4 Sources page + add-source form ....... [griller]
│   ├── F5 Ingestion-activity page .............. [griller]
│   ├── F6 Messenger page (view+edit) ........... [griller]
│   ├── F7 Knowledge/facts page (view+curate) ... [griller]
│   └── Tailwind v4 / React 19 migration ........ [user, S10]
└── Cross-cutting [observability/security]
    ├── X1 Security / secrets / auth / deploy ... [griller] → ADR 0017
    │   └── Server bind address / Podman topology [discovered]
    └── X2 Hardening (states, a11y, testing) .... [griller, --harden]
```

(Graphviz source: `2026-06-05-workbench-dashboard-tree.dot`)

## Conflicts Resolved

1. **Source activation** — hot-reload vs restart vs PATCH-only → user chose YAML write-back + hot-reload (both).
2. **Per-source stats storage** — `ingestion_runs` table vs PipelineJob attribution vs columns → `ingestion_runs` table.
3. **Delete sources** — in/out of v1 → in (DB+YAML).
4. **Per-source schedule** — global interval vs real cron → real per-source cron.
5. **Mutation scope** — read-only vs full → full management (incl. messenger edit + facts curation).

## Preference Updates

- `preference-frontend-dashboard-stack` (feedback, frontend) — prefers shadcn/ui + Tailwind + dark mode + latest library versions for dashboards.
- `preference-config-write-back` (feedback, backend) — wants UI config changes written back to YAML AND hot-reloaded (YAML stays source of truth), not DB-only.

## Artifacts Produced

- `CONTEXT.md` — Management Dashboard glossary section + reinstated dropped concepts (commit f3d3941)
- `docs/auto-plan/specs/2026-06-05-workbench-dashboard-design.md` (commit a89726f, e946b25)
- `docs/adr/0013`–`0019` (7 ADRs) (commit e78aac8)
- `docs/auto-plan/plans/2026-06-05-workbench-dashboard.md` — 25 TDD tasks, 6 phases (commit 50cd079, e946b25)
- `docs/auto-plan/reports/2026-06-05-workbench-dashboard-{state.json,report.md,tree.dot}`

## Notes / Follow-ups

- **Cross-repo:** memory-service `DELETE/PATCH /facts/{id}` + tombstone + list-all (Graphiti) is a **workbench-meta** task (ADR 0019); create a Meta Task with `--owner=anshulverma`.
- **Out of scope (v1):** connection creation/OAuth via UI; entity/relationship graph view; bulk dead-letter actions; multi-user; per-fact confidence/categories.
- Config `version` bumps to `0.4.0` (adds `source.id`).

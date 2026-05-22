# Workbench Phase 1 — Implementation Plan

## Context

Build an open-source Claude Code plugin + API server + PostgreSQL database that serves as a personal intelligence feed. Ingests from multiple pluggable sources (meeting notes, email, social feeds, tasks, code reviews), filters noise adaptively via a preference learning system, and triages items through rich interactive cards sent via Messenger (WhatsApp/Discord/Google Chat).

Full spec at: `specs/2026-05-21-workbench-design.md`

## Key Decisions

- **Architecture**: Claude Code plugin → FastAPI API server → PostgreSQL (all containerized)
- **Deployment**: Docker + docker-compose (compatible with Podman)
- **Provider interfaces**: DocReader, WorkbenchStore, Messenger, SourceAdapter, ContextEnricher — all pluggable
- **Filter**: Adaptive noise filter with 3-layer preference learning (interaction log → preference summary → informed decisions)
- **Triage**: Rich triage cards with source-specific action options, not simple yes/no
- **Email**: Gmail adapter with per-account filter rules, starts empty and learns
- **Enrichment**: Configurable depth (shallow/deep) with budget controls and trace logging
- **Database**: PostgreSQL from day one (no flat file storage for state)

## Implementation Sequence

1. **Docker stack**: Dockerfile for FastAPI server, docker-compose.yml with API + PostgreSQL
2. **Database schema**: Alembic migrations for all tables (items, plans, triage_cards, interaction_log, filter_rules, email_filters, preferences, enrichment_trace, processed, config)
3. **API server**: FastAPI app with all endpoints (items, triage, plans, preferences, filter-rules, interactions, enrichment, config, health)
4. **API client**: `api_client.py` — thin HTTP client for the plugin to talk to the API
5. **Plugin scaffold**: `plugin.json`, directory structure, `config.json`, `providers.json`
6. **Provider interfaces**: Base classes for DocReader, WorkbenchStore, Messenger, SourceAdapter, ContextEnricher
7. **Core scripts**: `doc_reader.sh`, `doc_sections.py`, `doc_export.sh`, `messenger.sh`, `messenger_triage.py`, `state.py`, `enrich.py`, `preferences.py`
8. **Source adapter stubs**: `meetings.sh`, `social.sh`, `tasks.sh`, `code_review.sh` (stubs) + `email.sh` (Gmail implementation)
9. **`/workbench:setup` command**: Deploy containers, run migrations, configure providers, register crons, test Messenger
10. **`/process` command**: Core pipeline (DocReader fetch → Claude extraction → filter → enrich → triage card → Messenger)
11. **Cron prompt templates**: Source watcher, triage response checker, daily cleanup with self-healing
12. **`/workbench:status` command**: Container health, API status, crons, pending items, budget usage
13. **`/workbench:cleanup` command**: Manual prune trigger
14. **`/workbench:sources` command**: Source management
15. **`/workbench:triage` command**: CLI-based triage for pending items
16. **End-to-end testing** per verification section in spec

## Verification

1. `/workbench:setup` — containers start, DB migrates, crons register, Messenger test message sent
2. `/process` with pasted text — triage card sent via Messenger with correct options
3. Respond to triage card — item appears in DB with correct priority
4. `/process` with Google Doc link — doc fetched and processed
5. Source watcher cron — picks up new items from enabled sources
6. "Never" response — filter rule created in DB
7. `/workbench:cleanup` — completed items archived, stale items flagged
8. `/workbench:status` — all systems healthy
9. Enrichment trace — budget settings respected
10. `preferences.py` digest — incremental read from last cursor

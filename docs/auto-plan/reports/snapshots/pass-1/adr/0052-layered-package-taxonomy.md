# ADR 0052: Layered package taxonomy for `src/workbench/`

**Status:** Proposed
**Date:** 2026-06-09

## Context
`src/workbench/` had 13 loose cross-cutting modules at the package root and a `providers/` folder polluted with a non-provider (`_plugboard.py`). Location no longer communicated role; locality was low.

## Decision
Group every module into role-based packages: `domain/` (entity vocabulary), `config/`, `runtime/` (ASGI assembly), `telemetry/` (emitted operational signals), `providers/` (pluggable impls + the registry, with `memory/` unified in), `pipeline/`, `storage/`, `api/`, `mcp/`, `migrations/`. A single placement rule (decide by primary role) governs where any new module goes, and each package's `README.md` records its slice of that rule. No module lives at the package root except `__init__.py` and `__main__.py`.

## Alternatives
- **Keep loose root modules** — rejected: the status quo, low locality.
- **`observability/` / `monitoring/`** for telemetry — rejected: verbose / generic; "telemetry" precisely names emitted operational signals.
- **Rename provider interface subfolders** — rejected: contradicts the glossary's "Provider" term for zero gain.
- **`adapters/` instead of `providers/`** — rejected: CONTEXT.md pins "Provider"; "adapter alone" is on the avoid-list.

## Consequences
Most provider/pipeline/storage `class:` and import paths are unchanged; the churn concentrates in the domain rename (0053), memory unification, and the four relocations into new packages. Telemetry depends on `providers/llm/plugboard.py` for the call-record type (acceptable: the type is Prometheus-free).

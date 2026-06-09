# providers/enrichment

**Purpose:** ContextEnricher implementations behind the `ContextEnricher` base
interface — the per-source enrichers that add context to extracted items.

**What belongs here:** the `ContextEnricher` base interface (`base.py`), the
composite enricher (`composite.py`, fans out to per-source enrichers), concrete
enrichers — `github.py`, `gmail.py`, `gcalendar.py`, `gchat.py` — and the
`stub.py` no-op enricher.

**What does NOT belong here:** other provider families, the enrichment
orchestration stage or budget controls (`pipeline/enrichment.py`), or enrichment
trace persistence (`storage/`).

**Update this README when** you add a new KIND of code here (a new enricher or
the composite strategy) — not for every new file.

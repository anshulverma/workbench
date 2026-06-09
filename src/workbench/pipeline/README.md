# pipeline

**Purpose:** the processing pipeline — the orchestration stages that move
content from raw ingestion to a triage card.

**What belongs here:** pipeline stage modules — `extraction.py` (LLM
extraction), `filter.py` (adaptive noise filter), `enrichment.py` (context
enrichment orchestration), `triage.py` (triage-card assembly), `scheduler.py`
(ingestion scheduling), `worker.py` (queue worker loop), `engine.py` (the
pipeline engine that ties stages together), `presenter.py` (Card Presenter),
`content_generator.py` (Card Content Generator), `debounce.py` (DebounceManager),
and `change_context.py` (ChangeContext building for re-triage).

**What does NOT belong here:** provider implementations (`providers/`), domain
models (`domain/`), persistence (`storage/`), or HTTP routes (`api/`). Stages
orchestrate; they call into providers and stores rather than embedding those
concerns.

**Update this README when** you add a new KIND of code here (a new pipeline
stage) — not for every tweak to an existing stage.

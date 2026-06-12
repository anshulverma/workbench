# domain

**Purpose:** the entity vocabulary of Workbench — the pydantic models and enums
that form the shared domain language. Replaces the former single
`workbench.models` module. Import everything as `from workbench.domain import X`;
`__init__.py` re-exports the full public surface (this is the package interface,
not a back-compat shim — there is no `workbench.models`).

**Submodule map:**

- `enums.py` — dependency-free leaf enums: Priority, ItemStatus, ItemCategory, ItemOrigin, EntityType, ActionCategory, JobStatus, JobTrigger, QueueEntryStatus.
- `items.py` — RawItem, ExtractedItem, Item, ItemUpdate, ItemFilters.
- `pipeline.py` — PipelineJob, IngestionQueueEntry, IngestionRun.
- `triage.py` — TriageOption, TriageCard, TriageResponse, TriageResponseResult, CardLink, CardSection, ThreadHunk, CardMessage, ChangeContext.
- `diff.py` — DiffMetadata, DiffRisk, DiffHunkSection, DiffCardContent.
- `feedback.py` — FeedbackCorrection, FilterTuningTask.
- `filters.py` — FilterRule (extended with prompt, sources, confidence, origin, matched, enabled, label, order_index).
- `preferences.py` — InteractionEntry, PreferenceSummary, Fact, EntityKnowledge, Relationship, SystemAction, UserTodo, InterpretedResponse.
- `enrichment.py` — EnrichmentTrace, TraceFilters, EnrichmentBudget, EnricherConfig, LoopBackConfig.
- `sources.py` — SourceRelevanceConfig, SourceConfig, SourceConfigUpdate.
- `plans.py` — Plan, PlanFilters, PlanUpdate.

**Update this README when** you add a new kind of domain model (and add its class
to the relevant submodule's `__all__`).

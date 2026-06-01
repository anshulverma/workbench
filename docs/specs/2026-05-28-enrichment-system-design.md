# Enrichment System Design

## Overview

Replace the current single-enricher stub with a multi-enricher orchestration system. Items flowing through the pipeline get enriched with contextual data from multiple sources — diffs, tasks, org charts, docs, etc. An orchestrator coordinates detection, dispatch, budget management, chaining, and result merging.

## Architecture

```
ExtractedItem
  │
  ▼
EnrichmentOrchestrator (implements ContextEnricher)
  │
  ├── 1. Depth Resolution
  │     config defaults + source-type overrides + priority auto-upgrade
  │
  ├── 2. Budget Initialization
  │     shared pool: max_calls, max_seconds
  │
  ├── 3. Entity Detection (pass 0)
  │     ├── RegexEntityDetector (always runs, zero cost)
  │     └── LLMEntityDetector (conditional, for rich content)
  │     → EntityManifest (list of EntityRef)
  │
  ├── 4. Enrichment Loop (passes 1..max_chain_depth)
  │     ├── Group pending entities by type
  │     ├── Dispatch to registered enrichers (concurrent)
  │     ├── Collect results + discovered entities
  │     ├── Dedup against already-enriched entities
  │     └── Repeat until no new entities or budget exhausted
  │
  ├── 5. Result Assembly
  │     → EnrichmentResult (flat entity stores + discovery graph)
  │
  └── 6. Trace Logging
        → EnrichmentTrace written to storage
```

## Internal / External Split

The enrichment system is split into two layers:

**Framework layer (`src/workbench/enrichment/`)** — generic orchestration, interfaces, models, detection infrastructure. No knowledge of specific entity types or data sources. Defines `Enricher` ABC, `BaseContext`, `EntityRef`, `EnrichmentOrchestrator`, `BudgetTracker`, `EntityDetector`. The regex detector takes patterns as config; the LLM detector takes prompts as config.

**Provider layer (`src/workbench/providers/enrichment/`)** — concrete enricher implementations for specific entity types. Each enricher owns its data source. Contains typed context models, regex patterns for entity detection, and API-calling logic. Installed as separate packages or bundled with the main repo for common platforms.

## Core Interfaces

### Enricher (ABC)

```python
class Enricher(ABC):
    entity_type: str

    async def enrich(
        self,
        entities: list[EntityRef],
        depth: str,
        budget: BudgetTracker,
    ) -> EnricherOutput:
        ...

    async def close(self) -> None:
        ...
```

Each enricher handles one entity type. Receives a list of entity references, a depth setting, and a shared budget tracker. Returns `EnricherOutput` containing typed context objects and optionally discovered entities for chaining.

### EntityDetector (ABC)

```python
class EntityDetector(ABC):
    async def detect(
        self,
        content: str,
        budget: BudgetTracker | None = None,
    ) -> list[EntityRef]:
        ...
```

Two implementations:
- `RegexEntityDetector` — takes a list of compiled patterns with entity type mappings. Always runs, zero cost.
- `LLMEntityDetector` — uses an LLM to extract implicit entity references from unstructured text. Conditional: only runs for rich content (above a character threshold) when budget allows.

### EnrichmentOrchestrator

Implements the existing `ContextEnricher` interface for backward compatibility with the pipeline engine. Internally coordinates detection, dispatch, chaining, budget management, and result merging.

```python
class EnrichmentOrchestrator(ContextEnricher):
    def __init__(
        self,
        registry: EnricherRegistry,
        regex_detector: RegexEntityDetector,
        llm_detector: LLMEntityDetector | None,
        config: EnrichmentConfig,
        trace_store: EnrichmentTraceStore | None,
    ): ...

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget,
    ) -> dict:
        # Internally produces EnrichmentResult, serializes to dict
        # for backward compatibility with generate_card()
        ...
```

## Data Models

### Framework Layer (`src/workbench/enrichment/models.py`)

```python
class EntityRef(BaseModel):
    type: str              # opaque string, defined by enricher registrations
    id: str                # entity identifier
    source: str            # "regex" or "llm"
    confidence: float      # 1.0 for regex, 0.0-1.0 for LLM

class EntityKey(BaseModel):
    type: str
    id: str

class EntityManifest(BaseModel):
    entities: list[EntityRef]
    detection_method: str       # "regex", "llm", "regex+llm"
    detection_time_ms: int

class DiscoveryEdge(BaseModel):
    source: EntityKey           # entity being enriched when discovery happened
    target: EntityKey           # entity that was discovered
    enricher: str               # which enricher made the discovery
    chain_depth: int            # 0 = detected from item, 1+ = discovered during enrichment
    relation: str               # "links_to", "authored_by", "managed_by", "reviewer", etc.
    confidence: float           # 1.0 for explicit, lower for inferred

class BaseContext(BaseModel):
    entity_key: EntityKey

class CommentContext(BaseModel):
    author: str
    content: str
    created_at: str

class EnricherOutput(BaseModel):
    enricher_type: str
    contexts: list[BaseContext]           # one per enriched entity
    discovered_entities: list[EntityRef]  # new entities found during enrichment
    discovery_edges: list[DiscoveryEdge]  # edges from enriched entities to discovered entities

class EnrichmentMetadata(BaseModel):
    total_calls: int
    total_time_ms: int
    chain_depth_reached: int
    enrichers_invoked: list[str]
    failed_enrichers: list[str]
    budget_exhausted: bool
    detection_method: str

class EnrichmentResult(BaseModel):
    contexts: dict[str, list[BaseContext]]   # keyed by entity type
    discovery_edges: list[DiscoveryEdge]
    item_key: EntityKey
    metadata: EnrichmentMetadata

    def get_contexts(self, entity_type: str, model: type[T]) -> list[T]:
        """Type-safe accessor for consumers that know the concrete model."""
        ...
```

### Discovery Graph

Entities are stored flat and deduplicated. The discovery graph captures how each entity was found:

```
depth 0: entity_detector detects PR #123 from item
         → DiscoveryEdge(source=item, target=diff:123, enricher="entity_detector",
                         depth=0, relation="links_to", confidence=1.0)

depth 1: DiffEnricher enriches PR #123, discovers Alice is author
         → DiscoveryEdge(source=diff:123, target=person:alice, enricher="diff",
                         depth=1, relation="authored_by", confidence=1.0)

depth 2: OrgChartEnricher enriches Alice, discovers Bob is manager
         → DiscoveryEdge(source=person:alice, target=person:bob, enricher="org",
                         depth=2, relation="managed_by", confidence=1.0)
```

Every entity is reachable by walking `discovery_edges` from `item_key`. The `enricher` field records what found it, `relation` records why, `chain_depth` records when.

## Budget Management

A shared `BudgetTracker` pool replaces the current `EnrichmentBudget` model.

```python
class BudgetTracker:
    max_calls: int          # default: 15
    max_seconds: int        # default: 60
    calls_used: int
    start_time: float

    def can_proceed(self) -> bool: ...
    def record_call(self) -> None: ...
    def remaining_seconds(self) -> float: ...
    def snapshot(self) -> dict: ...       # returns {calls_used, time_elapsed_ms, budget_exhausted}
```

- The orchestrator creates one `BudgetTracker` per item.
- All enrichers share the same tracker instance.
- Safe for concurrent use within a single asyncio event loop (enrichers run via `asyncio.gather`).
- Enrichers check `budget.can_proceed()` before each API call.
- Each enricher call is wrapped in `asyncio.wait_for()` using `budget.remaining_seconds()`.

## Depth Resolution

The orchestrator resolves enrichment depth per item:

1. Check for explicit `depth_override` (for API-triggered enrichment).
2. Look up `config.depth_by_source[item.source_type]` for source-type defaults.
3. Fall back to `config.default_depth` (default: `"shallow"`).
4. If `item.priority_score > config.auto_upgrade_threshold`, upgrade to `"deep"`.

Depth affects enricher behavior:
- **shallow**: basic metadata only (title, status, author).
- **deep**: full context (comments, reviewers, test results, related items, doc summaries, org chains).

## Chaining

Enrichers can discover new entities during enrichment (e.g., a DiffEnricher discovers the diff author). The orchestrator runs multiple passes:

1. Pass 0: Entity detection from item content.
2. Pass 1: Enrich detected entities. Collect discovered entities.
3. Pass 2..N: Enrich newly discovered entities. Repeat.
4. Stop when: no new entities discovered, budget exhausted, or `max_chain_depth` reached.

`max_chain_depth` is configurable in YAML (default: 2). Deduplication prevents re-enriching an entity already processed in a prior pass.

## Enricher Registry

Maps entity type strings to `Enricher` instances. Built from YAML config at startup.

```python
class EnricherRegistry:
    def register(self, entity_type: str, enricher: Enricher) -> None: ...
    def get(self, entity_type: str) -> Enricher | None: ...
    def all_types(self) -> list[str]: ...
    async def close_all(self) -> None: ...
```

Adding a new enricher requires: writing the class, adding a YAML entry. No orchestrator code changes.

## Entity Detection

### RegexEntityDetector

Takes a list of pattern configs (compiled regex + entity type + optional ID group name). Runs all patterns against item content. Returns `EntityRef` entries with `source="regex"` and `confidence=1.0`.

Regex patterns are defined per deployment in the provider layer. For example, a GitHub deployment might detect `#\d+` (issues/PRs), `@\w+` (people), and URL patterns for docs.

### LLMEntityDetector

Uses an LLM (Haiku for cost) to extract implicit entity references from rich content. Triggered when:
- Item content exceeds `rich_content_threshold` characters (configurable, default: 500).
- Budget has remaining calls.

Returns `EntityRef` entries with `source="llm"` and `confidence` based on the LLM's assessment.

Results are merged with regex results. Regex entities take precedence for deduplication (higher confidence).

## Error Handling

- **Enricher failure isolation**: If an enricher throws, the orchestrator catches the exception, logs it, adds the enricher to `metadata.failed_enrichers`, and continues with remaining enrichers. Partial results are preserved.
- **Budget enforcement**: `BudgetTracker.can_proceed()` is checked before each API call. When exhausted, enrichers return what they have. `metadata.budget_exhausted` is set to `true`.
- **Per-enricher timeout**: Each enricher dispatch is wrapped in `asyncio.wait_for()` using remaining budget time. Prevents a single slow enricher from consuming the entire time budget.
- **Detection fallback**: If LLM detection fails, regex results are used alone. If regex fails, the item proceeds with an empty manifest (same behavior as current `StubEnricher`).

## YAML Config

```yaml
enrichment:
  orchestrator:
    max_chain_depth: 2
    default_depth: shallow
    auto_upgrade_threshold: 0.8
    depth_by_source:
      incident: deep
      diff: shallow
      email: shallow

  budget:
    max_calls: 15
    max_seconds: 60

  detection:
    regex:
      class: workbench.providers.enrichment.patterns.DefaultRegexPatterns
    llm:
      class: workbench.providers.llm.anthropic.AnthropicLLM
      model: claude-haiku-4-5-20251001
      rich_content_threshold: 500

  enrichers:
    diff:
      class: workbench.providers.enrichment.diff.DiffEnricher
    person:
      class: workbench.providers.enrichment.org.OrgChartEnricher
      snapshot: true
    doc:
      class: workbench.providers.enrichment.doc.DocEnricher
```

Validated by a typed `EnrichmentConfig` pydantic model in `config.py`.

## File Layout

```
src/workbench/
├── enrichment/                              # Framework layer (generic)
│   ├── __init__.py
│   ├── base.py                              # Enricher ABC, EntityDetector ABC
│   ├── models.py                            # EntityRef, EntityKey, EntityManifest,
│   │                                        #   DiscoveryEdge, BaseContext, CommentContext,
│   │                                        #   EnricherOutput, EnrichmentResult,
│   │                                        #   EnrichmentMetadata
│   ├── orchestrator.py                      # EnrichmentOrchestrator (implements ContextEnricher)
│   ├── registry.py                          # EnricherRegistry
│   ├── budget.py                            # BudgetTracker
│   └── detection/
│       ├── __init__.py
│       ├── regex.py                         # RegexEntityDetector
│       └── llm.py                           # LLMEntityDetector
│
├── providers/enrichment/                    # Provider layer
│   ├── __init__.py
│   ├── base.py                              # Existing ContextEnricher ABC (kept)
│   └── stub.py                              # Existing StubEnricher (kept for testing)
```

Concrete enricher implementations (for specific platforms like GitHub, Phabricator, etc.) live in provider packages — either bundled or installed separately.

## Integration with Existing Code

### pipeline/enrichment.py

The `enrich_item()` function continues as the pipeline's entry point. It now receives the orchestrator (which implements `ContextEnricher`) and the orchestrator internally returns `EnrichmentResult`. The function serializes the result to `dict` for backward compatibility with `generate_card()`.

### pipeline/engine.py

Pass `item.priority_score` and `item.source_type` through to enrichment so the orchestrator can resolve depth and decide on LLM detection.

### models.py

- `EnrichmentBudget` replaced or extended by `BudgetTracker` in `enrichment/budget.py`.
- `EnrichmentTrace` extended with `discovery_edges`, `chain_depth_reached`, `failed_enrichers`.

### config.py

Add typed `EnrichmentConfig` pydantic model with sub-models for orchestrator, budget, detection, and enrichers. Replaces the current `dict | None`.

### main.py

At startup, build the `EnrichmentOrchestrator` from config:
1. Create `EnricherRegistry` from `config.enrichment.enrichers`.
2. Create `RegexEntityDetector` from `config.enrichment.detection.regex`.
3. Optionally create `LLMEntityDetector` from `config.enrichment.detection.llm`.
4. Create `EnrichmentOrchestrator` with registry, detectors, config, and trace store.
5. Pass orchestrator to `PipelineEngine` as the `ContextEnricher`.

### API

Add `GET /api/enrichment/trace` endpoint (specified in original design but never implemented). Returns enrichment traces with optional `item_id` and `since` filters.

### Storage

The existing `EnrichmentTraceStore` and `PgEnrichmentTraceStore` are functional. The orchestrator now calls `log_trace()` after each enrichment (currently wired but never called).

The `enrichment_trace` table schema may need a migration to add `discovery_edges` (JSONB), `chain_depth_reached` (int), and `failed_enrichers` (text[]) columns.

## Testing Strategy

- **Unit tests per enricher**: Mock data source, verify context model output and discovered entities.
- **Unit test for orchestrator**: Mock enrichers and detectors, verify dispatch, chaining, budget enforcement, deduplication, error isolation.
- **Unit test for detection**: Verify regex patterns match expected entity types. Verify LLM detector prompt and response parsing.
- **Integration test**: Full pipeline with orchestrator and stub enrichers returning realistic data. Verify enrichment trace is logged, result flows to card generation.
- **Budget exhaustion test**: Verify enrichment stops cleanly when budget is exhausted mid-chain.
- **Failure isolation test**: Verify one enricher throwing doesn't affect others.

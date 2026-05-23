# Step 5: Provider Interfaces (Base Classes)

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [02-database-schema.md](02-database-schema.md)

## Goal

Define abstract base classes for all six provider types. These interfaces establish the contracts that all implementations must follow.

## Files to Create

```
server/
  providers/
    __init__.py
    llm/
      __init__.py
      base.py                -- LLM provider interface
    doc_reader/
      __init__.py
      base.py                -- DocReader interface
    doc_export/
      __init__.py
      base.py                -- WorkbenchStore/export interface
    messenger/
      __init__.py
      base.py                -- Messenger interface
    source/
      __init__.py
      base.py                -- SourceAdapter interface
    enrichment/
      __init__.py
      base.py                -- ContextEnricher interface
    registry.py              -- provider registry for runtime lookup
```

## Interface Definitions

### LLMProvider

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    async def extract(self, raw_text: str, source_type: str) -> ExtractedItems:
        """Extract structured items from raw text.
        Returns: summary, action_items, plan_seeds, meetings_to_schedule."""

    @abstractmethod
    async def score_relevance(
        self, item: ExtractedItem, preferences: str, filter_rules: list[FilterRule]
    ) -> tuple[int, int]:
        """Score an item for relevance and confidence (0-100 each)."""

    @abstractmethod
    async def generate_triage_card(
        self, item: ExtractedItem, enrichment_context: dict, source_type: str
    ) -> TriageCard:
        """Generate a rich triage card with source-specific options."""

    @abstractmethod
    async def synthesize_preferences(self, digest: PreferenceDigest) -> str:
        """Synthesize a markdown preference summary from the interaction digest."""
```

### DocReader

```python
class DocReader(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this reader can handle the given URL."""

    @abstractmethod
    async def read(self, url: str) -> str:
        """Read the document and return content as markdown."""
```

### DocExporter

```python
class DocExporter(ABC):
    @abstractmethod
    async def export_dashboard(self, workspace_id: UUID, content: str) -> str:
        """Export dashboard markdown. Returns the doc URL."""

    @abstractmethod
    async def create_plan_doc(self, title: str, content: str) -> str:
        """Create a new plan document. Returns the doc URL."""
```

### Messenger

```python
class Messenger(ABC):
    @abstractmethod
    async def send(self, user_identifier: str, message: str) -> str:
        """Send a message. Returns the message ID."""

    @abstractmethod
    async def read_since(self, user_identifier: str, since: datetime) -> list[Message]:
        """Read messages received since the given timestamp."""
```

### SourceAdapter

```python
class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        """Poll for new items. Returns raw items (id, source_type, source_label, raw_text)."""

    @abstractmethod
    def adapter_type(self) -> str:
        """Return the adapter type string (email, meeting, social, task, code_review)."""
```

### ContextEnricher

```python
class ContextEnricher(ABC):
    @abstractmethod
    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget
    ) -> EnrichmentResult:
        """Fetch additional context for an item.
        Returns: context dict, calls_made, time_ms."""
```

## Data Classes

Define Pydantic models for the data types used in provider interfaces:

```python
class RawItem(BaseModel):
    id: str
    source_type: str
    source_label: str
    raw_text: str

class ExtractedItem(BaseModel):
    summary: str
    action_items: list[str]
    plan_seeds: list[str]
    meetings_to_schedule: list[str]
    raw_item: RawItem

class TriageCard(BaseModel):
    summary: str
    context: str
    options: list[TriageOption]

class TriageOption(BaseModel):
    label: str
    action: str  # add_todo, skip, mute_sender, mute_pattern, etc.
    details: dict | None = None

class EnrichmentBudget(BaseModel):
    max_api_calls: int
    max_seconds: int

class EnrichmentResult(BaseModel):
    context: dict
    calls_made: int
    time_ms: int

class PreferenceDigest(BaseModel):
    total_interactions: int
    new_interactions: int
    response_distribution: dict
    top_included_patterns: list[str]
    top_dropped_patterns: list[str]
    recent_interactions: list[dict]

class Message(BaseModel):
    id: str
    text: str
    timestamp: datetime
    sender: str
```

## Provider Registry

A registry that maps provider type + implementation name to a class:

```python
class ProviderRegistry:
    def get_llm(self, name: str) -> LLMProvider: ...
    def get_doc_reader(self, url: str) -> DocReader | None: ...
    def get_doc_exporter(self, name: str) -> DocExporter: ...
    def get_messenger(self, name: str) -> Messenger: ...
    def get_source_adapter(self, adapter_type: str) -> SourceAdapter: ...
    def get_enricher(self, name: str) -> ContextEnricher: ...
```

The registry is initialized at server startup from workspace config and injected into the pipeline engine.

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. All six base classes are importable and have well-defined abstract methods
2. All data classes validate with Pydantic
3. `ProviderRegistry` can register and look up providers by name
4. Attempting to instantiate a base class directly raises `TypeError`
5. A stub implementation of each interface passes type checking

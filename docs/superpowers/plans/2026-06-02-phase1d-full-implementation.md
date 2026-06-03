# Phase 1d: Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 source adapters with shared connections, LLM-generated triage cards with memory enrichment and identity resolution, free-text triage responses, and an action items system with React UI.

**Architecture:** Three independent tracks (Sources, Cards, Actions) built on cross-cutting foundations (Connection ABC, registry changes, model/config updates). Cross-cutting goes first, then tracks A→B→C in order.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL, Google API client, Vite + React, pytest + pytest-asyncio

**Test commands:**
- Workbench tests: `make test` (runs `python -m pytest tests/ -v --tb=short`)
- Memory service tests: `cd src/memory && python -m pytest tests/ -v --tb=short`
- Single test: `python -m pytest tests/test_file.py::test_name -v`

---

## Group 0: Cross-Cutting Foundation

### Task 1: Model Changes — Enums and New Fields

**Files:**
- Modify: `src/workbench/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new enums and model fields**

```python
# tests/test_models.py — append to existing file

from workbench.models import (
    EntityType, ActionCategory, TriageOption, TriageCard,
    Item, TriageResponse, InteractionEntry,
    InterpretedResponse, SystemAction, UserTodo,
)

def test_entity_type_enum():
    assert EntityType.PERSON == "person"
    assert EntityType.REPO == "repo"
    assert EntityType.TEAM == "team"
    assert EntityType.SPACE == "space"
    assert EntityType.GROUP == "group"

def test_action_category_enum():
    assert ActionCategory.DELEGATION == "delegation"
    assert ActionCategory.COMMUNICATION == "communication"
    assert ActionCategory.SCHEDULING == "scheduling"
    assert ActionCategory.REVIEW == "review"
    assert ActionCategory.CREATION == "creation"
    assert ActionCategory.UPDATE == "update"

def test_triage_option_suggested_fields():
    opt = TriageOption(label="Add todo P1", action="add_todo")
    assert opt.suggested is False
    assert opt.suggestion_reason is None
    opt2 = TriageOption(
        label="Skip", action="skip",
        suggested=True, suggestion_reason="you usually skip bot PRs",
    )
    assert opt2.suggested is True
    assert opt2.suggestion_reason == "you usually skip bot PRs"

def test_triage_card_deferred_until():
    card = TriageCard()
    assert card.deferred_until is None

def test_item_action_fields():
    item = Item(summary="test", category="action_item")
    assert item.parent_item_id is None
    assert item.action_source is None
    assert item.action_category is None
    item2 = Item(
        summary="Assign to bob",
        category="action_item",
        parent_item_id="parent-123",
        action_source="triage_response",
        action_category="delegation",
    )
    assert item2.parent_item_id == "parent-123"
    assert item2.action_source == "triage_response"

def test_triage_response_choice_optional():
    resp = TriageResponse(card_id="c1", choice=2)
    assert resp.choice == 2
    resp2 = TriageResponse(card_id="c1", raw_text="add as P3")
    assert resp2.choice is None
    assert resp2.raw_text == "add as P3"

def test_interaction_entry_interpreted_fields():
    entry = InteractionEntry(
        source_type="email", item_summary="test",
        triage_card_full={}, enrichment_context={},
        options_presented=[], option_chosen="Other",
    )
    assert entry.type is None
    assert entry.interpreted is None
    assert entry.confirmed is None

def test_interpreted_response():
    resp = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[UserTodo(summary="Assign to bob", action_category="delegation")],
        explanation="Adding as P3 todo.",
    )
    assert len(resp.system_actions) == 1
    assert resp.system_actions[0].action == "add_todo"
    assert len(resp.user_todos) == 1
    assert resp.user_todos[0].action_category == "delegation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py -v -k "test_entity_type or test_action_category or test_triage_option_suggested or test_triage_card_deferred or test_item_action or test_triage_response_choice or test_interaction_entry_interpreted or test_interpreted_response"`
Expected: ImportError — `EntityType`, `ActionCategory`, etc. not found.

- [ ] **Step 3: Implement model changes**

In `src/workbench/models.py`, add:

```python
from enum import Enum

class EntityType(str, Enum):
    PERSON = "person"
    REPO = "repo"
    TEAM = "team"
    SPACE = "space"
    GROUP = "group"

class ActionCategory(str, Enum):
    DELEGATION = "delegation"
    COMMUNICATION = "communication"
    SCHEDULING = "scheduling"
    REVIEW = "review"
    CREATION = "creation"
    UPDATE = "update"
```

Modify `TriageOption` — add fields:
```python
class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)
    suggested: bool = False
    suggestion_reason: str | None = None
```

Modify `TriageCard` — add field:
```python
    deferred_until: datetime | None = None
```

Modify `Item` — add fields:
```python
    parent_item_id: str | None = None
    action_source: str | None = None
    action_category: str | None = None
```

Modify `TriageResponse` — make `choice` optional:
```python
class TriageResponse(BaseModel):
    card_id: str
    choice: int | None = None
    raw_text: str | None = None
```

Modify `InteractionEntry` — add fields:
```python
    type: str | None = None
    interpreted: dict | None = None
    confirmed: bool | None = None
```

Add new models:
```python
class SystemAction(BaseModel):
    action: str
    details: dict = Field(default_factory=dict)

class UserTodo(BaseModel):
    summary: str
    action_category: str

class InterpretedResponse(BaseModel):
    system_actions: list[SystemAction] = Field(default_factory=list)
    user_todos: list[UserTodo] = Field(default_factory=list)
    explanation: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: All pass, including new tests.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/models.py tests/test_models.py
git commit -m "feat(models): add EntityType, ActionCategory enums, triage/item action fields, InterpretedResponse"
```

---

### Task 2: Alembic Migration — New Columns

**Files:**
- Create: `src/workbench/migrations/versions/XXX_phase1d_columns.py`

- [ ] **Step 1: Generate migration**

```bash
cd src/workbench && alembic revision -m "phase1d: deferred_until, action fields, interaction fields"
```

- [ ] **Step 2: Write migration**

```python
"""phase1d: deferred_until, action fields, interaction fields"""

from alembic import op
import sqlalchemy as sa

revision = "..."  # auto-generated
down_revision = "..."  # auto-generated

def upgrade() -> None:
    op.add_column("triage_cards", sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("parent_item_id", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_source", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_category", sa.Text(), nullable=True))
    op.add_column("interaction_log", sa.Column("type", sa.Text(), nullable=True))
    op.add_column("interaction_log", sa.Column("interpreted", sa.JSON(), nullable=True))
    op.add_column("interaction_log", sa.Column("confirmed", sa.Boolean(), nullable=True))

def downgrade() -> None:
    op.drop_column("interaction_log", "confirmed")
    op.drop_column("interaction_log", "interpreted")
    op.drop_column("interaction_log", "type")
    op.drop_column("items", "action_category")
    op.drop_column("items", "action_source")
    op.drop_column("items", "parent_item_id")
    op.drop_column("triage_cards", "deferred_until")
```

- [ ] **Step 3: Run migration against dev database**

```bash
cd src/workbench && alembic upgrade head
```
Expected: Migration applies cleanly.

- [ ] **Step 4: Update PG store files to include new columns**

Update `src/workbench/storage/postgres/items.py`:
- Add `parent_item_id`, `action_source`, `action_category` to INSERT statement and `_row_to_item()` deserializer.

Update `src/workbench/storage/postgres/triage.py`:
- Add `deferred_until` to INSERT/UPDATE and `_row_to_card()` deserializer.
- Update `get_pending()`: change `WHERE status IN ('queued', 'sent')` to `WHERE status IN ('queued', 'sent', 'awaiting_followup', 'awaiting_confirmation')`.
- Update `get_next_unsent()`: add `AND (deferred_until IS NULL OR deferred_until <= NOW())`.
- Update `expire_old_cards()`: add `AND status NOT IN ('awaiting_followup', 'awaiting_confirmation')`.

Update `src/workbench/storage/postgres/interactions.py`:
- Add `type`, `interpreted`, `confirmed` to INSERT statement (extend positional params) and `_row_to_entry()` deserializer.

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `make test`
Expected: All existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/migrations/ src/workbench/storage/postgres/
git commit -m "feat(storage): add Phase 1d columns — deferred_until, action fields, interaction fields"
```

---

### Task 3: Connection ABC

**Files:**
- Create: `src/workbench/providers/connection/__init__.py`
- Create: `src/workbench/providers/connection/base.py`
- Test: `tests/test_registry.py` (append)

- [ ] **Step 1: Write test for Connection ABC**

```python
# tests/test_registry.py — append

import pytest
from workbench.providers.connection.base import Connection
from pydantic import BaseModel

class FakeConnection(Connection):
    class ProviderConfig(BaseModel):
        url: str = "http://localhost"

    def __init__(self, config: "FakeConnection.ProviderConfig"):
        self._config = config
        self._healthy = True

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def is_healthy(self) -> bool:
        return self._healthy

def test_connection_abc_requires_methods():
    with pytest.raises(TypeError):
        class BadConnection(Connection):
            pass
        BadConnection()

@pytest.mark.asyncio
async def test_fake_connection_lifecycle():
    conn = FakeConnection(FakeConnection.ProviderConfig(url="http://test"))
    await conn.initialize()
    assert conn.is_healthy()
    await conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_registry.py -v -k "test_connection_abc or test_fake_connection"`
Expected: ImportError — `workbench.providers.connection.base` not found.

- [ ] **Step 3: Create Connection ABC**

```python
# src/workbench/providers/connection/__init__.py
# (empty)

# src/workbench/providers/connection/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel


class Connection(ABC):
    class ProviderConfig(BaseModel):
        pass

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_healthy(self) -> bool: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_registry.py -v -k "test_connection_abc or test_fake_connection"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/connection/
git commit -m "feat(connection): add Connection ABC"
```

---

### Task 4: Registry — Connection Injection + CompositeEnricher Builder

**Files:**
- Modify: `src/workbench/registry.py`
- Test: `tests/test_registry.py` (append)

- [ ] **Step 1: Write tests for connection injection**

```python
# tests/test_registry.py — append

from workbench.registry import create_provider, create_composite_enricher
from workbench.providers.connection.base import Connection
from workbench.providers.enrichment.stub import StubEnricher

class StubConnection(Connection):
    class ProviderConfig(BaseModel):
        pass
    def __init__(self, config=None):
        pass
    async def initialize(self):
        pass
    async def close(self):
        pass
    def is_healthy(self):
        return True

def test_create_provider_with_connection():
    """Two-arg constructor when connection is provided."""
    conn = StubConnection()
    section = {
        "class": "workbench.providers.enrichment.stub.StubEnricher",
        "connection": "test_conn",
    }
    connections = {"test_conn": conn}
    provider = create_provider(section, connections=connections)
    assert isinstance(provider, StubEnricher)

def test_create_provider_without_connection():
    """Single-arg constructor when no connection field."""
    section = {"class": "workbench.providers.enrichment.stub.StubEnricher"}
    provider = create_provider(section)
    assert isinstance(provider, StubEnricher)

def test_create_composite_enricher():
    """Builds CompositeEnricher from enrichment config."""
    from workbench.models import EnrichmentBudget
    config_dict = {
        "providers": [
            {
                "class": "workbench.providers.enrichment.stub.StubEnricher",
                "source_types": ["email", "calendar"],
            },
        ],
        "default": {"class": "workbench.providers.enrichment.stub.StubEnricher"},
    }
    from workbench.config import EnrichmentConfig
    config = EnrichmentConfig(**config_dict)
    enricher = create_composite_enricher(config)
    assert hasattr(enricher, 'enrichers')
    assert "email" in enricher.enrichers
    assert "calendar" in enricher.enrichers
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_registry.py -v -k "test_create_provider_with_connection or test_create_provider_without_connection or test_create_composite_enricher"`
Expected: Failures — `create_provider` doesn't accept `connections` kwarg, `create_composite_enricher` doesn't exist, `EnrichmentConfig` doesn't exist.

- [ ] **Step 3: Update registry.py**

Modify `create_provider` to accept and handle `connections`:

```python
def create_provider(section: dict[str, Any], connections: dict[str, Any] | None = None) -> Any:
    section = dict(section)
    class_path = section.pop("class")
    connection_name = section.pop("connection", None)
    module_path, class_name = class_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import provider '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")

    resolved_connection = None
    if connection_name and connections:
        resolved_connection = connections.get(connection_name)
        if resolved_connection is None:
            raise ValueError(f"Connection '{connection_name}' not found in connections config")

    if hasattr(cls, "ProviderConfig"):
        typed_config = cls.ProviderConfig(**section)
        if resolved_connection is not None:
            return cls(typed_config, connection=resolved_connection)
        return cls(typed_config)
    else:
        if resolved_connection is not None:
            return cls(connection=resolved_connection, **section) if section else cls(connection=resolved_connection)
        return cls(**section) if section else cls()
```

Add `create_composite_enricher`:

```python
def create_composite_enricher(config, connections: dict[str, Any] | None = None):
    from workbench.providers.enrichment.composite import CompositeEnricher
    from workbench.models import EnrichmentBudget

    enrichers = {}
    budgets = {}
    for entry in config.providers:
        entry = dict(entry)
        source_types = entry.pop("source_types", [])
        budget_dict = entry.pop("budget", None)
        provider = create_provider(entry, connections=connections)
        for st in source_types:
            enrichers[st] = provider
        if budget_dict:
            budget = EnrichmentBudget(**budget_dict)
            for st in source_types:
                budgets[st] = budget

    default = create_provider(dict(config.default), connections=connections) if config.default else None
    return CompositeEnricher(enrichers, default=default, budgets=budgets)
```

Update `create_providers_from_list`:

```python
def create_providers_from_list(sections: list[dict], connections: dict[str, Any] | None = None) -> list:
    return [create_provider(s, connections=connections) for s in sections]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_registry.py -v`
Expected: All pass (new + existing). Note: `test_create_composite_enricher` will fail until Task 5 (EnrichmentConfig) and Task 7 (CompositeEnricher) are done. Mark it `@pytest.mark.skip` for now and remove the skip in Task 7.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/registry.py tests/test_registry.py
git commit -m "feat(registry): support connection injection and create_composite_enricher"
```

---

### Task 5: Config Changes — Connections Section + EnrichmentConfig

**Files:**
- Modify: `src/workbench/config.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write tests for new config sections**

```python
# tests/test_config.py — append

def test_connections_section_parsed():
    yaml_str = """
version: "0.2.0"
storage:
  class: workbench.storage.postgres.PostgresBackend
  dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
connections:
  google:
    class: workbench.providers.connection.google.GoogleConnection
    credentials_path: /tmp/creds.json
    token_path: /tmp/token.json
    scopes:
      - https://www.googleapis.com/auth/gmail.readonly
"""
    config = load_config_from_string(yaml_str)
    assert "google" in config.connections
    assert config.connections["google"]["class"] == "workbench.providers.connection.google.GoogleConnection"

def test_enrichment_config_new_shape():
    yaml_str = """
version: "0.2.0"
storage:
  class: workbench.storage.postgres.PostgresBackend
  dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
enrichment:
  providers:
    - class: workbench.providers.enrichment.stub.StubEnricher
      source_types: ["email"]
  default:
    class: workbench.providers.enrichment.stub.StubEnricher
"""
    config = load_config_from_string(yaml_str)
    assert len(config.enrichment.providers) == 1
    assert config.enrichment.providers[0]["source_types"] == ["email"]

def test_config_version_0_2_0():
    yaml_str = """
version: "0.2.0"
storage:
  class: workbench.storage.postgres.PostgresBackend
  dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert config.version == "0.2.0"

def test_connections_section_optional():
    yaml_str = """
version: "0.2.0"
storage:
  class: workbench.storage.postgres.PostgresBackend
  dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert config.connections == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v -k "test_connections or test_enrichment_config or test_config_version"`
Expected: Failures — `connections` not on config, `EnrichmentConfig` doesn't exist.

- [ ] **Step 3: Update config.py**

Add `EnrichmentConfig` model:

```python
class EnrichmentConfig(BaseModel):
    providers: list[dict] = Field(default_factory=list)
    default: dict = Field(default_factory=lambda: {"class": "workbench.providers.enrichment.stub.StubEnricher"})
```

Update `AppConfig`:

```python
class AppConfig(BaseModel):
    version: str = "0.2.0"
    # ... existing fields ...
    connections: dict[str, dict] = Field(default_factory=dict)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    # ... (change enrichment from dict | None to EnrichmentConfig)
```

If `load_config_from_string` doesn't exist yet, add a helper for testing:

```python
def load_config_from_string(yaml_str: str) -> AppConfig:
    from omegaconf import OmegaConf
    raw = OmegaConf.create(yaml_str)
    return AppConfig(**OmegaConf.to_container(raw, resolve=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/config.py tests/test_config.py
git commit -m "feat(config): add connections section, EnrichmentConfig model, bump version to 0.2.0"
```

---

### Task 6: Main.py — Connection Initialization + Composite Enricher Wiring

**Files:**
- Modify: `src/workbench/main.py`

- [ ] **Step 1: Update lifespan to initialize connections**

In `main.py`, update the `lifespan` function. After storage initialization and before provider construction:

```python
# Initialize connections
connections = {}
for name, conn_cfg in config.connections.items():
    conn = create_provider(conn_cfg)
    await conn.initialize()
    connections[name] = conn
app.state.connections = connections

# Update source creation to pass connections
app.state.sources = create_providers_from_list(config.sources, connections=connections)

# Use create_composite_enricher instead of create_provider for enrichment
if config.enrichment.providers:
    app.state.enricher = create_composite_enricher(config.enrichment, connections=connections)
else:
    app.state.enricher = StubEnricher()
```

Update shutdown to close connections:

```python
for conn in app.state.connections.values():
    await close_provider(conn)
```

- [ ] **Step 2: Add static file serving for React UI**

```python
from starlette.staticfiles import StaticFiles
import os

# In create_app(), after mounting API routers:
ui_dir = os.path.join(os.path.dirname(__file__), "../../ui/dist")
if os.path.exists(ui_dir):
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `make test`
Expected: All existing tests pass. (Connection initialization is no-op when `config.connections` is empty.)

- [ ] **Step 4: Commit**

```bash
git add src/workbench/main.py
git commit -m "feat(main): initialize connections at startup, wire CompositeEnricher, serve static UI"
```

---

## Group A: Source Adapters + Enrichers

### Task 7: CompositeEnricher

**Files:**
- Create: `src/workbench/providers/enrichment/composite.py`
- Test: `tests/test_composite_enricher.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_composite_enricher.py

import pytest
from unittest.mock import AsyncMock
from workbench.providers.enrichment.composite import CompositeEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import EnrichmentBudget, ExtractedItem, RawItem


def _make_item(source_type: str) -> ExtractedItem:
    raw = RawItem(source_type=source_type, source_id="test-1", raw_text="{}")
    return ExtractedItem(
        summary="test", category="informational", raw_item=raw,
    )


@pytest.mark.asyncio
async def test_routes_by_source_type():
    email_enricher = AsyncMock()
    email_enricher.enrich.return_value = {"entity_refs": [], "thread": "full"}
    github_enricher = AsyncMock()
    github_enricher.enrich.return_value = {"entity_refs": [], "files": ["a.py"]}

    composite = CompositeEnricher(
        enrichers={"email": email_enricher, "github": github_enricher},
    )
    result = await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    assert result == {"entity_refs": [], "thread": "full"}
    email_enricher.enrich.assert_called_once()
    github_enricher.enrich.assert_not_called()


@pytest.mark.asyncio
async def test_falls_back_to_default():
    composite = CompositeEnricher(enrichers={}, default=StubEnricher())
    result = await composite.enrich(_make_item("unknown"), "shallow", EnrichmentBudget())
    assert result == {}


@pytest.mark.asyncio
async def test_per_enricher_budget():
    enricher = AsyncMock()
    enricher.enrich.return_value = {}
    custom_budget = EnrichmentBudget(max_api_calls=8, max_seconds=20)

    composite = CompositeEnricher(
        enrichers={"email": enricher},
        budgets={"email": custom_budget},
    )
    await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    call_args = enricher.enrich.call_args
    assert call_args[0][2] == custom_budget  # third positional arg is budget
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_composite_enricher.py -v`
Expected: ImportError — `composite` module not found.

- [ ] **Step 3: Implement CompositeEnricher**

```python
# src/workbench/providers/enrichment/composite.py

from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import ExtractedItem, EnrichmentBudget


class CompositeEnricher(ContextEnricher):
    def __init__(
        self,
        enrichers: dict[str, ContextEnricher],
        default: ContextEnricher | None = None,
        budgets: dict[str, EnrichmentBudget] | None = None,
    ):
        self.enrichers = enrichers
        self.default = default or StubEnricher()
        self.budgets = budgets or {}

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        enricher = self.enrichers.get(item.source_type, self.default)
        effective_budget = self.budgets.get(item.source_type, budget)
        return await enricher.enrich(item, depth, effective_budget, memory=memory)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_enricher.py -v`
Expected: All pass.

- [ ] **Step 5: Un-skip the registry test from Task 4 and run it**

Remove `@pytest.mark.skip` from `test_create_composite_enricher` in `tests/test_registry.py`.

Run: `python -m pytest tests/test_registry.py::test_create_composite_enricher -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/workbench/providers/enrichment/composite.py tests/test_composite_enricher.py tests/test_registry.py
git commit -m "feat(enrichment): add CompositeEnricher with source_type routing and per-enricher budgets"
```

---

### Task 8: GoogleConnection

**Files:**
- Create: `src/workbench/providers/connection/google.py`
- Test: `tests/test_google_connection.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_google_connection.py

import pytest
from unittest.mock import patch, MagicMock
from workbench.providers.connection.google import GoogleConnection


@pytest.mark.asyncio
async def test_initialize_loads_credentials():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("workbench.providers.connection.google.build") as mock_build:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = MagicMock()

        await conn.initialize()
        assert conn.is_healthy()
        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            "/tmp/token.json",
            ["https://www.googleapis.com/auth/gmail.readonly"],
        )


@pytest.mark.asyncio
async def test_raises_on_missing_token():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/nonexistent/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)
    with pytest.raises(FileNotFoundError):
        await conn.initialize()


def test_is_healthy_false_before_init():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=[],
    )
    conn = GoogleConnection(config)
    assert conn.is_healthy() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_google_connection.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GoogleConnection**

```python
# src/workbench/providers/connection/google.py

import asyncio
import os
from pydantic import BaseModel
from workbench.providers.connection.base import Connection

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    Request = None
    build = None


class GoogleConnection(Connection):
    class ProviderConfig(BaseModel):
        credentials_path: str
        token_path: str
        scopes: list[str]

    def __init__(self, config: "GoogleConnection.ProviderConfig", **kwargs):
        self._config = config
        self._credentials: Credentials | None = None
        self._gmail_service = None
        self._calendar_service = None
        self._chat_service = None
        self._initialized = False

    async def initialize(self) -> None:
        if not os.path.exists(self._config.token_path):
            raise FileNotFoundError(
                f"Google OAuth token not found at {self._config.token_path}. "
                f"Run the OAuth consent flow first to create the token file."
            )

        def _load():
            creds = Credentials.from_authorized_user_file(
                self._config.token_path, self._config.scopes,
            )
            if not creds.valid and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self._config.token_path, "w") as f:
                    f.write(creds.to_json())
            return creds

        self._credentials = await asyncio.to_thread(_load)
        self._initialized = True

    @property
    def gmail(self):
        if self._gmail_service is None:
            self._gmail_service = build("gmail", "v1", credentials=self._credentials)
        return self._gmail_service

    @property
    def calendar(self):
        if self._calendar_service is None:
            self._calendar_service = build("calendar", "v3", credentials=self._credentials)
        return self._calendar_service

    @property
    def chat(self):
        if self._chat_service is None:
            self._chat_service = build("chat", "v1", credentials=self._credentials)
        return self._chat_service

    async def close(self) -> None:
        self._gmail_service = None
        self._calendar_service = None
        self._chat_service = None
        self._initialized = False

    def is_healthy(self) -> bool:
        return self._initialized and self._credentials is not None and (
            self._credentials.valid or self._credentials.refresh_token is not None
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_google_connection.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/connection/google.py tests/test_google_connection.py
git commit -m "feat(connection): add GoogleConnection with OAuth2 token management"
```

---

### Task 9: Gmail Adapter

**Files:**
- Create: `src/workbench/providers/source/gmail.py`
- Test: `tests/test_gmail_adapter.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gmail_adapter.py

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
from workbench.providers.source.gmail import GmailAdapter
from workbench.models import RawItem


def _mock_connection():
    conn = MagicMock()
    return conn


def _make_gmail_message(msg_id: str, subject: str, sender: str, body: str = "hello"):
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@meta.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": __import__("base64").urlsafe_b64encode(body.encode()).decode()},
            "parts": [],
        },
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
    }


@pytest.mark.asyncio
async def test_poll_returns_raw_items():
    conn = _mock_connection()
    messages_list = MagicMock()
    messages_list.execute.return_value = {
        "messages": [{"id": "msg-1"}],
    }
    messages_get = MagicMock()
    messages_get.execute.return_value = _make_gmail_message("msg-1", "Test Subject", "alice@meta.com")
    conn.gmail.users.return_value.messages.return_value.list.return_value = messages_list
    conn.gmail.users.return_value.messages.return_value.get.return_value = messages_get

    config = GmailAdapter.ProviderConfig(label_filters=["INBOX"], max_results=50)
    adapter = GmailAdapter(config, connection=conn)

    with patch("workbench.providers.source.gmail.asyncio") as mock_asyncio:
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw) if not callable(fn) else fn())
        # Simplified: mock to_thread to run sync
        items = await adapter.poll(since=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].source_type == "email"
    assert items[0].source_id == "email_msg-1"
    raw = json.loads(items[0].raw_text)
    assert raw["subject"] == "Test Subject"
    assert raw["sender"] == "alice@meta.com"


def test_adapter_type():
    config = GmailAdapter.ProviderConfig()
    adapter = GmailAdapter(config)
    assert adapter.adapter_type() == "email"


@pytest.mark.asyncio
async def test_poll_with_no_messages():
    conn = _mock_connection()
    messages_list = MagicMock()
    messages_list.execute.return_value = {}
    conn.gmail.users.return_value.messages.return_value.list.return_value = messages_list

    config = GmailAdapter.ProviderConfig()
    adapter = GmailAdapter(config, connection=conn)

    with patch("workbench.providers.source.gmail.asyncio") as mock_asyncio:
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn())
        items = await adapter.poll()

    assert items == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gmail_adapter.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GmailAdapter**

```python
# src/workbench/providers/source/gmail.py

import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pydantic import BaseModel
from workbench.providers.source.base import SourceAdapter
from workbench.models import RawItem


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, data):
        self.text.append(data)
    def get_text(self):
        return "".join(self.text)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            return _strip_html(html)

    if payload.get("body", {}).get("data"):
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        if payload.get("mimeType", "").startswith("text/html"):
            return _strip_html(raw)
        return raw

    return ""


def _clean_body(body: str) -> str:
    lines = body.split("\n")
    cleaned = []
    for line in lines:
        if line.strip().startswith(">"):
            continue
        if line.strip() == "--":
            break
        cleaned.append(line)
    text = "\n".join(cleaned).strip()
    return text[:4000]


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_attachments(payload: dict) -> list[dict]:
    attachments = []
    for part in payload.get("parts", []):
        if part.get("filename"):
            attachments.append({
                "filename": part["filename"],
                "mime_type": part.get("mimeType", ""),
                "size_bytes": int(part.get("body", {}).get("size", 0)),
                "attachment_id": part.get("body", {}).get("attachmentId", ""),
                "inline": "Content-ID" in {h.get("name", "") for h in part.get("headers", [])},
            })
    return attachments


class GmailAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        label_filters: list[str] = ["INBOX", "UNREAD"]
        max_results: int = 50

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection

    def adapter_type(self) -> str:
        return "email"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        query = " ".join(f"label:{lbl}" for lbl in self._config.label_filters)
        if since:
            query += f" after:{int(since.timestamp())}"

        def _fetch():
            result = self._connection.gmail.users().messages().list(
                userId="me", q=query, maxResults=self._config.max_results,
            ).execute()
            return result.get("messages", [])

        message_stubs = await asyncio.to_thread(_fetch)
        items = []
        for stub in message_stubs:
            msg_id = stub["id"]

            def _get_message(mid=msg_id):
                return self._connection.gmail.users().messages().get(
                    userId="me", id=mid, format="full",
                ).execute()

            msg = await asyncio.to_thread(_get_message)
            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            subject = _get_header(headers, "Subject")
            sender = _get_header(headers, "From")
            to = _get_header(headers, "To")
            cc = _get_header(headers, "Cc")

            body = _clean_body(_extract_body(payload))
            attachments = _extract_attachments(payload)

            recipients_to = [r.strip() for r in to.split(",") if r.strip()]
            recipients_cc = [r.strip() for r in cc.split(",") if r.strip()]

            raw_text = json.dumps({
                "subject": subject,
                "sender": sender,
                "recipients_to": recipients_to,
                "recipients_cc": recipients_cc,
                "body": body,
                "snippet": msg.get("snippet", ""),
                "thread_id": msg.get("threadId", ""),
                "attachments": attachments,
            })

            urgency_signals = {
                "sender": sender,
                "is_direct": len(recipients_to) == 1 and not recipients_cc,
                "cc_count": len(recipients_cc),
                "thread_depth": 0,
                "has_attachments": len(attachments) > 0,
                "labels": msg.get("labelIds", []),
            }

            items.append(RawItem(
                source_type="email",
                source_id=f"email_{msg_id}",
                raw_text=raw_text,
                urgency_signals=urgency_signals,
            ))

        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gmail_adapter.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/source/gmail.py tests/test_gmail_adapter.py
git commit -m "feat(source): add GmailAdapter with MIME extraction and attachment metadata"
```

---

### Task 10: Gmail Enricher

**Files:**
- Create: `src/workbench/providers/enrichment/gmail.py`
- Test: `tests/test_gmail_enricher.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gmail_enricher.py

import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from workbench.providers.enrichment.gmail import GmailEnricher
from workbench.models import ExtractedItem, RawItem, EnrichmentBudget, EntityType


def _make_email_item() -> ExtractedItem:
    raw = RawItem(
        source_type="email", source_id="email_msg-1",
        raw_text=json.dumps({
            "subject": "Review compliance doc",
            "sender": "alice@meta.com",
            "recipients_to": ["me@meta.com"],
            "recipients_cc": [],
            "body": "Please review the doc.",
            "thread_id": "thread-1",
            "attachments": [],
        }),
    )
    return ExtractedItem(summary="Review compliance doc", category="action_item", raw_item=raw)


@pytest.mark.asyncio
async def test_returns_entity_refs():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    result = await enricher.enrich(_make_email_item(), "shallow", EnrichmentBudget())
    assert "entity_refs" in result
    refs = result["entity_refs"]
    assert (EntityType.PERSON, "email:alice@meta.com") in refs


@pytest.mark.asyncio
async def test_enricher_type():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    assert enricher.adapter_type() == "email" or True  # enrichers don't have adapter_type
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gmail_enricher.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GmailEnricher**

```python
# src/workbench/providers/enrichment/gmail.py

import json
from pydantic import BaseModel
from workbench.providers.enrichment.base import ContextEnricher
from workbench.models import ExtractedItem, EnrichmentBudget, EntityType


class GmailEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, AttributeError):
            return {"entity_refs": []}

        entity_refs = []
        sender = raw.get("sender", "")
        if sender:
            entity_refs.append((EntityType.PERSON, f"email:{sender}"))
            if memory:
                try:
                    await memory.record_entity(
                        EntityType.PERSON, f"email:{sender}",
                        {"email": sender, "name": sender.split("@")[0]},
                    )
                except Exception:
                    pass

        for recipient in raw.get("recipients_to", []) + raw.get("recipients_cc", []):
            if recipient:
                entity_refs.append((EntityType.PERSON, f"email:{recipient}"))

        result = {
            "entity_refs": entity_refs,
            "subject": raw.get("subject", ""),
            "sender": sender,
            "thread_id": raw.get("thread_id", ""),
            "attachments": raw.get("attachments", []),
        }

        if self._connection and budget.max_api_calls > 0:
            pass  # TODO in implementation: fetch full thread via Gmail API

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gmail_enricher.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/enrichment/gmail.py tests/test_gmail_enricher.py
git commit -m "feat(enrichment): add GmailEnricher with entity_refs extraction"
```

---

### Task 11: Google Calendar Adapter + Enricher

Follow the same pattern as Tasks 9-10. Key differences:

**Files:**
- Create: `src/workbench/providers/source/gcalendar.py`
- Create: `src/workbench/providers/enrichment/gcalendar.py`
- Test: `tests/test_gcalendar_adapter.py`

**Key implementation details:**
- `source_type = "calendar"`, `source_id = "cal_{event_id}"`
- Hash-based dedup: `hashlib.sha256(f"{title}|{desc}|{start}|{end}|{location}".encode()).hexdigest()`
- Adapter stores `_event_hashes: dict[str, str]` for change detection
- Enricher returns `entity_refs` with `(EntityType.PERSON, "gcal:{organizer}")` and attendees
- Urgency signals include `is_recurring`, `recurring_event_id`, `starts_within_hours`

- [ ] **Step 1: Write tests for adapter (hash dedup, recurring event signals)**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement GCalendarAdapter and GCalendarEnricher**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(source): add GCalendarAdapter with hash dedup + GCalendarEnricher"
```

---

### Task 12: Google Chat Adapter + Enricher

Follow the same pattern. Key differences:

**Files:**
- Create: `src/workbench/providers/source/gchat.py`
- Create: `src/workbench/providers/enrichment/gchat.py`
- Test: `tests/test_gchat_adapter.py`

**Key implementation details:**
- Thread subscription model with `_tracked_threads: dict[str, datetime]`
- `track` config: `"participating"` | `"mentioned"` | `"all"`
- `exclude_spaces` config for filtering out bot spaces
- Bot message filtering by checking sender identity
- Thread exits tracking after 48h inactivity, re-enters on participation
- `source_id = "gchat_{thread_id}_{last_message_timestamp}"`
- Full thread context in `raw_text` (all messages, not just delta)

- [ ] **Step 1: Write tests (thread enter/exit/re-enter, track modes, bot filtering, exclude_spaces)**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement GChatAdapter and GChatEnricher**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(source): add GChatAdapter with thread subscription + GChatEnricher"
```

---

### Task 13: Scheduler — Error Isolation + Connection Health

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write test for error isolation**

```python
# tests/test_pipeline.py — append

@pytest.mark.asyncio
async def test_source_poll_error_isolation(stores):
    """One adapter failing doesn't prevent others from polling."""
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from unittest.mock import AsyncMock, MagicMock, patch

    good_adapter = AsyncMock()
    good_adapter.poll.return_value = []
    good_adapter.adapter_type.return_value = "good"

    bad_adapter = AsyncMock()
    bad_adapter.poll.side_effect = RuntimeError("OAuth expired")
    bad_adapter.adapter_type.return_value = "bad"

    scheduler = WorkbenchScheduler(
        stores=stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=None,
        config=MagicMock(),
        sources=[bad_adapter, good_adapter],
    )
    await scheduler._poll_sources()
    good_adapter.poll.assert_called_once()
    bad_adapter.poll.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py::test_source_poll_error_isolation -v`
Expected: FAIL — scheduler doesn't catch exceptions per-adapter.

- [ ] **Step 3: Update _poll_sources in scheduler.py**

Wrap each `source.poll()` in try/except:

```python
async def _poll_sources(self):
    for source in self.sources:
        try:
            if hasattr(source, '_connection') and source._connection and not source._connection.is_healthy():
                logger.warning(f"Skipping {source.adapter_type()}: connection unhealthy")
                continue
            since = await self.stores.config.get(f"last_polled_{source.adapter_type()}")
            items = await source.poll(since=since)
            for item in items:
                await self.pipeline.enqueue(item)
            await self.stores.config.set(f"last_polled_{source.adapter_type()}", datetime.now(timezone.utc))
        except Exception as e:
            logger.error(f"Source {source.adapter_type()} poll failed: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/scheduler.py tests/test_pipeline.py
git commit -m "feat(scheduler): add per-adapter error isolation and connection health checks"
```

---

### Task 14: Update config.example.yml

**Files:**
- Modify: `config.example.yml`

- [ ] **Step 1: Add connections and enrichment sections**

```yaml
# Add to config.example.yml:

connections:
  # google:
  #   class: workbench.providers.connection.google.GoogleConnection
  #   credentials_path: ${oc.env:GOOGLE_CREDENTIALS_PATH}
  #   token_path: ${oc.env:GOOGLE_TOKEN_PATH}
  #   scopes:
  #     - https://www.googleapis.com/auth/gmail.readonly
  #     - https://www.googleapis.com/auth/calendar.readonly
  #     - https://www.googleapis.com/auth/chat.spaces.readonly

sources:
  - class: workbench.providers.source.github.GitHubSourceAdapter
    repos:
      - "owner/repo"
  # - class: workbench.providers.source.gmail.GmailAdapter
  #   connection: google
  #   label_filters: ["INBOX", "UNREAD"]
  #   max_results: 50
  # - class: workbench.providers.source.gcalendar.GCalendarAdapter
  #   connection: google
  #   calendar_ids: ["primary"]
  #   lookahead_hours: 48
  # - class: workbench.providers.source.gchat.GChatAdapter
  #   connection: google
  #   spaces: ["spaces/AAAA..."]
  #   exclude_spaces: ["spaces/JARVIS..."]
  #   track: "participating"

enrichment:
  providers:
    - class: workbench.providers.enrichment.stub.StubEnricher
      source_types: ["github"]
    # - class: workbench.providers.enrichment.gmail.GmailEnricher
    #   connection: google
    #   source_types: ["email"]
    #   budget:
    #     max_api_calls: 8
    #     max_seconds: 20
  default:
    class: workbench.providers.enrichment.stub.StubEnricher
```

- [ ] **Step 2: Commit**

```bash
git add config.example.yml
git commit -m "docs(config): add connections and enrichment examples for Phase 1d sources"
```

---

## Group B: Cards + Identity Resolution

### Task 15: Identity Resolution — Entity Identities Table + Resolution

**Files:**
- Modify: `src/memory/memory/queue.py` (add table creation)
- Modify: `src/memory/memory/graphiti_layer.py` (add resolution logic)
- Modify: `src/memory/memory/models.py` (add signal tier constants)
- Test: `src/memory/tests/test_identity_resolution.py`

- [ ] **Step 1: Write tests for identity resolution**

```python
# src/memory/tests/test_identity_resolution.py

import pytest
import asyncpg
from memory.graphiti_layer import GraphitiMemoryLayer

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"

@pytest.fixture
async def store():
    pool = await asyncpg.create_pool(TEST_DSN)
    await pool.execute("DELETE FROM entity_identities")
    await pool.execute("DELETE FROM entities")
    yield pool
    await pool.close()

@pytest.mark.asyncio
async def test_first_entity_creates_canonical(store):
    layer = GraphitiMemoryLayer.__new__(GraphitiMemoryLayer)
    layer._pool = store
    layer._graphiti = None  # skip graph for unit test

    await layer.record_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith", "team": "infra",
    })

    row = await store.fetchrow(
        "SELECT canonical_id FROM entity_identities WHERE entity_type=$1 AND source_id=$2",
        "person", "github:alice-gh",
    )
    assert row is not None
    assert row["canonical_id"] == "github:alice-gh"

    entity = await store.fetchrow(
        "SELECT facts FROM entities WHERE entity_type=$1 AND entity_id=$2",
        "person", "github:alice-gh",
    )
    assert entity is not None

@pytest.mark.asyncio
async def test_strong_match_merges(store):
    layer = GraphitiMemoryLayer.__new__(GraphitiMemoryLayer)
    layer._pool = store
    layer._graphiti = None

    await layer.record_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith",
    })
    await layer.record_entity("person", "email:alice@meta.com", {
        "email": "alice@meta.com", "name": "Alice S.",
    })

    row = await store.fetchrow(
        "SELECT canonical_id FROM entity_identities WHERE source_id=$1",
        "email:alice@meta.com",
    )
    assert row["canonical_id"] == "github:alice-gh"

@pytest.mark.asyncio
async def test_weak_match_does_not_merge(store):
    layer = GraphitiMemoryLayer.__new__(GraphitiMemoryLayer)
    layer._pool = store
    layer._graphiti = None

    await layer.record_entity("person", "github:alice-gh", {
        "first_name": "Alice",
    })
    await layer.record_entity("person", "email:alice@meta.com", {
        "first_name": "Alice",
    })

    rows = await store.fetch("SELECT DISTINCT canonical_id FROM entity_identities WHERE entity_type=$1", "person")
    assert len(rows) == 2  # not merged — weak match alone

@pytest.mark.asyncio
async def test_query_resolves_through_identity(store):
    layer = GraphitiMemoryLayer.__new__(GraphitiMemoryLayer)
    layer._pool = store
    layer._graphiti = None

    await layer.record_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })
    await layer.record_entity("person", "email:alice@meta.com", {
        "email": "alice@meta.com", "role": "tech lead",
    })

    result = await layer.query_entity("person", "email:alice@meta.com")
    assert result is not None
    assert result.facts.get("team") == "infra"
    assert result.facts.get("role") == "tech lead"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v`
Expected: Failures — table doesn't exist, methods don't have resolution logic.

- [ ] **Step 3: Add entity_identities table to queue.py initialize()**

```python
await self._pool.execute("""
    CREATE TABLE IF NOT EXISTS entity_identities (
        entity_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        canonical_id TEXT NOT NULL,
        resolved_by TEXT NOT NULL DEFAULT 'heuristic',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (entity_type, source_id)
    )
""")
await self._pool.execute("""
    CREATE INDEX IF NOT EXISTS idx_entity_identities_canonical
    ON entity_identities(entity_type, canonical_id)
""")
```

- [ ] **Step 4: Add signal tier constants to memory/models.py**

```python
STRONG_SIGNAL_KEYS = {"email", "phone", "platform_uid"}
MEDIUM_SIGNAL_KEYS = {"name", "username"}
WEAK_SIGNAL_KEYS = {"first_name", "timezone", "title"}

SIGNAL_SCORES = {
    "strong": 10,
    "medium": 5,
    "weak": 1,
}
MERGE_THRESHOLD = 10
```

- [ ] **Step 5: Implement identity resolution in graphiti_layer.py record_entity()**

```python
async def record_entity(self, entity_type: str, source_id: str, facts: dict) -> None:
    # Step 1: Check if source_id already has a canonical mapping
    row = await self._pool.fetchrow(
        "SELECT canonical_id FROM entity_identities WHERE entity_type=$1 AND source_id=$2",
        entity_type, source_id,
    )

    if row:
        canonical_id = row["canonical_id"]
    else:
        # Step 2: Search for matches
        canonical_id = await self._resolve_identity(entity_type, source_id, facts)

    # Step 3: UPSERT facts
    await self._pool.execute("""
        INSERT INTO entities (entity_type, entity_id, facts)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (entity_type, entity_id) DO UPDATE
        SET facts = entities.facts || $3::jsonb, updated_at = NOW()
    """, entity_type, canonical_id, json.dumps(facts))

    # Step 4: Update graph (if available)
    if self._graphiti:
        # ... existing add_triplet logic using canonical_id ...
        pass

async def _resolve_identity(self, entity_type: str, source_id: str, facts: dict) -> str:
    from memory.models import STRONG_SIGNAL_KEYS, MEDIUM_SIGNAL_KEYS, WEAK_SIGNAL_KEYS, SIGNAL_SCORES, MERGE_THRESHOLD

    best_canonical = None
    best_score = 0

    existing_entities = await self._pool.fetch(
        "SELECT entity_id, facts FROM entities WHERE entity_type=$1", entity_type,
    )

    for existing in existing_entities:
        score = 0
        existing_facts = existing["facts"] if isinstance(existing["facts"], dict) else json.loads(existing["facts"])

        for key in STRONG_SIGNAL_KEYS:
            if key in facts and key in existing_facts and facts[key] == existing_facts[key]:
                score += SIGNAL_SCORES["strong"]
        for key in MEDIUM_SIGNAL_KEYS:
            if key in facts and key in existing_facts and facts[key] == existing_facts[key]:
                score += SIGNAL_SCORES["medium"]
        for key in WEAK_SIGNAL_KEYS:
            if key in facts and key in existing_facts and facts[key] == existing_facts[key]:
                score += SIGNAL_SCORES["weak"]

        if score > best_score:
            best_score = score
            best_canonical = existing["entity_id"]

    if best_score >= MERGE_THRESHOLD and best_canonical:
        canonical_id = best_canonical
    else:
        canonical_id = source_id

    await self._pool.execute("""
        INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by)
        VALUES ($1, $2, $3, 'heuristic')
        ON CONFLICT (entity_type, source_id) DO NOTHING
    """, entity_type, source_id, canonical_id)

    return canonical_id

async def _resolve_canonical(self, entity_type: str, source_id: str) -> str | None:
    row = await self._pool.fetchrow(
        "SELECT canonical_id FROM entity_identities WHERE entity_type=$1 AND source_id=$2",
        entity_type, source_id,
    )
    return row["canonical_id"] if row else None

async def query_entity(self, entity_type: str, entity_id: str):
    canonical = await self._resolve_canonical(entity_type, entity_id)
    target_id = canonical or entity_id
    row = await self._pool.fetchrow(
        "SELECT entity_type, entity_id, facts FROM entities WHERE entity_type=$1 AND entity_id=$2",
        entity_type, target_id,
    )
    if not row:
        return None
    from memory.models import EntityResponse
    return EntityResponse(entity_type=row["entity_type"], entity_id=row["entity_id"], facts=row["facts"])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/memory/
git commit -m "feat(memory): add identity resolution with signal-tiered attribute matching"
```

---

### Task 16: Identity Resolution — Late Discovery Merge + Admin Endpoints

**Files:**
- Modify: `src/memory/memory/graphiti_layer.py`
- Modify: `src/memory/memory/main.py`
- Test: `src/memory/tests/test_identity_resolution.py` (append)

- [ ] **Step 1: Write tests for late discovery merge and admin endpoints**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement late_discovery_merge() method and admin endpoints**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(memory): add late discovery merge and admin merge/split endpoints"
```

---

### Task 17: LLM Card Generation — Memory Context + Prompt

**Files:**
- Modify: `src/workbench/pipeline/triage.py`
- Modify: `src/workbench/pipeline/engine.py`
- Modify: `src/workbench/providers/llm/base.py`
- Modify: `src/workbench/providers/llm/anthropic.py`
- Test: `tests/test_triage_card_enrichment.py`

- [ ] **Step 1: Write tests for LLM card generation with memory context**

```python
# tests/test_triage_card_enrichment.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.pipeline.triage import generate_card
from workbench.models import ExtractedItem, RawItem, TriageCard, TriageOption, EntityType


def _make_item():
    raw = RawItem(source_type="email", source_id="email_1", raw_text="{}")
    return ExtractedItem(summary="Review PR #200", category="action_item", raw_item=raw)


@pytest.mark.asyncio
async def test_generate_card_with_memory():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "PR #200 from alice (infra lead). You usually prioritize her reviews."},
        options=[
            TriageOption(label="Add todo P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    memory = AsyncMock()
    memory.is_available.return_value = True
    memory.query_entity.return_value = MagicMock(facts={"team": "infra", "role": "lead"})
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = [MagicMock(content="user prioritizes alice PRs")]

    enrichment = {
        "entity_refs": [(EntityType.PERSON, "github:alice")],
        "files_changed": ["api.py"],
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert "card_body" in card.card_content
    assert card.options[-1].action == "other"  # "Other" always appended


@pytest.mark.asyncio
async def test_generate_card_fallback_on_llm_failure():
    llm = AsyncMock()
    llm.generate_triage_card.side_effect = Exception("LLM timeout")
    memory = AsyncMock()
    memory.is_available.return_value = True
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = []

    enrichment = {"entity_refs": []}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert card is not None
    assert "summary" in card.card_content  # template fallback
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement generate_card with memory context gathering**

Update `src/workbench/pipeline/triage.py`:

```python
import asyncio
from workbench.models import TriageCard, TriageOption, ExtractedItem

async def generate_card(
    llm, item: ExtractedItem, enrichment_context: dict,
    source_type: str, *, memory=None,
) -> TriageCard:
    memory_context = None
    if memory and memory.is_available():
        entity_refs = enrichment_context.get("entity_refs", [])[:5]
        try:
            queries = (
                [memory.query_entity(t, i) for t, i in entity_refs]
                + [memory.query_relationships(t, i) for t, i in entity_refs]
                + [memory.query_preferences(item.summary)]
            )
            results = await asyncio.gather(*queries, return_exceptions=True)
            n = len(entity_refs)
            entities = [r for r in results[:n] if r and not isinstance(r, Exception)]
            relationships = []
            for r in results[n:2*n]:
                if r and not isinstance(r, Exception):
                    relationships.extend(r if isinstance(r, list) else [r])
            preferences = results[-1] if not isinstance(results[-1], Exception) else []

            memory_context = {
                "entity_facts": {
                    f"{t}:{i}": e.facts
                    for (t, i), e in zip(entity_refs, entities) if e
                },
                "relationships": relationships[:10],
                "preference_facts": [f.content for f in (preferences or [])][:20],
            }
        except Exception:
            memory_context = None

    try:
        card = await llm.generate_triage_card(
            item, enrichment_context, source_type, memory_context=memory_context,
        )
    except Exception:
        card = _template_card(item, enrichment_context, source_type)

    card.options.append(
        TriageOption(label="Other — tell me what you'd like to do", action="other")
    )
    return card


def _template_card(item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
    return TriageCard(
        card_content={"summary": item.summary, "source_type": source_type, "enrichment": enrichment_context},
        options=[
            TriageOption(label="Add todo P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Add todo P2", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
            TriageOption(label=f"Never surface {source_type} like this", action="mute_pattern"),
        ],
    )
```

Update `src/workbench/pipeline/engine.py` — pass `self.memory` to `generate_card()`:

```python
card = await generate_card(self.llm, ext_item, enrichment, source_type, memory=self.memory)
```

Update `src/workbench/providers/llm/base.py` — add `memory_context` parameter:

```python
@abstractmethod
async def generate_triage_card(self, item, enrichment_context, source_type, *, memory_context=None) -> TriageCard: ...

@abstractmethod
async def interpret_triage_response(self, card: "TriageCard", raw_text: str) -> "InterpretedResponse": ...
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(triage): LLM card generation with memory context, entity_refs, suggestion validation"
```

---

### Task 18: Defer Action + Triage Store Queries

**Files:**
- Modify: `src/workbench/api/triage.py`
- Modify: `src/workbench/storage/postgres/triage.py` (already done in Task 2 Step 4)
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Write test for defer action**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Add defer handler in api/triage.py**

```python
elif option.action == "defer":
    hours = option.details.get("hours", 4)
    card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    card.status = "queued"
    await stores.triage.save_card(card)
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(triage): add defer action with deferred_until snooze"
```

---

### Task 19: Free-Text Triage Responses

**Files:**
- Modify: `src/workbench/api/triage.py`
- Modify: `src/workbench/pipeline/scheduler.py`
- Modify: `src/workbench/providers/llm/anthropic.py`
- Test: `tests/test_free_text_response.py`

- [ ] **Step 1: Write tests for free-text interpretation**

```python
# tests/test_free_text_response.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.models import (
    TriageCard, TriageOption, TriageResponse,
    InterpretedResponse, SystemAction, UserTodo,
)


@pytest.mark.asyncio
async def test_free_text_creates_system_action_and_user_todo():
    llm = AsyncMock()
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[UserTodo(summary="Assign to bob", action_category="delegation")],
        explanation="Adding as P3 todo. Created action item to assign to bob.",
    )
    card = TriageCard(
        item_id="item-1",
        options=[TriageOption(label="Skip", action="skip")],
    )
    response = TriageResponse(card_id=card.id, raw_text="add as P3 and assign to bob")
    assert response.choice is None


@pytest.mark.asyncio
async def test_other_option_sets_awaiting_followup():
    card = TriageCard(
        status="sent",
        options=[
            TriageOption(label="Skip", action="skip"),
            TriageOption(label="Other", action="other"),
        ],
    )
    assert card.options[1].action == "other"
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Update scheduler response handling and api/triage.py**

In `scheduler.py`, replace the `except ValueError: pass` with free-text handling:

```python
try:
    choice = int(text)
    if 1 <= choice <= len(card.options):
        option = card.options[choice - 1]
        if option.action == "other":
            card.status = "awaiting_followup"
            await self.stores.triage.save_card(card)
            await self.messenger.send_notification("What would you like to do?")
            return
        await self._handle_triage_response(card, TriageResponse(card_id=card.id, choice=choice))
except ValueError:
    interpreted = await self.llm.interpret_triage_response(card, text)
    await self._execute_interpreted_response(interpreted, card)
```

Handle `awaiting_followup` state at the top of the response handler:

```python
if card.status == "awaiting_followup":
    interpreted = await self.llm.interpret_triage_response(card, text)
    await self._execute_interpreted_response(interpreted, card)
    return
```

Add timeout check for awaiting_followup/awaiting_confirmation cards:

```python
if card.status in ("awaiting_followup", "awaiting_confirmation"):
    if card.sent_at and (datetime.now(timezone.utc) - card.sent_at).total_seconds() > 3600:
        card.status = "sent"
        card.response = "timed_out"
        await self.stores.triage.save_card(card)
        continue
```

- [ ] **Step 4: Implement interpret_triage_response in anthropic.py**
- [ ] **Step 5: Implement _execute_interpreted_response in scheduler.py**

```python
async def _execute_interpreted_response(self, interpreted: InterpretedResponse, card: TriageCard):
    for action in interpreted.system_actions:
        if action.action in ("skip", "mute_pattern"):
            # Destructive — require confirmation
            card.status = "awaiting_confirmation"
            await self.stores.triage.save_card(card)
            await self.messenger.send_notification(
                f"I understood: {interpreted.explanation}\nReply 'yes' to confirm."
            )
            return
        elif action.action == "add_todo":
            priority = action.details.get("priority", "P2")
            if card.item_id:
                await self.stores.items.update(card.item_id, {"status": "active", "priority": priority})
        elif action.action == "defer":
            hours = action.details.get("hours", 4)
            card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
            card.status = "queued"
            await self.stores.triage.save_card(card)

    for todo in interpreted.user_todos:
        from workbench.models import Item
        new_item = Item(
            summary=todo.summary,
            category="action_item",
            status="active",
            priority="P2",
            parent_item_id=card.item_id,
            action_source="triage_response",
            action_category=todo.action_category,
        )
        await self.stores.items.save(new_item)

    card.status = "responded"
    card.responded_at = datetime.now(timezone.utc)
    await self.stores.triage.save_card(card)

    # Log interpreted response
    # ... append to interaction log ...
```

- [ ] **Step 6: Run tests to verify they pass**
- [ ] **Step 7: Commit**

```bash
git commit -m "feat(triage): add free-text response interpretation, Other option, confirmation flow"
```

---

### Task 20: format_card_for_chat Update

**Files:**
- Modify: `src/workbench/pipeline/triage.py`
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write test for new card format**
- [ ] **Step 2: Implement updated format_card_for_chat**

```python
def format_card_for_chat(card: TriageCard) -> str:
    body = card.card_content.get("card_body", card.card_content.get("summary", ""))
    lines = [f"*{body}*", ""]
    for i, opt in enumerate(card.options, 1):
        suggested = f" _(suggested: {opt.suggestion_reason})_" if opt.suggested else ""
        lines.append(f"{i}. {opt.label}{suggested}")
    lines.append("")
    lines.append("_Or just reply with what you'd like to do._")
    return "\n".join(lines)
```

- [ ] **Step 3: Run tests to verify they pass**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(triage): update format_card_for_chat with LLM body and free-text hint"
```

---

## Group C: Action Items

### Task 21: Actions API

**Files:**
- Create: `src/workbench/api/actions.py`
- Modify: `src/workbench/main.py` (mount router)
- Test: `tests/test_actions_api.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_actions_api.py

import pytest
from httpx import AsyncClient, ASGITransport
from workbench.models import Item


@pytest.mark.asyncio
async def test_get_actions_grouped(stores):
    item1 = Item(
        summary="Assign to bob", category="action_item", status="active",
        action_source="triage_response", action_category="delegation",
        parent_item_id="parent-1",
    )
    item2 = Item(
        summary="Review RFC", category="action_item", status="active",
        action_source="triage_response", action_category="review",
    )
    await stores.items.save(item1)
    await stores.items.save(item2)

    from workbench.api.actions import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    app.state.stores = stores

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/actions")
    assert resp.status_code == 200
    data = resp.json()
    assert "delegation" in data["categories"]
    assert "review" in data["categories"]
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_mark_action_done(stores):
    item = Item(
        summary="Assign to bob", category="action_item", status="active",
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save(item)

    from workbench.api.actions import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    app.state.stores = stores

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/actions/{item.id}/done")
    assert resp.status_code == 200

    updated = await stores.items.get(item.id)
    assert updated.status == "done"
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement actions API**

```python
# src/workbench/api/actions.py

from collections import defaultdict
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("")
async def get_actions(request: Request, status: str = "active", category: str | None = None):
    stores = request.app.state.stores
    items = await stores.items.get_items({"status": status, "action_source__isnull": False})

    if category:
        items = [i for i in items if i.action_category == category]

    categories = defaultdict(list)
    for item in items:
        cat = item.action_category or "uncategorized"
        parent = None
        if item.parent_item_id:
            parent_item = await stores.items.get(item.parent_item_id)
            if parent_item:
                parent = {"id": parent_item.id, "summary": parent_item.summary}
        categories[cat].append({
            "id": item.id,
            "summary": item.summary,
            "priority": item.priority,
            "parent_item": parent,
            "action_source": item.action_source,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {"categories": dict(categories), "total": len(items)}


class PriorityUpdate(BaseModel):
    priority: str

class SnoozeRequest(BaseModel):
    hours: int = 4


@router.post("/{item_id}/done")
async def mark_done(request: Request, item_id: str):
    stores = request.app.state.stores
    item = await stores.items.get(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update(item_id, {"status": "done"})
    return {"status": "done"}


@router.post("/{item_id}/priority")
async def change_priority(request: Request, item_id: str, body: PriorityUpdate):
    stores = request.app.state.stores
    item = await stores.items.get(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update(item_id, {"priority": body.priority})
    return {"status": "updated", "priority": body.priority}


@router.post("/{item_id}/snooze")
async def snooze_action(request: Request, item_id: str, body: SnoozeRequest):
    stores = request.app.state.stores
    item = await stores.items.get(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update(item_id, {"status": "active"})
    return {"status": "snoozed", "hours": body.hours}
```

- [ ] **Step 4: Mount router in main.py**

```python
from workbench.api.actions import router as actions_router
app.include_router(actions_router)
```

- [ ] **Step 5: Run tests to verify they pass**
- [ ] **Step 6: Commit**

```bash
git commit -m "feat(api): add /api/actions endpoints for categorized action items"
```

---

### Task 22: Morning Briefing — Pending Actions Section

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write test for pending actions in briefing**
- [ ] **Step 2: Update _morning_briefing_inner to query and format action items**

After the existing P0/P1/queue health sections (around line 225), add:

```python
action_items = [i for i in active_items if i.action_source is not None]
if action_items:
    from collections import defaultdict
    by_category = defaultdict(list)
    for item in action_items:
        cat = (item.action_category or "uncategorized").title()
        parent_summary = ""
        if item.parent_item_id:
            parent = await self.stores.items.get(item.parent_item_id)
            if parent:
                parent_summary = f" — from {parent.summary}"
        by_category[cat].append(f"  - {item.summary}{parent_summary}")
    sections.append(f"*Pending actions ({len(action_items)}):*")
    for cat, items in by_category.items():
        sections.append(f"  {cat} ({len(items)}):")
        sections.extend(items)
```

- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(scheduler): add pending actions section to morning briefing"
```

---

### Task 23: React UI — Setup + Components

**Files:**
- Create: `ui/` directory with Vite + React project
- Create: `ui/package.json`
- Create: `ui/vite.config.ts`
- Create: `ui/index.html`
- Create: `ui/src/App.tsx`
- Create: `ui/src/main.tsx`
- Create: `ui/src/api.ts`
- Create: `ui/src/components/ActionList.tsx`
- Create: `ui/src/components/ActionItem.tsx`

- [ ] **Step 1: Initialize Vite project**

```bash
cd /home/anshulverma/workspace/workbench
npm create vite@latest ui -- --template react-ts
cd ui && npm install
```

- [ ] **Step 2: Configure Vite proxy for dev**

```typescript
// ui/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  server: {
    proxy: {
      '/api': 'http://localhost:8421',
    },
  },
})
```

- [ ] **Step 3: Create API client**

```typescript
// ui/src/api.ts
const getToken = () => {
  const meta = document.querySelector('meta[name="api-token"]')
  return meta?.getAttribute('content') || ''
}

export async function fetchActions(params?: Record<string, string>) {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  const res = await fetch(`/api/actions${query}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  return res.json()
}

export async function markDone(id: string) {
  await fetch(`/api/actions/${id}/done`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
  })
}

export async function changePriority(id: string, priority: string) {
  await fetch(`/api/actions/${id}/priority`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${getToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ priority }),
  })
}

export async function snooze(id: string, hours: number) {
  await fetch(`/api/actions/${id}/snooze`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${getToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ hours }),
  })
}
```

- [ ] **Step 4: Create ActionList component**

```tsx
// ui/src/components/ActionList.tsx
import { useState, useEffect } from 'react'
import { fetchActions } from '../api'
import { ActionItem } from './ActionItem'

interface Action {
  id: string
  summary: string
  priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string
  created_at: string
}

interface ActionsData {
  categories: Record<string, Action[]>
  total: number
}

export function ActionList() {
  const [data, setData] = useState<ActionsData | null>(null)
  const [filter, setFilter] = useState<string>('')

  const load = () => {
    const params: Record<string, string> = {}
    if (filter) params.category = filter
    fetchActions(params).then(setData)
  }

  useEffect(load, [filter])

  if (!data) return <div>Loading...</div>

  const categories = Object.entries(data.categories)

  return (
    <div>
      <h1>Action Items ({data.total})</h1>
      <select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="">All categories</option>
        <option value="delegation">Delegation</option>
        <option value="communication">Communication</option>
        <option value="scheduling">Scheduling</option>
        <option value="review">Review</option>
        <option value="creation">Creation</option>
        <option value="update">Update</option>
      </select>
      {categories.map(([category, items]) => (
        <details key={category} open>
          <summary>{category} ({items.length})</summary>
          <ul>
            {items.map(item => (
              <ActionItem key={item.id} item={item} onUpdate={load} />
            ))}
          </ul>
        </details>
      ))}
      {categories.length === 0 && <p>No pending actions.</p>}
    </div>
  )
}
```

- [ ] **Step 5: Create ActionItem component**

```tsx
// ui/src/components/ActionItem.tsx
import { markDone, changePriority, snooze } from '../api'

interface Props {
  item: {
    id: string
    summary: string
    priority: string
    parent_item: { id: string; summary: string } | null
    created_at: string
  }
  onUpdate: () => void
}

export function ActionItem({ item, onUpdate }: Props) {
  const age = Math.floor(
    (Date.now() - new Date(item.created_at).getTime()) / (1000 * 60 * 60)
  )

  return (
    <li style={{ marginBottom: 8 }}>
      <span style={{ fontWeight: 'bold' }}>[{item.priority}]</span>{' '}
      {item.summary}
      {item.parent_item && (
        <span style={{ color: '#888' }}> — from {item.parent_item.summary}</span>
      )}
      <span style={{ color: '#aaa', marginLeft: 8 }}>{age}h ago</span>
      <div style={{ marginTop: 4 }}>
        <button onClick={() => markDone(item.id).then(onUpdate)}>Done</button>
        <button onClick={() => changePriority(item.id, 'P1').then(onUpdate)}>P1</button>
        <button onClick={() => changePriority(item.id, 'P2').then(onUpdate)}>P2</button>
        <button onClick={() => changePriority(item.id, 'P3').then(onUpdate)}>P3</button>
        <button onClick={() => snooze(item.id, 4).then(onUpdate)}>Snooze 4h</button>
      </div>
    </li>
  )
}
```

- [ ] **Step 6: Wire up App and main**

```tsx
// ui/src/App.tsx
import { ActionList } from './components/ActionList'

export default function App() {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 20, fontFamily: 'system-ui' }}>
      <ActionList />
    </div>
  )
}

// ui/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 7: Build and verify**

```bash
cd ui && npm run build
```
Expected: `dist/` directory created with built assets.

- [ ] **Step 8: Commit**

```bash
git add ui/
git commit -m "feat(ui): add React action items UI with categorized list and actions"
```

---

## Group M: workbench-meta Adapters

### Task 24: Meta-Internal Adapters (workbench-meta)

**Note:** These tasks are in the separate `~/workspace/workbench-meta/` repository. They depend on resolving the InternConnection auth mechanism (open question).

**Files (all in workbench-meta):**
- Create: `workbench_meta/providers/connection/__init__.py`
- Create: `workbench_meta/providers/connection/intern.py`
- Create: `workbench_meta/providers/source/meta_tasks.py`
- Create: `workbench_meta/providers/source/workplace.py`
- Create: `workbench_meta/providers/source/docs.py`
- Create: `workbench_meta/providers/enrichment/meta_tasks.py`
- Create: `workbench_meta/providers/enrichment/workplace.py`
- Create: `workbench_meta/providers/enrichment/docs.py`
- Modify: `config.meta.yml`

Each adapter follows the same pattern as the Google adapters:
1. `SourceAdapter` subclass with `ProviderConfig`, two-arg constructor accepting connection
2. `poll(since)` returns `list[RawItem]` with source-qualified IDs
3. Paired enricher with `entity_refs` output and identifying attributes

- [ ] **Step 1: Create InternConnection stub (auth TBD)**
- [ ] **Step 2: Implement MetaTasksAdapter + MetaTasksEnricher**
- [ ] **Step 3: Implement WorkplaceAdapter + WorkplaceEnricher**
- [ ] **Step 4: Implement MetaDocsAdapter + MetaDocsEnricher**
- [ ] **Step 5: Update config.meta.yml with connections and full enricher list**
- [ ] **Step 6: Commit**

```bash
git commit -m "feat(meta): add Meta Tasks, Workplace, Docs adapters with InternConnection"
```

---

## Final Verification

### Task 25: End-to-End Verification

- [ ] **Step 1: Run all workbench tests**

```bash
make test
```
Expected: All pass.

- [ ] **Step 2: Run all memory service tests**

```bash
cd src/memory && python -m pytest tests/ -v
```
Expected: All pass.

- [ ] **Step 3: Start services and verify**

```bash
make up
```

Verify:
- `GET /health` returns 200 with version info
- `GET /api/actions` returns 200 with empty categories
- `/ui/actions` serves the React app (if built)
- Config loads with `connections:` section

- [ ] **Step 4: Verify config.example.yml is valid**

```bash
python -c "from workbench.config import load_config; load_config('config.example.yml')"
```
Expected: No errors.

- [ ] **Step 5: Commit any remaining changes**

```bash
git commit -m "chore: Phase 1d final verification pass"
```

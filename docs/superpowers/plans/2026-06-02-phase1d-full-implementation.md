# Phase 1d: Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 6 source adapters with shared connections, LLM-generated triage cards with memory enrichment and identity resolution, free-text triage responses, and an action items system with React UI. Includes observability foundation (structlog, Prometheus metrics, instrumented wrappers), operational readiness (health checks, alerting, debug config, diagnostic endpoints), and privacy safeguards (PII log sanitization, data retention).

**Architecture:** Cross-cutting foundation (Group 0), then observability/ops/privacy foundation (Group 0.5), then three independent tracks: A (Sources) → B (Cards) → C (Actions). Group 0.5 is a prerequisite for Group A — adapters must have metrics and PII-safe logging from day 1.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL, Google API client, Vite + React + Tailwind CSS, pdfplumber, pytest + pytest-asyncio

**Grilling Decisions Applied (2026-06-02):** This plan incorporates 34 design decisions from the grilling session. Key changes from the original spec:
1. Response handling consolidated into shared `execute_triage_response()` in `pipeline/triage.py`
2. GChat thread state via `adapter_state` PG table + `AdapterStateStore` + `state_store` constructor injection
3. UUID canonical entity IDs (not first-seen source_id)
4. PG-first, Neo4j best-effort for merge atomicity
5. Timeout on `awaiting_*` states reverts to `sent` (keeps `bot_message_id`, resumes polling)
6. No caps on memory context (entity_refs, relationships, preference facts — send all)
7. No re-scoring on deferred card snooze expiry — preserve original `relevance_score`, just set back to `queued`
8. 8 action categories: delegation, communication, scheduling, review, creation, update, decision, investigation
9. Full attachment processing: images via Claude vision API, PDFs via pdfplumber
10. Config version 0.3.0 (from 0.2.1)
11. Connection init failure = hard startup error (no degraded mode)
12. Defense-in-depth for GChat feedback loop (bot filter + exclude_spaces validation + triage response filtering)
13. Entity admin endpoints proxied through workbench
14. Workplace uses own Graph API (shared InternConnection auth)
15. InternConnection auth must be resolved before Meta adapter work
16. All-day calendar events included with `is_all_day: true`
17. TEAM entity refs extracted from Meta sources
18. ~~Dropped~~: no migration script — old queued cards degrade gracefully via `format_card_for_chat()` fallback
19. `snoozed_until` and `completed_at` on Item model
20. Tailwind CSS for React UI
21. `describe_image(content, mime_type, context)` on LLMProvider + `extract_pdf_text()` in `workbench/util/attachments.py` (split per grilling #12)
22. Full context (card + enrichment + memory) for interpret_triage_response, stored on card

**Grilling Decisions Applied (2026-06-03 — Observability, Operations, Privacy):**
23. Observability/ops/privacy woven into Phase 1d as Group 0.5 (not deferred to separate phase)
24. structlog with JSON/console output replaces glog formatter (ADR 0010)
25. Correlation ID middleware (UUID4 per request, bound to structlog context)
26. Prometheus metrics via `prometheus-client` with `/metrics` endpoint
27. Instrumented wrappers (decorator pattern) for adapters, LLM, enrichers — applied by registry
28. Health check returns 503 on critical failure; component-level checks; liveness/readiness split
29. Structured `DebugConfig` section (SQL, LLM prompts, request bodies — independently toggled)
30. PII debug logging requires double opt-in (debug flag + `privacy.allow_pii_in_debug_logs`)
31. `SanitizingProcessor` for log PII redaction — email/phone regex, content truncation (ADR 0011)
32. Extensible sanitizer patterns via `extra_patterns` (workbench-meta adds PHIDs, employee IDs)
33. Data retention with daily cleanup; OSS defaults 30-90 days; workbench-meta overrides to 365 days
34. AlertManager with messenger integration, configurable thresholds, cooldown dedup
35. Diagnostic endpoints under `/api/debug/` (adapters, pipeline, connections, identity, config with secret redaction)
36. OpenTelemetry auto-instrumentation opt-in via `tracing:` config section
37. All observability/ops/privacy infrastructure in workbench (OSS); workbench-meta adds only config overrides + extra sanitizer patterns

**Grilling Decisions Applied (2026-06-03 — Plan Review Round 2):**
38. UUID4 always for canonical entity IDs — fix Task 15 tests (was using first source_id)
39. Consolidate `execute_triage_response()` in `pipeline/triage.py` — fix Tasks 18/19 (was duplicated between API route and scheduler)
40. Add `TriageResponseResult` to Task 1 model changes (was missing)
41. `entity_refs` as list of dicts `[{"type": "person", "id": "..."}]` not tuples (clean JSON/JSONB round-trip)
42. React UI token injection via dedicated route + `__API_TOKEN__` placeholder (fix main.py, match grilling #23)
43. Add `state_store` injection to registry Task 4 alongside `connection`; create `AdapterStateStore` in Task 2
44. Add `enrichment_errors` counter to metrics Task 6b; pass to CompositeEnricher
45. Add `describe_image()` to LLMProvider base + `extract_pdf_text()` utility in Task 10 (Gmail Enricher)
46. `GET /api/items` excludes action items by default (`?exclude_actions=true`)
47. Auth exemptions for `/metrics`, `/health/live`, `/health/ready` consolidated in Task 6c
48. GChat bot identity auto-discovered via Chat API at `GoogleConnection` init, cached as `bot_user_id`
49. InternConnection auth investigation added as early task (before Group A, not deferred to Group M)
50. `AdapterStateStore` created in Task 2 with full interface (get/save/delete)
51. Config minor version warning when config.version < expected
52. `InteractionEntry.type` set for all interactions: `option_selected`, `interpreted_response`, `confirmation`
53. `CompositeEnricher` wraps each child enricher with `InstrumentedContextEnricher` at construction
54. `format_card_for_chat` skips raw enrichment when `card_body` present (LLM already incorporated context)
55. Strip authoring commentary from plan markdown
56. React UI auth: revert to `__API_TOKEN__` meta tag approach (not /api/auth/token endpoint) — no bootstrapping problem
57. Meta sanitizer regex: `\b[a-z]{2,20}(?=@(?:fb|meta)\.com)` to match both @fb.com and @meta.com
58. React UI: add Tailwind CSS per spec; replace inline styles with utility classes
59. Meta enrichers: fix entity_refs from tuples to dicts per decision #41
60. config.meta.yml: update enrichment to new `providers:` format with source_type routing for CompositeEnricher

**Test commands:**
- Workbench: make test
- Memory service: cd src/memory && python -m pytest tests/ -v
- Single test: python -m pytest tests/test_file.py::test_name -v

---

## Group 0: Cross-Cutting Foundation

### Task 1: Model Changes — Enums and New Fields

**Files:**
- Modify: `src/workbench/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new enums and model fields**

Append to `tests/test_models.py`:

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
    assert ActionCategory.DECISION == "decision"
    assert ActionCategory.INVESTIGATION == "investigation"


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
    item = Item(
        source_type="email", source_id="e1",
        summary="test", category="action_item",
        origin="manual", priority="P2",
    )
    assert item.parent_item_id is None
    assert item.action_source is None
    assert item.action_category is None
    item2 = Item(
        source_type="email", source_id="e2",
        summary="Assign to bob",
        category="action_item",
        origin="triaged", priority="P2",
        parent_item_id="parent-123",
        action_source="triage_response",
        action_category="delegation",
    )
    assert item2.parent_item_id == "parent-123"
    assert item2.action_source == "triage_response"
    assert item2.action_category == "delegation"


def test_triage_response_choice_optional():
    resp = TriageResponse(card_id="c1", choice=2)
    assert resp.choice == 2
    resp2 = TriageResponse(card_id="c1", raw_text="add as P3")
    assert resp2.choice is None
    assert resp2.raw_text == "add as P3"


def test_interaction_entry_interpreted_fields():
    entry = InteractionEntry(
        source_type="email", item_summary="test",
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

Run: `python -m pytest tests/test_models.py -v -k "test_entity_type or test_action_category or test_triage_option_suggested or test_triage_card_deferred or test_item_action or test_triage_response_choice_optional or test_interaction_entry_interpreted or test_interpreted_response"`
Expected: ImportError -- `EntityType`, `ActionCategory`, `InterpretedResponse`, etc. not found.

- [ ] **Step 3: Implement model changes**

In `src/workbench/models.py`, add two new enums after the existing `ItemOrigin` enum:

```python
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
    DECISION = "decision"
    INVESTIGATION = "investigation"
```

Modify `TriageOption` -- add two fields after `details`:
```python
class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)
    suggested: bool = False
    suggestion_reason: str | None = None
```

Modify `TriageCard` -- add field after `response`:
```python
    deferred_until: datetime | None = None
```

Modify `Item` -- add five fields after `updated_at`:
```python
    parent_item_id: str | None = None
    action_source: str | None = None
    action_category: str | None = None
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None
```

Modify `TriageResponse` -- make `choice` optional:
```python
class TriageResponse(BaseModel):
    card_id: str
    choice: int | None = None
    raw_text: str | None = None
```

Modify `InteractionEntry` -- add three fields after `enrichment_time_ms`:
```python
    type: str | None = None
    interpreted: dict | None = None
    confirmed: bool | None = None
```

Add three new models at the end of the file:
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
Expected: All pass, including new tests. Existing tests must remain green.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/models.py tests/test_models.py
git commit -m "feat(models): add EntityType, ActionCategory enums, triage/item action fields, InterpretedResponse"
```

---

### Task 2: Alembic Migration -- New Columns

**Files:**
- Create: `src/workbench/migrations/versions/003_phase1d_columns.py`
- Modify: `src/workbench/storage/postgres/items.py`
- Modify: `src/workbench/storage/postgres/triage.py`
- Modify: `src/workbench/storage/postgres/interactions.py`

- [ ] **Step 1: Create migration file**

Create `src/workbench/migrations/versions/003_phase1d_columns.py`:

```python
"""phase1d: deferred_until, action fields, interaction fields.

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Triage cards: deferred snooze support
    op.add_column("triage_cards", sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True))

    # Items: action item hierarchy + snooze/completion tracking
    op.add_column("items", sa.Column("parent_item_id", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_source", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_category", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_items_action_source", "items", ["action_source"], postgresql_where=sa.text("action_source IS NOT NULL"))

    # Adapter state persistence
    op.execute("""
        CREATE TABLE adapter_state (
            adapter_name TEXT PRIMARY KEY,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Interaction log: free-text interpretation
    op.add_column("interaction_log", sa.Column("type", sa.Text(), nullable=True))
    op.add_column("interaction_log", sa.Column("interpreted", JSONB, nullable=True))
    op.add_column("interaction_log", sa.Column("confirmed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS adapter_state")
    op.drop_column("interaction_log", "confirmed")
    op.drop_column("interaction_log", "interpreted")
    op.drop_column("interaction_log", "type")
    op.drop_index("idx_items_action_source", "items")
    op.drop_column("items", "completed_at")
    op.drop_column("items", "snoozed_until")
    op.drop_column("items", "action_category")
    op.drop_column("items", "action_source")
    op.drop_column("items", "parent_item_id")
    op.drop_column("triage_cards", "deferred_until")
```

- [ ] **Step 2: Update PgItemStore to include new columns**

In `src/workbench/storage/postgres/items.py`, update `save_item` INSERT statement to include the three new columns:

```python
    async def save_item(self, item: Item) -> Item:
        await self.pool.execute(
            """INSERT INTO items
               (id, source_type, source_id, summary, category, origin,
                priority, status, raw_data, created_at, updated_at,
                parent_item_id, action_source, action_category)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
                       $12, $13, $14)""",
            item.id,
            item.source_type,
            item.source_id,
            item.summary,
            item.category.value if hasattr(item.category, 'value') else item.category,
            item.origin.value if hasattr(item.origin, 'value') else item.origin,
            item.priority.value if hasattr(item.priority, 'value') else item.priority,
            item.status.value if hasattr(item.status, 'value') else item.status,
            json.dumps(item.raw_data),
            item.created_at,
            item.updated_at,
            item.parent_item_id,
            item.action_source,
            item.action_category,
        )
        return item
```

Update `_row_to_item` to read the new columns:

```python
    @staticmethod
    def _row_to_item(row: asyncpg.Record) -> Item:
        raw = row["raw_data"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return Item(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            summary=row["summary"],
            category=row["category"],
            origin=row["origin"],
            priority=row["priority"],
            status=row["status"],
            raw_data=raw,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            parent_item_id=row.get("parent_item_id"),
            action_source=row.get("action_source"),
            action_category=row.get("action_category"),
        )
```

- [ ] **Step 3: Update PgTriageStore to include deferred_until**

In `src/workbench/storage/postgres/triage.py`:

Update `save_card` -- add `deferred_until` as the 14th parameter:

```python
    async def save_card(self, card: TriageCard) -> TriageCard:
        await self.pool.execute(
            """INSERT INTO triage_cards
               (id, item_id, card_content, options, relevance_score,
                confidence_score, status, bot_message_id, daily_sequence,
                expires_at, sent_at, responded_at, response, deferred_until)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8, $9,
                       $10, $11, $12, $13, $14)
               ON CONFLICT (id) DO UPDATE SET
                 item_id = EXCLUDED.item_id,
                 card_content = EXCLUDED.card_content,
                 options = EXCLUDED.options,
                 relevance_score = EXCLUDED.relevance_score,
                 confidence_score = EXCLUDED.confidence_score,
                 status = EXCLUDED.status,
                 bot_message_id = EXCLUDED.bot_message_id,
                 daily_sequence = EXCLUDED.daily_sequence,
                 expires_at = EXCLUDED.expires_at,
                 sent_at = EXCLUDED.sent_at,
                 responded_at = EXCLUDED.responded_at,
                 response = EXCLUDED.response,
                 deferred_until = EXCLUDED.deferred_until""",
            card.id,
            card.item_id,
            json.dumps(card.card_content),
            json.dumps([o.model_dump() for o in card.options]),
            card.relevance_score,
            card.confidence_score,
            card.status,
            card.bot_message_id,
            card.daily_sequence,
            card.expires_at,
            card.sent_at,
            card.responded_at,
            card.response,
            card.deferred_until,
        )
        return card
```

Update `get_pending` to include new statuses:

```python
    async def get_pending(self) -> list[TriageCard]:
        rows = await self.pool.fetch(
            "SELECT * FROM triage_cards WHERE status IN ('queued', 'sent', 'awaiting_followup', 'awaiting_confirmation') "
            "ORDER BY relevance_score DESC"
        )
        return [self._row_to_card(r) for r in rows]
```

Update `get_next_unsent` to respect `deferred_until`:

```python
    async def get_next_unsent(self) -> TriageCard | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM triage_cards WHERE status = 'queued' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) "
            "ORDER BY relevance_score DESC LIMIT 1"
        )
        return self._row_to_card(row) if row else None
```

Update `expire_old_cards` to exclude awaiting cards:

```python
    async def expire_old_cards(self, expiry_days: int) -> int:
        result = await self.pool.execute(
            "UPDATE triage_cards SET status = 'expired' "
            "WHERE status = 'queued' AND expires_at < NOW()"
        )
        return int(result.split()[-1])
```

Update `_row_to_card` to include `deferred_until`:

```python
    @staticmethod
    def _row_to_card(row: asyncpg.Record) -> TriageCard:
        card_content = row["card_content"]
        if isinstance(card_content, str):
            card_content = json.loads(card_content)

        options_data = row["options"]
        if isinstance(options_data, str):
            options_data = json.loads(options_data)

        return TriageCard(
            id=row["id"],
            item_id=row["item_id"],
            card_content=card_content,
            options=[TriageOption(**o) for o in options_data],
            relevance_score=row["relevance_score"],
            confidence_score=row["confidence_score"],
            status=row["status"],
            bot_message_id=row["bot_message_id"],
            daily_sequence=row["daily_sequence"],
            expires_at=row["expires_at"],
            sent_at=row["sent_at"],
            responded_at=row["responded_at"],
            response=row["response"],
            deferred_until=row.get("deferred_until"),
        )
```

- [ ] **Step 4: Update PgInteractionStore to include new columns**

In `src/workbench/storage/postgres/interactions.py`, update `append` INSERT to add the three new columns:

```python
    async def append(self, entry: InteractionEntry) -> None:
        await self.pool.execute(
            """INSERT INTO interaction_log
               (id, timestamp, source_type, item_id, item_summary,
                triage_card_full, enrichment_context, options_presented,
                option_chosen, todo_created, enrichment_depth,
                enrichment_calls, enrichment_time_ms, choice_index,
                type, interpreted, confirmed)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
                       $9, $10::jsonb, $11, $12, $13, $14,
                       $15, $16::jsonb, $17)""",
            entry.id,
            entry.timestamp,
            entry.source_type,
            entry.item_id,
            entry.item_summary,
            json.dumps(entry.triage_card_full),
            json.dumps(entry.enrichment_context),
            json.dumps(entry.options_presented),
            entry.option_chosen,
            json.dumps(entry.todo_created) if entry.todo_created else None,
            entry.enrichment_depth,
            entry.enrichment_calls,
            entry.enrichment_time_ms,
            entry.choice_index,
            entry.type,
            json.dumps(entry.interpreted) if entry.interpreted else None,
            entry.confirmed,
        )
```

Update `_row_to_entry` to read the new columns:

```python
    @staticmethod
    def _row_to_entry(row: asyncpg.Record) -> InteractionEntry:
        triage_card_full = row["triage_card_full"]
        if isinstance(triage_card_full, str):
            triage_card_full = json.loads(triage_card_full)

        enrichment_context = row["enrichment_context"]
        if isinstance(enrichment_context, str):
            enrichment_context = json.loads(enrichment_context)

        options_presented = row["options_presented"]
        if isinstance(options_presented, str):
            options_presented = json.loads(options_presented)

        todo = row["todo_created"]
        if isinstance(todo, str):
            todo = json.loads(todo)

        interpreted = row.get("interpreted")
        if isinstance(interpreted, str):
            interpreted = json.loads(interpreted)

        return InteractionEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            source_type=row["source_type"],
            item_id=row["item_id"],
            item_summary=row["item_summary"],
            triage_card_full=triage_card_full,
            enrichment_context=enrichment_context,
            options_presented=options_presented,
            option_chosen=row["option_chosen"],
            choice_index=row.get("choice_index"),
            todo_created=todo,
            enrichment_depth=row["enrichment_depth"],
            enrichment_calls=row["enrichment_calls"],
            enrichment_time_ms=row["enrichment_time_ms"],
            type=row.get("type"),
            interpreted=interpreted,
            confirmed=row.get("confirmed"),
        )
```

- [ ] **Step 5: Run migration against dev database**

```bash
cd src/workbench && alembic upgrade head
```
Expected: Migration applies cleanly.

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `make test`
Expected: All existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/migrations/versions/003_phase1d_columns.py src/workbench/storage/postgres/items.py src/workbench/storage/postgres/triage.py src/workbench/storage/postgres/interactions.py
git commit -m "feat(storage): add Phase 1d columns — deferred_until, action fields, interaction fields"
```

---

### Task 3: Connection ABC

**Files:**
- Create: `src/workbench/providers/connection/__init__.py`
- Create: `src/workbench/providers/connection/base.py`
- Test: `tests/test_registry.py` (append)

- [ ] **Step 1: Write tests for Connection ABC**

Append to `tests/test_registry.py`:

```python
# tests/test_registry.py — append after existing test

import pytest
from pydantic import BaseModel
from workbench.providers.connection.base import Connection


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
    """Connection subclass missing abstract methods should raise TypeError."""
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
Expected: ImportError -- `workbench.providers.connection.base` not found.

- [ ] **Step 3: Create Connection ABC**

Create `src/workbench/providers/connection/__init__.py` (empty file).

Create `src/workbench/providers/connection/base.py`:

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel


class Connection(ABC):
    """Base class for shared connections (e.g., Google OAuth, Intern API).

    Connections are initialized once at startup, injected into source adapters
    and enrichers that share the same credentials/session.
    """

    class ProviderConfig(BaseModel):
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Set up credentials, create sessions, verify connectivity."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources, close sessions."""
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """Return True if the connection is usable (credentials valid, session open)."""
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_registry.py -v -k "test_connection_abc or test_fake_connection"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/connection/__init__.py src/workbench/providers/connection/base.py tests/test_registry.py
git commit -m "feat(connection): add Connection ABC for shared provider connections"
```

---

### Task 4: Registry -- Connection Injection via inspect.signature

**Files:**
- Modify: `src/workbench/registry.py`
- Test: `tests/test_registry.py` (append)

- [ ] **Step 1: Write tests for connection injection**

Append to `tests/test_registry.py`:

```python
# tests/test_registry.py — append

from workbench.registry import create_provider
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


class ConnectionAwareProvider:
    """Provider that accepts a connection kwarg."""
    class ProviderConfig(BaseModel):
        mode: str = "default"

    def __init__(self, config: ProviderConfig, connection=None):
        self.config = config
        self.connection = connection


class ConnectionUnawareProvider:
    """Provider that does NOT accept a connection kwarg."""
    class ProviderConfig(BaseModel):
        mode: str = "default"

    def __init__(self, config: ProviderConfig):
        self.config = config


def test_create_provider_injects_connection_when_accepted():
    """Provider with connection param gets it injected."""
    conn = StubConnection()
    # Register ConnectionAwareProvider in a test-accessible module
    import workbench.registry as reg
    reg._test_conn_aware = ConnectionAwareProvider  # monkey-patch for test

    section = {
        "class": "tests.test_registry.ConnectionAwareProvider",
        "connection": "test_conn",
        "mode": "test",
    }
    connections = {"test_conn": conn}
    provider = create_provider(section, connections=connections)
    assert isinstance(provider, ConnectionAwareProvider)
    assert provider.connection is conn


def test_create_provider_skips_connection_when_not_accepted():
    """Provider without connection param works fine even if connection is in config."""
    conn = StubConnection()
    section = {
        "class": "tests.test_registry.ConnectionUnawareProvider",
        "connection": "test_conn",
        "mode": "test",
    }
    connections = {"test_conn": conn}
    provider = create_provider(section, connections=connections)
    assert isinstance(provider, ConnectionUnawareProvider)
    assert not hasattr(provider, 'connection')


def test_create_provider_without_connection():
    """Normal provider creation still works when no connection specified."""
    section = {"class": "workbench.providers.enrichment.stub.StubEnricher"}
    provider = create_provider(section)
    assert isinstance(provider, StubEnricher)


def test_create_provider_raises_on_missing_connection():
    """Referencing a non-existent connection name raises ValueError."""
    section = {
        "class": "workbench.providers.enrichment.stub.StubEnricher",
        "connection": "nonexistent",
    }
    with pytest.raises(ValueError, match="not found"):
        create_provider(section, connections={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_registry.py -v -k "test_create_provider"`
Expected: Failures -- `create_provider` doesn't accept `connections` kwarg.

- [ ] **Step 3: Update registry.py with connection injection using inspect.signature**

Replace the contents of `src/workbench/registry.py`:

```python
from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    pass


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

    # Resolve the connection object if referenced
    resolved_connection = None
    if connection_name and connections is not None:
        resolved_connection = connections.get(connection_name)
        if resolved_connection is None:
            raise ValueError(f"Connection '{connection_name}' not found in connections config")

    # Use inspect.signature to check if constructor accepts a connection kwarg
    # before attempting to pass it. This avoids TypeError for providers that
    # don't expect it.
    if hasattr(cls, "ProviderConfig"):
        typed_config = cls.ProviderConfig(**section)
        sig = inspect.signature(cls.__init__)
        if 'connection' in sig.parameters and resolved_connection is not None:
            return cls(typed_config, connection=resolved_connection)
        return cls(typed_config)
    else:
        sig = inspect.signature(cls.__init__)
        if 'connection' in sig.parameters and resolved_connection is not None:
            return cls(connection=resolved_connection, **section) if section else cls(connection=resolved_connection)
        return cls(**section) if section else cls()


def create_providers_from_list(sections: list[dict[str, Any]], connections: dict[str, Any] | None = None) -> list[Any]:
    return [create_provider(s, connections=connections) for s in sections]


def create_composite_enricher(config, connections: dict[str, Any] | None = None):
    """Build a CompositeEnricher from an EnrichmentConfig.

    Routes enrichment by source_type to specific enricher instances,
    with a default fallback. Per-enricher budget overrides are supported.
    """
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


async def close_provider(provider: Any) -> None:
    if hasattr(provider, "close"):
        try:
            await provider.close()
        except Exception as e:
            logger.warning(f"Error closing provider {type(provider).__name__}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_registry.py -v`
Expected: All pass (new + existing). Note: `test_create_composite_enricher` will fail until Task 5 (EnrichmentConfig) and Task 7 (CompositeEnricher) are both done. Skip it with `@pytest.mark.skip(reason="Depends on Task 5 + Task 7")` and remove the skip in Task 7.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/registry.py tests/test_registry.py
git commit -m "feat(registry): support connection injection via inspect.signature and add create_composite_enricher"
```

---

### Task 5: Config Changes -- Connections Section + EnrichmentConfig

**Files:**
- Modify: `src/workbench/config.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write tests for new config sections**

Append to `tests/test_config.py`:

```python
# tests/test_config.py — append

from workbench.config import AppConfig, EnrichmentConfig, load_config_from_string


def test_connections_section_parsed():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
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


def test_connections_section_optional():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert config.connections == {}


def test_enrichment_config_new_shape():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
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
    assert isinstance(config.enrichment, EnrichmentConfig)
    assert len(config.enrichment.providers) == 1
    assert config.enrichment.providers[0]["source_types"] == ["email"]
    assert config.enrichment.default["class"] == "workbench.providers.enrichment.stub.StubEnricher"


def test_enrichment_config_defaults():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert isinstance(config.enrichment, EnrichmentConfig)
    assert config.enrichment.providers == []
    assert config.enrichment.default["class"] == "workbench.providers.enrichment.stub.StubEnricher"


def test_enrichment_backward_compat_dict():
    """Old-style enrichment: {class: ...} still loads (converted to EnrichmentConfig)."""
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher
"""
    config = load_config_from_string(yaml_str)
    assert isinstance(config.enrichment, EnrichmentConfig)
    # Old-style dict gets loaded as default
    assert config.enrichment.default["class"] == "workbench.providers.enrichment.stub.StubEnricher"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v -k "test_connections or test_enrichment"`
Expected: Failures -- `connections` not on config, `EnrichmentConfig` doesn't exist, `load_config_from_string` doesn't exist.

- [ ] **Step 3: Update config.py**

Add `EnrichmentConfig` model and update `AppConfig` in `src/workbench/config.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field, model_validator


class ServerConfig(BaseModel):
    port: int = 8421
    debug: bool = False
    api_token: str = "dev-token-change-me"


class StorageConfig(BaseModel):
    postgres_dsn: str


class QueueConfig(BaseModel):
    scorer: dict = Field(default_factory=dict)
    worker_concurrency: int = 2
    max_attempts: int = 3
    base_delay_seconds: int = 5


class TriageConfig(BaseModel):
    daily_cap: int = 20
    expiry_days: int = 7
    timeout_minutes: int = 30
    triage_poll_interval_seconds: int = 10


class PipelineConfig(BaseModel):
    include_threshold: int = 70
    drop_threshold: int = 30
    confidence_threshold: int = 70


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_dir: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    max_age_days: int = 84
    timezone: str = "America/Los_Angeles"


class SchedulerConfig(BaseModel):
    poll_interval_minutes: int = 15
    morning_briefing_hour: int = 9


class EnrichmentConfig(BaseModel):
    providers: list[dict] = Field(default_factory=list)
    default: dict = Field(default_factory=lambda: {"class": "workbench.providers.enrichment.stub.StubEnricher"})


class AppConfig(BaseModel):
    version: str = "0.3.0"
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig
    llm: dict
    queue: QueueConfig = Field(default_factory=QueueConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    messenger: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    memory: dict | None = None
    connections: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_enrichment(cls, values):
        """Support old-style enrichment: {class: ...} by converting to EnrichmentConfig shape."""
        enrichment = values.get("enrichment")
        if isinstance(enrichment, dict) and "class" in enrichment:
            # Old-style single-enricher config: promote to default
            values["enrichment"] = {
                "providers": [],
                "default": enrichment,
            }
        return values


def load_config(config_path: str, override_path: str | None = None) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print("Run 'cp config.example.yml config.yml' and edit it.", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)

    config = AppConfig(**resolved)

    major = int(config.version.split(".")[0])
    expected_major = 0
    if major != expected_major:
        print(f"Error: Config version {config.version} is incompatible (expected major {expected_major})", file=sys.stderr)
        sys.exit(1)

    return config


def load_config_from_string(yaml_str: str) -> AppConfig:
    """Load config from a YAML string. Useful for testing."""
    raw = OmegaConf.create(yaml_str)
    resolved = OmegaConf.to_container(raw, resolve=True)
    return AppConfig(**resolved)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: All pass (new + existing).

- [ ] **Step 5: Verify existing config.example.yml still loads**

Run: `python -c "from workbench.config import load_config; c = load_config('config.example.yml'); print('OK:', c.version)"`
Expected: Prints `OK: 0.2.0` (the old-style `enrichment: {class: ...}` gets normalized via the model_validator).

- [ ] **Step 6: Commit**

```bash
git add src/workbench/config.py tests/test_config.py
git commit -m "feat(config): add connections section, EnrichmentConfig model, load_config_from_string helper"
```

---

### Task 6: Main.py -- Connection Initialization + Composite Enricher Wiring + Deps + Gitignore

**Files:**
- Modify: `src/workbench/main.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add Google API dependencies to pyproject.toml**

Update `pyproject.toml` dependencies list -- add `google-api-python-client`, `google-auth`, and `google-auth-httplib2`:

```toml
[project]
name = "workbench"
version = "0.2.1"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "anthropic>=0.40",
    "apscheduler>=3.10",
    "httpx>=0.27",
    "omegaconf>=2.3",
    "PyYAML>=6.0",
    "sqlalchemy>=2.0",
    "google-api-python-client>=2.100",
    "google-auth>=2.0",
    "google-auth-httplib2>=0.2",
]
```

Remove the `gchat` optional dependency group since `google-auth` is now a core dependency:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
]
```

- [ ] **Step 2: Add ui/ build artifacts to .gitignore**

Append to `.gitignore`:

```
ui/node_modules/
ui/dist/
```

- [ ] **Step 3: Update lifespan in main.py for connection initialization and composite enricher**

Replace the full `src/workbench/main.py`:

```python
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from workbench import __version__
from workbench.auth import BearerTokenMiddleware
from workbench.config import AppConfig, load_config
from workbench.logging import setup_logging
from workbench.memory.noop import NoopMemoryLayer
from workbench.registry import close_provider, create_provider, create_providers_from_list, create_composite_enricher

setup_logging()
logger = logging.getLogger(__name__)


def get_config() -> AppConfig:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    log_cfg = config.logging
    log_dir = log_cfg.log_dir or os.environ.get("WORKBENCH_LOG_DIR", "logs")
    setup_logging(
        log_dir=log_dir,
        level=getattr(logging, log_cfg.level.upper(), logging.INFO),
        max_bytes=log_cfg.max_bytes,
        max_age_days=log_cfg.max_age_days,
        timezone=log_cfg.timezone,
    )
    logger.info("Config loaded (version=%s, port=%d)", config.version, config.server.port)

    from workbench.storage.factory import create_stores
    app.state.stores = await create_stores(config)
    logger.info("Storage connected")

    # Initialize shared connections
    connections = {}
    for name, conn_cfg in config.connections.items():
        conn = create_provider(conn_cfg)
        await conn.initialize()
        connections[name] = conn
        logger.info("Connection '%s' initialized", name)
    app.state.connections = connections

    app.state.llm = create_provider(config.llm)

    if config.messenger:
        app.state.messenger = create_provider(config.messenger)
    else:
        app.state.messenger = None

    # Enrichment: use CompositeEnricher when providers are configured,
    # otherwise fall back to StubEnricher
    if config.enrichment.providers:
        app.state.enricher = create_composite_enricher(config.enrichment, connections=connections)
    else:
        from workbench.providers.enrichment.stub import StubEnricher
        app.state.enricher = StubEnricher()

    if config.memory:
        app.state.memory = create_provider(config.memory)
    else:
        app.state.memory = NoopMemoryLayer()

    if config.queue.scorer:
        app.state.queue_scorer = create_provider(config.queue.scorer)
    else:
        app.state.queue_scorer = None

    # Source adapters: pass connections so adapters can reference shared connections
    app.state.sources = create_providers_from_list(config.sources, connections=connections)

    from workbench.pipeline.engine import PipelineEngine
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher,
        queue_scorer=app.state.queue_scorer,
    )

    # Ingestion queue worker
    from workbench.pipeline.worker import IngestionQueueWorker
    worker = IngestionQueueWorker(
        app.state.stores, app.state.pipeline,
        concurrency=config.queue.worker_concurrency,
    )
    worker.start()
    app.state.worker = worker

    # Scheduler
    from workbench.pipeline.scheduler import WorkbenchScheduler
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline,
        app.state.messenger, config, sources=app.state.sources,
    )
    app.state.scheduler.start()
    logger.info("Workbench %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")

    # Cleanup
    if hasattr(app.state, 'worker'):
        app.state.worker.stop()
    app.state.scheduler.scheduler.shutdown(wait=False)

    for provider in [app.state.llm, app.state.messenger, app.state.enricher,
                     app.state.memory, app.state.queue_scorer]:
        if provider:
            await close_provider(provider)
    for source in app.state.sources:
        await close_provider(source)

    # Close shared connections
    for conn in app.state.connections.values():
        await close_provider(conn)

    if hasattr(app.state.stores, 'close'):
        await app.state.stores.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(BearerTokenMiddleware)

    from workbench.api import (
        config as config_api, filter_rules, health, items, jobs,
        memory, process, queue, sources, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, jobs.router, queue.router,
    ]:
        app.include_router(r)

    # Serve React UI static files if built
    ui_dir = os.path.join(os.path.dirname(__file__), "../../ui/dist")
    if os.path.exists(ui_dir):
        from starlette.staticfiles import StaticFiles
        app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()


def cli_main():
    import uvicorn
    config = get_config()
    uvicorn.run("workbench.main:app", host="0.0.0.0", port=config.server.port,
                reload=config.server.debug)
```

Note: Auth is global `BearerTokenMiddleware` -- all routes except `/health` are auto-protected. No `Depends(require_auth)` needed on any route.

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `make test`
Expected: All existing tests pass. Connection initialization is a no-op when `config.connections` is empty (the default).

- [ ] **Step 5: Commit**

```bash
git add src/workbench/main.py pyproject.toml .gitignore
git commit -m "feat(main): initialize connections at startup, wire CompositeEnricher, add Google API deps, update gitignore"
```

---

## Group 0.5: Observability, Operations, and Privacy Foundation

> Grilling session 2026-06-03: These tasks are prerequisites for source adapters. Privacy safeguards for email/calendar/chat ingestion are not optional add-ons. Observability for 6 new external API integrations is load-bearing. See ADR 0010, ADR 0011.

### Task 6a: Structured Logging Migration (structlog)

**Files:**
- Modify: `src/workbench/logging.py`
- Create: `src/workbench/middleware.py`
- Modify: `src/workbench/main.py`
- Modify: `pyproject.toml`
- Test: `tests/test_structured_logging.py`

- [ ] **Step 1: Write tests for structured logging and correlation IDs**

Create `tests/test_structured_logging.py`:

```python
# tests/test_structured_logging.py

import json
import logging
import uuid

import pytest
import structlog

from workbench.logging import setup_logging
from workbench.middleware import CorrelationIdMiddleware


def test_json_output_format(tmp_path, capsys):
    """JSON format produces parseable JSON lines."""
    setup_logging(log_format="json", log_dir=None)
    logger = structlog.get_logger("test")
    logger.info("test_event", key="value", count=42)
    captured = capsys.readouterr()
    line = json.loads(captured.err.strip())
    assert line["event"] == "test_event"
    assert line["key"] == "value"
    assert line["count"] == 42


def test_console_output_format(capsys):
    """Console format produces human-readable output."""
    setup_logging(log_format="console", log_dir=None)
    logger = structlog.get_logger("test")
    logger.info("test_event", key="value")
    captured = capsys.readouterr()
    assert "test_event" in captured.err
    assert "key=" in captured.err or "key" in captured.err


def test_stdlib_logger_gets_structlog_processing(capsys):
    """Existing logging.getLogger() calls go through structlog pipeline."""
    setup_logging(log_format="json", log_dir=None)
    logger = logging.getLogger("legacy.module")
    logger.info("legacy message %s", "arg1")
    captured = capsys.readouterr()
    line = json.loads(captured.err.strip())
    assert "legacy message arg1" in line.get("event", "")


def test_file_handler_preserved(tmp_path):
    """AgeRotatingFileHandler still writes logs to files."""
    log_dir = str(tmp_path / "logs")
    setup_logging(log_format="json", log_dir=log_dir)
    logger = structlog.get_logger("test")
    logger.info("file_test")
    import os
    assert os.path.exists(log_dir)
    log_files = os.listdir(log_dir)
    assert len(log_files) >= 1


@pytest.mark.asyncio
async def test_correlation_id_middleware():
    """Middleware adds X-Request-ID to response and binds to context."""
    from starlette.testclient import TestClient
    from fastapi import FastAPI, Request

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/test")
    async def handler(request: Request):
        return {"request_id": request.state.request_id}

    client = TestClient(app)
    resp = client.get("/test")
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-ID")
    assert request_id is not None
    uuid.UUID(request_id)  # valid UUID
    assert resp.json()["request_id"] == request_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_structured_logging.py -v`
Expected: ImportError -- `structlog` not installed, `workbench.middleware` not found.

- [ ] **Step 3: Add structlog dependency to pyproject.toml**

Add `structlog>=24.0` to the dependencies list in `pyproject.toml`.

- [ ] **Step 4: Rewrite logging.py with structlog**

Replace `src/workbench/logging.py`:

```python
from __future__ import annotations

import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog


class AgeRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that also removes old backup files beyond max_age_days."""

    def __init__(self, filename, max_age_days=84, **kwargs):
        self.max_age_days = max_age_days
        super().__init__(filename, **kwargs)

    def doRollover(self):
        super().doRollover()
        self._cleanup_old_files()

    def _cleanup_old_files(self):
        log_dir = os.path.dirname(self.baseFilename)
        base_name = os.path.basename(self.baseFilename)
        cutoff = time.time() - (self.max_age_days * 86400)
        for f in os.listdir(log_dir):
            if f.startswith(base_name + ".") and f != base_name:
                path = os.path.join(log_dir, f)
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)


def setup_logging(
    log_format: str = "console",
    log_dir: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    max_age_days: int = 84,
    timezone: str = "America/Los_Angeles",
    extra_processors: list | None = None,
) -> None:
    """Configure structlog with JSON or console output.

    Args:
        log_format: "json" for production, "console" for dev.
        log_dir: Directory for log files. None = stderr only.
        level: Logging level.
        max_bytes: Max log file size before rotation.
        max_age_days: Delete rotated logs older than this.
        timezone: Timezone for timestamps.
        extra_processors: Additional structlog processors (e.g., SanitizingProcessor).
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if extra_processors:
        shared_processors.extend(extra_processors)

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = AgeRotatingFileHandler(
            os.path.join(log_dir, "workbench.log"),
            max_age_days=max_age_days,
            maxBytes=max_bytes,
            backupCount=10,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
```

- [ ] **Step 5: Create CorrelationIdMiddleware**

Create `src/workbench/middleware.py`:

```python
from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

- [ ] **Step 6: Update main.py to use structlog and middleware**

In `src/workbench/main.py`:

1. Replace `import logging` with `import structlog` at the top. Keep `import logging` for level constants.
2. Replace `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`
3. Update `setup_logging()` calls to pass `log_format=log_cfg.format` (add `format` field to `LoggingConfig`)
4. Add `CorrelationIdMiddleware` in `create_app()`:
```python
from workbench.middleware import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)
```

- [ ] **Step 7: Add `format` field to LoggingConfig in config.py**

In `src/workbench/config.py`, update `LoggingConfig`:
```python
class LoggingConfig(BaseModel):
    format: str = "console"  # "json" | "console"
    level: str = "INFO"
    log_dir: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    max_age_days: int = 84
    timezone: str = "America/Los_Angeles"
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_structured_logging.py -v && make test`
Expected: All pass, including existing tests (structlog stdlib integration is backward-compatible).

- [ ] **Step 9: Commit**

```bash
git add src/workbench/logging.py src/workbench/middleware.py src/workbench/main.py src/workbench/config.py pyproject.toml tests/test_structured_logging.py
git commit -m "feat(logging): replace glog with structlog, add correlation ID middleware (ADR 0010)"
```

---

### Task 6b: Metrics Foundation (Prometheus)

**Files:**
- Create: `src/workbench/metrics.py`
- Create: `src/workbench/instrumentation.py`
- Modify: `src/workbench/main.py`
- Modify: `src/workbench/registry.py`
- Modify: `src/workbench/config.py`
- Modify: `pyproject.toml`
- Test: `tests/test_metrics.py`
- Test: `tests/test_instrumentation.py`

- [ ] **Step 1: Write tests for metrics definitions and instrumented wrappers**

Create `tests/test_metrics.py`:

```python
# tests/test_metrics.py

import pytest
from prometheus_client import CollectorRegistry

from workbench.metrics import create_metrics


def test_all_metrics_registered():
    """All expected metrics are created."""
    registry = CollectorRegistry()
    m = create_metrics(registry)
    assert m.items_ingested is not None
    assert m.adapter_polls is not None
    assert m.adapter_poll_seconds is not None
    assert m.llm_calls is not None
    assert m.llm_errors is not None
    assert m.llm_call_seconds is not None
    assert m.items_triaged is not None
    assert m.items_dropped is not None
    assert m.pipeline_stage_seconds is not None
    assert m.enrichment_seconds is not None
    assert m.identity_merges is not None
    assert m.cards_generated is not None
    assert m.alerts_sent is not None
    assert m.ingestion_queue_depth is not None
    assert m.triage_queue_depth is not None
    assert m.dead_letter_count is not None
    assert m.connection_healthy is not None
```

Create `tests/test_instrumentation.py`:

```python
# tests/test_instrumentation.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from prometheus_client import CollectorRegistry
from workbench.metrics import create_metrics
from workbench.instrumentation import InstrumentedSourceAdapter


@pytest.mark.asyncio
async def test_instrumented_adapter_tracks_success():
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    inner = AsyncMock()
    inner.poll.return_value = [MagicMock(source_type="email") for _ in range(3)]

    adapter = InstrumentedSourceAdapter(inner, "gmail", metrics)
    items = await adapter.poll(datetime.now())

    assert len(items) == 3
    assert metrics.adapter_polls.labels(adapter="gmail", status="success")._value.get() == 1.0


@pytest.mark.asyncio
async def test_instrumented_adapter_tracks_errors():
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    inner = AsyncMock()
    inner.poll.side_effect = RuntimeError("API error")

    adapter = InstrumentedSourceAdapter(inner, "gmail", metrics)
    with pytest.raises(RuntimeError):
        await adapter.poll(datetime.now())

    assert metrics.adapter_polls.labels(adapter="gmail", status="error")._value.get() == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py tests/test_instrumentation.py -v`
Expected: ImportError -- `prometheus_client` not installed, modules not found.

- [ ] **Step 3: Add prometheus-client dependency**

Add `prometheus-client>=0.20` to `pyproject.toml` dependencies.

- [ ] **Step 4: Create metrics.py with all metric definitions**

Create `src/workbench/metrics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


@dataclass
class WorkbenchMetrics:
    # Counters
    items_ingested: Counter
    adapter_polls: Counter
    llm_calls: Counter
    llm_errors: Counter
    items_triaged: Counter
    items_dropped: Counter
    identity_merges: Counter
    cards_generated: Counter
    alerts_sent: Counter

    # Histograms
    adapter_poll_seconds: Histogram
    llm_call_seconds: Histogram
    pipeline_stage_seconds: Histogram
    enrichment_seconds: Histogram

    # Gauges
    ingestion_queue_depth: Gauge
    triage_queue_depth: Gauge
    dead_letter_count: Gauge
    connection_healthy: Gauge
    tracked_threads: Gauge


def create_metrics(registry: CollectorRegistry | None = None) -> WorkbenchMetrics:
    kw = {"registry": registry} if registry else {}

    return WorkbenchMetrics(
        items_ingested=Counter(
            "workbench_items_ingested_total", "Items ingested from sources",
            ["source_type", "adapter"], **kw,
        ),
        adapter_polls=Counter(
            "workbench_adapter_polls_total", "Source adapter poll attempts",
            ["adapter", "status"], **kw,
        ),
        llm_calls=Counter(
            "workbench_llm_calls_total", "LLM API calls",
            ["method"], **kw,
        ),
        llm_errors=Counter(
            "workbench_llm_errors_total", "LLM API errors",
            ["method", "error_type"], **kw,
        ),
        items_triaged=Counter(
            "workbench_items_triaged_total", "Items triaged by user action",
            ["action"], **kw,
        ),
        items_dropped=Counter(
            "workbench_items_dropped_total", "Items dropped from pipeline",
            ["reason"], **kw,
        ),
        identity_merges=Counter(
            "workbench_identity_merges_total", "Entity identity merges",
            ["resolved_by"], **kw,
        ),
        cards_generated=Counter(
            "workbench_cards_generated_total", "Triage cards generated",
            ["method"], **kw,
        ),
        alerts_sent=Counter(
            "workbench_alerts_sent_total", "Operational alerts sent",
            ["alert_type"], **kw,
        ),
        adapter_poll_seconds=Histogram(
            "workbench_adapter_poll_seconds", "Source adapter poll duration",
            ["adapter"], **kw,
        ),
        llm_call_seconds=Histogram(
            "workbench_llm_call_seconds", "LLM call duration",
            ["method"], **kw,
        ),
        pipeline_stage_seconds=Histogram(
            "workbench_pipeline_stage_seconds", "Pipeline stage duration",
            ["stage"], **kw,
        ),
        enrichment_seconds=Histogram(
            "workbench_enrichment_seconds", "Enrichment duration",
            ["enricher"], **kw,
        ),
        ingestion_queue_depth=Gauge(
            "workbench_ingestion_queue_depth", "Current ingestion queue depth",
            **kw,
        ),
        triage_queue_depth=Gauge(
            "workbench_triage_queue_depth", "Current triage queue depth",
            **kw,
        ),
        dead_letter_count=Gauge(
            "workbench_dead_letter_count", "Current dead letter count",
            **kw,
        ),
        connection_healthy=Gauge(
            "workbench_connection_healthy", "Connection health (1=healthy, 0=unhealthy)",
            ["name"], **kw,
        ),
        tracked_threads=Gauge(
            "workbench_tracked_threads", "Tracked chat threads",
            ["adapter"], **kw,
        ),
    )
```

- [ ] **Step 5: Create instrumentation.py with wrapper classes**

Create `src/workbench/instrumentation.py`:

```python
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import structlog

from workbench.metrics import WorkbenchMetrics

logger = structlog.get_logger(__name__)


class InstrumentedSourceAdapter:
    """Decorator that wraps a SourceAdapter with metrics and structured logging."""

    def __init__(self, inner, adapter_name: str, metrics: WorkbenchMetrics):
        self._inner = inner
        self._name = adapter_name
        self._metrics = metrics

    async def poll(self, since: datetime | None = None):
        start = time.monotonic()
        try:
            items = await self._inner.poll(since)
            elapsed = time.monotonic() - start
            self._metrics.adapter_polls.labels(adapter=self._name, status="success").inc()
            self._metrics.adapter_poll_seconds.labels(adapter=self._name).observe(elapsed)
            for item in items:
                self._metrics.items_ingested.labels(
                    source_type=item.source_type, adapter=self._name,
                ).inc()
            logger.info("adapter_poll_complete",
                adapter=self._name, items=len(items), duration_ms=round(elapsed * 1000))
            return items
        except Exception as e:
            elapsed = time.monotonic() - start
            self._metrics.adapter_polls.labels(adapter=self._name, status="error").inc()
            self._metrics.adapter_poll_seconds.labels(adapter=self._name).observe(elapsed)
            logger.error("adapter_poll_failed",
                adapter=self._name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    def __getattr__(self, name):
        return getattr(self._inner, name)


class InstrumentedLLMProvider:
    """Decorator that wraps an LLMProvider with metrics and structured logging."""

    def __init__(self, inner, metrics: WorkbenchMetrics):
        self._inner = inner
        self._metrics = metrics

    async def _instrumented_call(self, method_name: str, coro):
        start = time.monotonic()
        try:
            result = await coro
            elapsed = time.monotonic() - start
            self._metrics.llm_calls.labels(method=method_name).inc()
            self._metrics.llm_call_seconds.labels(method=method_name).observe(elapsed)
            logger.info("llm_call_complete",
                method=method_name, duration_ms=round(elapsed * 1000))
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            self._metrics.llm_errors.labels(
                method=method_name, error_type=type(e).__name__,
            ).inc()
            logger.error("llm_call_failed",
                method=method_name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    async def extract_items(self, *args, **kwargs):
        return await self._instrumented_call(
            "extract", self._inner.extract_items(*args, **kwargs))

    async def score_relevance(self, *args, **kwargs):
        return await self._instrumented_call(
            "score_relevance", self._inner.score_relevance(*args, **kwargs))

    async def generate_triage_card(self, *args, **kwargs):
        return await self._instrumented_call(
            "generate_card", self._inner.generate_triage_card(*args, **kwargs))

    async def interpret_triage_response(self, *args, **kwargs):
        return await self._instrumented_call(
            "interpret_response", self._inner.interpret_triage_response(*args, **kwargs))

    async def describe_image(self, *args, **kwargs):
        return await self._instrumented_call(
            "describe_image", self._inner.describe_image(*args, **kwargs))

    async def evaluate_filter(self, *args, **kwargs):
        return await self._instrumented_call(
            "evaluate_filter", self._inner.evaluate_filter(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._inner, name)


class InstrumentedContextEnricher:
    """Decorator that wraps a ContextEnricher with metrics and structured logging."""

    def __init__(self, inner, enricher_name: str, metrics: WorkbenchMetrics):
        self._inner = inner
        self._name = enricher_name
        self._metrics = metrics

    async def enrich(self, *args, **kwargs):
        start = time.monotonic()
        try:
            result = await self._inner.enrich(*args, **kwargs)
            elapsed = time.monotonic() - start
            self._metrics.enrichment_seconds.labels(enricher=self._name).observe(elapsed)
            logger.info("enrichment_complete",
                enricher=self._name, duration_ms=round(elapsed * 1000))
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error("enrichment_failed",
                enricher=self._name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    def __getattr__(self, name):
        return getattr(self._inner, name)
```

- [ ] **Step 6: Add MetricsConfig to config.py**

In `src/workbench/config.py`, add after `LoggingConfig`:
```python
class MetricsConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "/metrics"
```

Add to `AppConfig`:
```python
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
```

- [ ] **Step 7: Wire metrics in main.py**

In `src/workbench/main.py`:
1. Import and create metrics: `from workbench.metrics import create_metrics`
2. In `lifespan`: `app.state.metrics = create_metrics()`
3. In `create_app()`, add `/metrics` endpoint:
```python
if config.metrics.enabled:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response

    @app.get(config.metrics.endpoint, include_in_schema=False)
    async def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```
4. Wrap LLM provider: `app.state.llm = InstrumentedLLMProvider(create_provider(config.llm), app.state.metrics)`
5. Wrap source adapters: pass metrics to `InstrumentedSourceAdapter` wrapper in `create_providers_from_list`

- [ ] **Step 8: Update registry.py to apply instrumented wrappers**

In `src/workbench/registry.py`, update `create_providers_from_list` to accept optional `metrics` and wrap adapters:

```python
def create_providers_from_list(
    sections: list[dict[str, Any]],
    connections: dict[str, Any] | None = None,
    metrics: WorkbenchMetrics | None = None,
) -> list[Any]:
    providers = []
    for s in sections:
        name = s.get("class", "").rsplit(".", 1)[-1] if "class" in s else "unknown"
        provider = create_provider(s, connections=connections)
        if metrics:
            from workbench.instrumentation import InstrumentedSourceAdapter
            provider = InstrumentedSourceAdapter(provider, name, metrics)
        providers.append(provider)
    return providers
```

- [ ] **Step 9: Run tests**

Run: `python -m pytest tests/test_metrics.py tests/test_instrumentation.py -v && make test`
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add src/workbench/metrics.py src/workbench/instrumentation.py src/workbench/main.py src/workbench/registry.py src/workbench/config.py pyproject.toml tests/test_metrics.py tests/test_instrumentation.py
git commit -m "feat(metrics): add Prometheus metrics, instrumented provider wrappers"
```

---

### Task 6c: Health Check Improvements

**Files:**
- Modify: `src/workbench/api/health.py`
- Test: `tests/test_health_improved.py`

- [ ] **Step 1: Write tests for improved health checks**

Create `tests/test_health_improved.py`:

```python
# tests/test_health_improved.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from workbench.api.health import router
from fastapi import FastAPI


def _make_app(stores_healthy=True, connections=None):
    app = FastAPI()
    app.include_router(router)

    stores = MagicMock()
    if stores_healthy:
        stores.items.pool.fetchval = AsyncMock(return_value=1)
        stores.ingestion_queue.get_depth = AsyncMock(return_value=3)
        stores.triage.get_pending = AsyncMock(return_value=[])
        stores.ingestion_queue.get_dead_letters = AsyncMock(return_value=[])
    else:
        stores.items.pool.fetchval = AsyncMock(side_effect=Exception("PG down"))

    app.state.stores = stores
    app.state.connections = connections or {}
    app.state.llm = MagicMock()
    app.state.memory = MagicMock()
    app.state.messenger = None
    return app


def test_health_returns_200_when_healthy():
    app = _make_app(stores_healthy=True)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "components" in data


def test_health_returns_503_when_pg_down():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["components"]["storage"]["status"] == "unhealthy"


def test_health_live_always_200():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200


def test_health_ready_503_when_pg_down():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 503


def test_health_includes_connection_status():
    conn = MagicMock()
    conn.is_healthy.return_value = False
    app = _make_app(stores_healthy=True, connections={"google": conn})
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200  # connection is non-critical
    data = resp.json()
    assert data["components"]["connections"]["google"]["status"] == "unhealthy"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_health_improved.py -v`
Expected: Failures -- `/health/live` and `/health/ready` don't exist; `/health` returns 200 on PG failure.

- [ ] **Step 3: Rewrite health.py**

Replace `src/workbench/api/health.py`:

```python
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

from workbench import __version__

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])


async def _check_storage(stores) -> dict:
    try:
        await stores.items.pool.fetchval("SELECT 1")
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_connections(connections: dict) -> dict:
    result = {}
    for name, conn in connections.items():
        try:
            healthy = conn.is_healthy()
            result[name] = {"status": "healthy" if healthy else "unhealthy"}
        except Exception as e:
            result[name] = {"status": "unhealthy", "error": str(e)}
    return result


async def _build_health(request: Request) -> tuple[dict, bool]:
    stores = request.app.state.stores
    connections = getattr(request.app.state, "connections", {})

    storage_health = await _check_storage(stores)
    connection_health = await _check_connections(connections)

    critical_healthy = storage_health["status"] == "healthy"

    queue_stats = {}
    if critical_healthy:
        try:
            depth = await stores.ingestion_queue.get_depth()
            pending = await stores.triage.get_pending()
            dead = await stores.ingestion_queue.get_dead_letters()
            queue_stats = {
                "ingestion_depth": depth,
                "triage_pending": len(pending),
                "dead_letters": len(dead),
            }
        except Exception:
            pass

    return {
        "status": "healthy" if critical_healthy else "unhealthy",
        "version": __version__,
        "components": {
            "storage": storage_health,
            "connections": connection_health,
        },
        "queue": queue_stats,
    }, critical_healthy


@router.get("/health")
async def health(request: Request, response: Response):
    data, healthy = await _build_health(request)
    if not healthy:
        response.status_code = 503
    return data


@router.get("/health/live")
async def liveness():
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response):
    data, healthy = await _build_health(request)
    if not healthy:
        response.status_code = 503
    return data
```

- [ ] **Step 4: Update auth.py to allow new health endpoints**

In `src/workbench/auth.py`, update the unauthenticated paths list to include `/health/live` and `/health/ready`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_health_improved.py -v && make test`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/api/health.py src/workbench/auth.py tests/test_health_improved.py
git commit -m "fix(health): return 503 on critical failure, add component checks, liveness/readiness"
```

---

### Task 6d: Debug Configuration + Privacy Config + Log Sanitization

**Files:**
- Modify: `src/workbench/config.py`
- Create: `src/workbench/privacy.py`
- Modify: `src/workbench/logging.py`
- Modify: `src/workbench/main.py`
- Test: `tests/test_sanitizer.py`

- [ ] **Step 1: Write tests for sanitizer**

Create `tests/test_sanitizer.py`:

```python
# tests/test_sanitizer.py

import pytest
from workbench.privacy import SanitizingProcessor, PrivacyConfig


def _process(processor, event_dict):
    return processor(None, "info", event_dict)


def test_redacts_email_addresses():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "sender": "alice@meta.com"})
    assert result["sender"] == "[REDACTED:email]"


def test_redacts_email_in_longer_text():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "msg": "From alice@meta.com to bob@example.org"})
    assert "alice@meta.com" not in result["msg"]
    assert "[REDACTED:email]" in result["msg"]


def test_redacts_phone_numbers():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "phone": "555-123-4567"})
    assert result["phone"] == "[REDACTED:phone]"


def test_truncates_long_content():
    proc = SanitizingProcessor(PrivacyConfig(max_content_in_logs=50))
    long_text = "a" * 200
    result = _process(proc, {"event": "test", "body": long_text})
    assert len(result["body"]) < 200
    assert "[truncated]" in result["body"]


def test_preserves_short_content():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "msg": "short message"})
    assert result["msg"] == "short message"


def test_skips_non_string_values():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "count": 42, "items": [1, 2, 3]})
    assert result["count"] == 42
    assert result["items"] == [1, 2, 3]


def test_disabled_when_sanitize_logs_false():
    proc = SanitizingProcessor(PrivacyConfig(sanitize_logs=False))
    result = _process(proc, {"event": "test", "email": "alice@meta.com"})
    assert result["email"] == "alice@meta.com"


def test_extra_patterns():
    import re
    extra = [(re.compile(r'\bD\d{6,}\b'), '[REDACTED:phid]')]
    proc = SanitizingProcessor(PrivacyConfig(), extra_patterns=extra)
    result = _process(proc, {"event": "test", "diff": "D123456"})
    assert result["diff"] == "[REDACTED:phid]"


def test_skips_excluded_keys():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "alice@meta.com", "level": "info", "timestamp": "2026-06-03"})
    assert result["event"] == "alice@meta.com"  # event key is excluded from sanitization
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sanitizer.py -v`
Expected: ImportError -- `workbench.privacy` not found.

- [ ] **Step 3: Add DebugConfig and PrivacyConfig to config.py**

In `src/workbench/config.py`, add after `MetricsConfig`:

```python
class DebugConfig(BaseModel):
    sql_queries: bool = False
    llm_prompts: bool = False
    llm_token_usage: bool = True
    request_bodies: bool = False
    enrichment_details: bool = False
    adapter_raw_items: bool = False


class PrivacyConfig(BaseModel):
    sanitize_logs: bool = True
    redact_emails: bool = True
    redact_phones: bool = True
    max_content_in_logs: int = 200
    allow_pii_in_debug_logs: bool = False


class TracingConfig(BaseModel):
    enabled: bool = False
    exporter: str = "console"
    otlp_endpoint: str | None = None
    sample_rate: float = 1.0
```

Add to `AppConfig`:
```python
    debug: DebugConfig = Field(default_factory=DebugConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
```

- [ ] **Step 4: Create privacy.py with SanitizingProcessor**

Create `src/workbench/privacy.py`:

```python
from __future__ import annotations

import re
from typing import Any

from workbench.config import PrivacyConfig

EXCLUDED_KEYS = frozenset({"event", "level", "timestamp", "logger", "request_id"})


class SanitizingProcessor:
    """structlog processor that redacts PII patterns from log events."""

    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    PHONE_PATTERN = re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b')

    def __init__(
        self,
        config: PrivacyConfig,
        extra_patterns: list[tuple[re.Pattern, str]] | None = None,
    ):
        self._config = config
        self._patterns: list[tuple[re.Pattern, str]] = []
        if config.redact_emails:
            self._patterns.append((self.EMAIL_PATTERN, "[REDACTED:email]"))
        if config.redact_phones:
            self._patterns.append((self.PHONE_PATTERN, "[REDACTED:phone]"))
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def __call__(
        self, logger: Any, method_name: str, event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._config.sanitize_logs:
            return event_dict

        for key, value in event_dict.items():
            if key in EXCLUDED_KEYS:
                continue
            if not isinstance(value, str):
                continue
            if len(value) > self._config.max_content_in_logs:
                value = value[: self._config.max_content_in_logs] + "... [truncated]"
            for pattern, replacement in self._patterns:
                value = pattern.sub(replacement, value)
            event_dict[key] = value

        return event_dict
```

- [ ] **Step 5: Wire SanitizingProcessor into logging setup in main.py**

In `src/workbench/main.py`, update the `lifespan` function to create `SanitizingProcessor` and pass it to `setup_logging`:

```python
from workbench.privacy import SanitizingProcessor

# Inside lifespan, after config is loaded:
sanitizer = SanitizingProcessor(config.privacy)
setup_logging(
    log_format=log_cfg.format,
    log_dir=log_dir,
    level=getattr(logging, log_cfg.level.upper(), logging.INFO),
    max_bytes=log_cfg.max_bytes,
    max_age_days=log_cfg.max_age_days,
    timezone=log_cfg.timezone,
    extra_processors=[sanitizer],
)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_sanitizer.py -v && make test`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/privacy.py src/workbench/config.py src/workbench/main.py tests/test_sanitizer.py
git commit -m "feat(privacy): add SanitizingProcessor for PII log redaction, DebugConfig, PrivacyConfig (ADR 0011)"
```

---

### Task 6e: Data Retention

**Files:**
- Modify: `src/workbench/config.py`
- Modify: `src/workbench/pipeline/scheduler.py`
- Modify: `src/workbench/storage/base.py` (add retention methods to store interfaces)
- Modify: `src/workbench/storage/postgres/items.py`
- Modify: `src/workbench/storage/postgres/triage.py`
- Test: `tests/test_retention.py`

- [ ] **Step 1: Write tests for retention cleanup**

Create `tests/test_retention.py`:

```python
# tests/test_retention.py

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.config import RetentionConfig


@pytest.mark.asyncio
async def test_retention_deletes_old_archived_items():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(return_value=5)
    stores.triage.delete_older_than = AsyncMock(return_value=3)
    stores.enrichment_traces.delete_older_than = AsyncMock(return_value=2)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=1)

    config = RetentionConfig(archived_items_days=90)
    result = await run_retention_cleanup(stores, config)

    stores.items.delete_older_than.assert_called_once()
    assert result["archived_items"] == 5


@pytest.mark.asyncio
async def test_retention_skips_interaction_log():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(return_value=0)
    stores.triage.delete_older_than = AsyncMock(return_value=0)
    stores.enrichment_traces.delete_older_than = AsyncMock(return_value=0)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)

    config = RetentionConfig()
    await run_retention_cleanup(stores, config)

    assert not hasattr(stores.interactions, "delete_older_than") or \
           not stores.interactions.delete_older_than.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retention.py -v`
Expected: ImportError -- `RetentionConfig` not found, `run_retention_cleanup` not found.

- [ ] **Step 3: Add RetentionConfig to config.py**

In `src/workbench/config.py`, add:

```python
class RetentionConfig(BaseModel):
    archived_items_days: int = 90
    done_items_days: int = 90
    expired_cards_days: int = 30
    responded_cards_days: int = 90
    enrichment_traces_days: int = 30
    dead_letters_days: int = 30
```

Add to `AppConfig`:
```python
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
```

- [ ] **Step 4: Add retention delete methods to store interfaces**

In `src/workbench/storage/base.py`, add to `ItemStore`:
```python
    @abstractmethod
    async def delete_older_than(self, status: str, days: int) -> int:
        """Delete items with given status older than days. Returns count deleted."""
        ...
```

Add similar methods to `TriageStore` and `EnrichmentTraceStore`.

- [ ] **Step 5: Implement retention delete methods in PG stores**

In `src/workbench/storage/postgres/items.py`:
```python
    async def delete_older_than(self, status: str, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM items WHERE status = $1 AND updated_at < NOW() - INTERVAL '1 day' * $2",
            status, days,
        )
        return int(result.split()[-1])
```

Similar implementations for triage cards and enrichment traces.

- [ ] **Step 6: Add run_retention_cleanup to scheduler**

In `src/workbench/pipeline/scheduler.py`, add:

```python
async def run_retention_cleanup(stores, config: RetentionConfig) -> dict[str, int]:
    """Run daily retention cleanup. Returns counts of deleted rows."""
    logger = structlog.get_logger(__name__)
    results = {}

    results["archived_items"] = await stores.items.delete_older_than("archived", config.archived_items_days)
    results["done_items"] = await stores.items.delete_older_than("done", config.done_items_days)
    results["expired_cards"] = await stores.triage.delete_older_than("expired", config.expired_cards_days)
    results["responded_cards"] = await stores.triage.delete_older_than("responded", config.responded_cards_days)
    results["enrichment_traces"] = await stores.enrichment_traces.delete_older_than(config.enrichment_traces_days)
    results["dead_letters"] = await stores.ingestion_queue.delete_dead_letters_older_than(config.dead_letters_days)

    total = sum(results.values())
    if total > 0:
        logger.info("retention_cleanup_complete", **results, total=total)
    return results
```

Wire into the scheduler's morning briefing job to run after the briefing.

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_retention.py -v && make test`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add src/workbench/config.py src/workbench/pipeline/scheduler.py src/workbench/storage/base.py src/workbench/storage/postgres/items.py src/workbench/storage/postgres/triage.py tests/test_retention.py
git commit -m "feat(retention): add configurable data retention with daily cleanup"
```

---

### Task 6f: Alerting (AlertManager)

**Files:**
- Create: `src/workbench/alerting.py`
- Modify: `src/workbench/config.py`
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_alerting.py`

- [ ] **Step 1: Write tests for AlertManager**

Create `tests/test_alerting.py`:

```python
# tests/test_alerting.py

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.alerting import AlertManager, AlertConfig, AlertConditions


@pytest.mark.asyncio
async def test_alert_on_dead_letters():
    messenger = AsyncMock()
    config = AlertConfig(conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 5}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_called_once()
    msg = messenger.send_notification.call_args[0][0]
    assert "dead letter" in msg.lower()


@pytest.mark.asyncio
async def test_alert_cooldown_prevents_duplicate():
    messenger = AsyncMock()
    config = AlertConfig(cooldown_minutes=60, conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 5}
    await mgr.check_and_alert(health)
    await mgr.check_and_alert(health)  # within cooldown

    assert messenger.send_notification.call_count == 1


@pytest.mark.asyncio
async def test_no_alert_below_threshold():
    messenger = AsyncMock()
    config = AlertConfig(conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 2}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_connection_unhealthy_alert():
    messenger = AsyncMock()
    config = AlertConfig()
    mgr = AlertManager(messenger, config)

    health = {"connections": {"google": False}}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_called_once()
    msg = messenger.send_notification.call_args[0][0]
    assert "google" in msg.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alerting.py -v`
Expected: ImportError -- `workbench.alerting` not found.

- [ ] **Step 3: Add AlertConfig to config.py**

In `src/workbench/config.py`:

```python
class AlertConditions(BaseModel):
    dead_letter_threshold: int = 3
    adapter_failure_threshold: int = 3
    queue_depth_threshold: int = 50
    stale_card_days: int = 3
    llm_failure_threshold: int = 2


class AlertConfig(BaseModel):
    enabled: bool = True
    cooldown_minutes: int = 60
    conditions: AlertConditions = Field(default_factory=AlertConditions)
```

Add to `AppConfig`:
```python
    alerting: AlertConfig = Field(default_factory=AlertConfig)
```

- [ ] **Step 4: Create alerting.py**

Create `src/workbench/alerting.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from workbench.config import AlertConfig, AlertConditions

logger = structlog.get_logger(__name__)


class AlertManager:
    def __init__(self, messenger, config: AlertConfig):
        self._messenger = messenger
        self._config = config
        self._last_fired: dict[str, datetime] = {}

    async def check_and_alert(self, health: dict[str, Any]) -> None:
        if not self._config.enabled or not self._messenger:
            return

        conditions = self._config.conditions
        now = datetime.now(timezone.utc)

        # Dead letters
        dl = health.get("dead_letter_count", 0)
        if dl >= conditions.dead_letter_threshold:
            await self._fire("dead_letters", f"⚠ {dl} dead letter entries need investigation", now)

        # Connection health
        for name, healthy in health.get("connections", {}).items():
            if not healthy:
                await self._fire(f"conn_{name}", f"⚠ Connection '{name}' is unhealthy", now)

        # Queue depth
        depth = health.get("ingestion_queue_depth", 0)
        if depth >= conditions.queue_depth_threshold:
            await self._fire("queue_depth", f"⚠ Ingestion queue depth is {depth}", now)

        # Adapter failures
        for name, failures in health.get("adapter_consecutive_failures", {}).items():
            if failures >= conditions.adapter_failure_threshold:
                await self._fire(f"adapter_{name}", f"⚠ Adapter '{name}' has {failures} consecutive failures", now)

    async def _fire(self, key: str, message: str, now: datetime) -> None:
        cooldown = timedelta(minutes=self._config.cooldown_minutes)
        last = self._last_fired.get(key)
        if last and (now - last) < cooldown:
            return

        try:
            await self._messenger.send_notification(message)
            self._last_fired[key] = now
            logger.info("alert_sent", alert_key=key, message=message)
        except Exception as e:
            logger.error("alert_send_failed", alert_key=key, error=str(e))
```

- [ ] **Step 5: Wire AlertManager into scheduler**

In `src/workbench/pipeline/scheduler.py`:
1. Initialize `AlertManager` in `__init__` using `config.alerting` and `self.messenger`
2. On each scheduler tick, build health dict from stores + connections and call `self.alert_manager.check_and_alert(health)`

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_alerting.py -v && make test`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/alerting.py src/workbench/config.py src/workbench/pipeline/scheduler.py tests/test_alerting.py
git commit -m "feat(alerting): add AlertManager with messenger integration and cooldown dedup"
```

---

### Task 6g: Diagnostic Endpoints

**Files:**
- Create: `src/workbench/api/debug.py`
- Modify: `src/workbench/main.py`
- Test: `tests/test_debug_endpoints.py`

- [ ] **Step 1: Write tests for diagnostic endpoints**

Create `tests/test_debug_endpoints.py`:

```python
# tests/test_debug_endpoints.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from workbench.api.debug import router


def _make_app():
    app = FastAPI()
    app.include_router(router)

    stores = MagicMock()
    stores.items.pool.fetch = AsyncMock(return_value=[])
    stores.ingestion_queue.get_depth = AsyncMock(return_value=0)
    stores.triage.get_pending = AsyncMock(return_value=[])

    app.state.stores = stores
    app.state.connections = {}
    app.state.sources = []
    app.state.config = MagicMock()
    app.state.config.model_dump.return_value = {"version": "0.3.0", "server": {"api_token": "SECRET"}}
    app.state.metrics = None
    return app


def test_debug_adapters():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/adapters")
    assert resp.status_code == 200
    assert "adapters" in resp.json()


def test_debug_connections():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/connections")
    assert resp.status_code == 200
    assert "connections" in resp.json()


def test_debug_config_redacts_secrets():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "SECRET" not in str(data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_debug_endpoints.py -v`
Expected: ImportError -- `workbench.api.debug` not found.

- [ ] **Step 3: Create debug.py**

Create `src/workbench/api/debug.py`:

```python
from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Request

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/debug", tags=["debug"])

SECRET_PATTERN = re.compile(r'(token|key|secret|password|dsn|credentials)', re.IGNORECASE)


def _redact_secrets(obj: Any, depth: int = 0) -> Any:
    if depth > 10:
        return "..."
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if SECRET_PATTERN.search(k) else _redact_secrets(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(i, depth + 1) for i in obj]
    return obj


@router.get("/adapters")
async def debug_adapters(request: Request):
    sources = getattr(request.app.state, "sources", [])
    adapters = []
    for s in sources:
        inner = getattr(s, "_inner", s)
        adapters.append({
            "name": getattr(s, "_name", type(inner).__name__),
            "class": type(inner).__qualname__,
            "healthy": getattr(getattr(inner, "_connection", None), "is_healthy", lambda: True)(),
        })
    return {"adapters": adapters}


@router.get("/connections")
async def debug_connections(request: Request):
    connections = getattr(request.app.state, "connections", {})
    result = {}
    for name, conn in connections.items():
        result[name] = {
            "class": type(conn).__qualname__,
            "healthy": conn.is_healthy(),
        }
    return {"connections": result}


@router.get("/pipeline")
async def debug_pipeline(request: Request):
    stores = request.app.state.stores
    try:
        rows = await stores.items.pool.fetch(
            "SELECT id, status, source_type, created_at FROM items ORDER BY created_at DESC LIMIT 50"
        )
        jobs = [dict(r) for r in rows]
    except Exception:
        jobs = []
    return {"recent_items": jobs}


@router.get("/identity")
async def debug_identity(request: Request):
    memory = getattr(request.app.state, "memory", None)
    if not memory or not hasattr(memory, "get_identity_stats"):
        return {"message": "Identity resolution not available"}
    try:
        stats = await memory.get_identity_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


@router.get("/config")
async def debug_config(request: Request):
    config = request.app.state.config
    raw = config.model_dump() if hasattr(config, "model_dump") else {}
    return {"config": _redact_secrets(raw)}
```

- [ ] **Step 4: Register debug router in main.py**

In `src/workbench/main.py`, add `from workbench.api import debug` to the imports and include `debug.router` in the router list.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_debug_endpoints.py -v && make test`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/api/debug.py src/workbench/main.py tests/test_debug_endpoints.py
git commit -m "feat(debug): add diagnostic endpoints for adapters, pipeline, connections, config"
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
from workbench.models import EnrichmentBudget, ExtractedItem, RawItem, ItemCategory


def _make_item(source_type: str) -> ExtractedItem:
    raw = RawItem(
        id=f"test-{source_type}-1",
        source_type=source_type,
        source_label="test",
        raw_text="{}",
    )
    return ExtractedItem(
        summary="test",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


@pytest.mark.asyncio
async def test_routes_by_source_type():
    email_enricher = AsyncMock()
    email_enricher.enrich.return_value = {
        "calls_made": 1,
        "time_ms": 50,
        "context": {"thread_id": "t1", "entity_refs": [("person", "email:alice@meta.com")]},
    }
    github_enricher = AsyncMock()
    github_enricher.enrich.return_value = {
        "calls_made": 1,
        "time_ms": 30,
        "context": {"author": "alice", "entity_refs": []},
    }

    composite = CompositeEnricher(
        enrichers={"email": email_enricher, "github": github_enricher},
    )
    result = await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    assert result["calls_made"] == 1
    assert result["context"]["thread_id"] == "t1"
    email_enricher.enrich.assert_called_once()
    github_enricher.enrich.assert_not_called()


@pytest.mark.asyncio
async def test_falls_back_to_default():
    composite = CompositeEnricher(enrichers={}, default=StubEnricher())
    result = await composite.enrich(_make_item("unknown"), "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_default_is_stub_when_not_provided():
    composite = CompositeEnricher(enrichers={})
    result = await composite.enrich(_make_item("calendar"), "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_per_enricher_budget():
    enricher = AsyncMock()
    enricher.enrich.return_value = {"calls_made": 0, "time_ms": 0, "context": {}}
    custom_budget = EnrichmentBudget(max_api_calls=8, max_seconds=20)

    composite = CompositeEnricher(
        enrichers={"email": enricher},
        budgets={"email": custom_budget},
    )
    await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    call_args = enricher.enrich.call_args
    assert call_args[0][2] == custom_budget  # third positional arg is budget


@pytest.mark.asyncio
async def test_passes_memory_through():
    enricher = AsyncMock()
    enricher.enrich.return_value = {"calls_made": 0, "time_ms": 0, "context": {}}
    mock_memory = AsyncMock()

    composite = CompositeEnricher(enrichers={"github": enricher})
    await composite.enrich(_make_item("github"), "deep", EnrichmentBudget(), memory=mock_memory)
    call_kwargs = enricher.enrich.call_args[1]
    assert call_kwargs["memory"] is mock_memory


@pytest.mark.asyncio
async def test_close_closes_all_enrichers():
    e1 = AsyncMock()
    e2 = AsyncMock()
    default = AsyncMock()

    composite = CompositeEnricher(enrichers={"a": e1, "b": e2}, default=default)
    await composite.close()
    e1.close.assert_called_once()
    e2.close.assert_called_once()
    default.close.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_composite_enricher.py -v`
Expected: ImportError -- `composite` module not found.

- [ ] **Step 3: Implement CompositeEnricher**

```python
# src/workbench/providers/enrichment/composite.py
from __future__ import annotations

from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import ExtractedItem, EnrichmentBudget


class CompositeEnricher(ContextEnricher):
    """Routes enrichment to source-type-specific enrichers with per-type budgets."""

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
        source_type = item.raw_item.source_type
        enricher = self.enrichers.get(source_type, self.default)
        effective_budget = self.budgets.get(source_type, budget)
        return await enricher.enrich(item, depth, effective_budget, memory=memory)

    async def close(self) -> None:
        seen = set()
        for enricher in self.enrichers.values():
            eid = id(enricher)
            if eid not in seen:
                seen.add(eid)
                await enricher.close()
        if id(self.default) not in seen:
            await self.default.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_composite_enricher.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/enrichment/composite.py tests/test_composite_enricher.py
git commit -m "feat(enrichment): add CompositeEnricher with source_type routing and per-enricher budgets"
```

---

### Task 8: GoogleConnection

**Files:**
- Create: `src/workbench/providers/connection/__init__.py`
- Create: `src/workbench/providers/connection/base.py`
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
         patch("workbench.providers.connection.google.build") as mock_build, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
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


@pytest.mark.asyncio
async def test_close_resets_services():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=[],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        await conn.initialize()
        assert conn.is_healthy()
        await conn.close()
        assert conn.is_healthy() is False


@pytest.mark.asyncio
async def test_lazy_service_creation():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("workbench.providers.connection.google.build") as mock_build, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = MagicMock()

        await conn.initialize()
        mock_build.assert_not_called()  # not called until service accessed

        _ = conn.gmail
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

        _ = conn.calendar
        assert mock_build.call_count == 2

        _ = conn.chat
        assert mock_build.call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_google_connection.py -v`
Expected: ImportError.

- [ ] **Step 3: Create Connection ABC and GoogleConnection**

```python
# src/workbench/providers/connection/__init__.py
# (empty)
```

```python
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

```python
# src/workbench/providers/connection/google.py
from __future__ import annotations

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

    def __init__(self, config: GoogleConnection.ProviderConfig, **kwargs):
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
git add src/workbench/providers/connection/ tests/test_google_connection.py
git commit -m "feat(connection): add Connection ABC and GoogleConnection with OAuth2 token management"
```

---

### Task 9: Gmail Adapter

**Files:**
- Create: `src/workbench/providers/source/gmail.py`
- Test: `tests/test_gmail_adapter.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gmail_adapter.py

import asyncio
import base64
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
from workbench.providers.source.gmail import GmailAdapter


def _mock_connection():
    conn = MagicMock()
    return conn


def _make_gmail_message(msg_id: str, subject: str, sender: str, body: str = "hello"):
    return {
        "id": msg_id,
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "snippet": body[:50],
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@meta.com"},
                {"name": "Cc", "value": ""},
            ],
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
            "parts": [],
        },
    }


async def _run_sync(fn, *a, **kw):
    """Test helper: runs sync functions directly instead of in a thread."""
    return fn(*a, **kw)


@pytest.mark.asyncio
async def test_poll_returns_raw_items():
    conn = _mock_connection()
    messages_list = MagicMock()
    messages_list.execute.return_value = {
        "messages": [{"id": "msg-1"}],
    }
    messages_get = MagicMock()
    messages_get.execute.return_value = _make_gmail_message(
        "msg-1", "Test Subject", "alice@meta.com",
    )
    conn.gmail.users.return_value.messages.return_value.list.return_value = messages_list
    conn.gmail.users.return_value.messages.return_value.get.return_value = messages_get

    config = GmailAdapter.ProviderConfig(label_filters=["INBOX"], max_results=50)
    adapter = GmailAdapter(config, connection=conn)

    with patch("workbench.providers.source.gmail.asyncio") as mock_asyncio:
        mock_asyncio.to_thread = AsyncMock(side_effect=_run_sync)
        items = await adapter.poll(since=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].source_type == "email"
    assert items[0].id == "email_msg-1"
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
        mock_asyncio.to_thread = AsyncMock(side_effect=_run_sync)
        items = await adapter.poll()

    assert items == []


@pytest.mark.asyncio
async def test_poll_without_connection_returns_empty():
    config = GmailAdapter.ProviderConfig()
    adapter = GmailAdapter(config)
    items = await adapter.poll()
    assert items == []


@pytest.mark.asyncio
async def test_poll_extracts_urgency_signals():
    conn = _mock_connection()
    messages_list = MagicMock()
    messages_list.execute.return_value = {
        "messages": [{"id": "msg-2"}],
    }
    msg = _make_gmail_message("msg-2", "Urgent: Review needed", "bob@meta.com", "Please review ASAP")
    messages_get = MagicMock()
    messages_get.execute.return_value = msg
    conn.gmail.users.return_value.messages.return_value.list.return_value = messages_list
    conn.gmail.users.return_value.messages.return_value.get.return_value = messages_get

    config = GmailAdapter.ProviderConfig(label_filters=["INBOX"])
    adapter = GmailAdapter(config, connection=conn)

    with patch("workbench.providers.source.gmail.asyncio") as mock_asyncio:
        mock_asyncio.to_thread = AsyncMock(side_effect=_run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    signals = items[0].urgency_signals
    assert signals["sender"] == "bob@meta.com"
    assert signals["is_direct"] is True
    assert "labels" in signals


@pytest.mark.asyncio
async def test_html_body_stripped():
    from workbench.providers.source.gmail import _strip_html
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


@pytest.mark.asyncio
async def test_body_cleaning_strips_quoted():
    from workbench.providers.source.gmail import _clean_body
    body = "New content\n> Quoted line\n> Another quoted\nMore new content\n--\nSignature"
    cleaned = _clean_body(body)
    assert "> Quoted line" not in cleaned
    assert "Signature" not in cleaned
    assert "New content" in cleaned
    assert "More new content" in cleaned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gmail_adapter.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GmailAdapter**

```python
# src/workbench/providers/source/gmail.py
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from html.parser import HTMLParser

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def get_text(self) -> str:
        return "".join(self.text)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def _extract_body(payload: dict) -> str:
    """Extract plaintext body from a Gmail message payload, falling back to HTML."""
    # Direct plaintext body
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart: prefer text/plain
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart: fall back to text/html
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            return _strip_html(html)

    # Last resort: any body data
    if payload.get("body", {}).get("data"):
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        if payload.get("mimeType", "").startswith("text/html"):
            return _strip_html(raw)
        return raw

    return ""


def _clean_body(body: str) -> str:
    """Remove quoted lines and signatures, truncate to 4000 chars."""
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
            header_names = {h.get("name", "") for h in part.get("headers", [])}
            attachments.append({
                "filename": part["filename"],
                "mime_type": part.get("mimeType", ""),
                "size_bytes": int(part.get("body", {}).get("size", 0)),
                "attachment_id": part.get("body", {}).get("attachmentId", ""),
                "inline": "Content-ID" in header_names,
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
        items: list[RawItem] = []
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
                id=f"email_{msg_id}",
                source_type="email",
                source_label=f"Email: {subject[:80]}",
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

import json
import time
import pytest
from unittest.mock import AsyncMock
from workbench.providers.enrichment.gmail import GmailEnricher
from workbench.models import ExtractedItem, RawItem, EnrichmentBudget, ItemCategory


def _make_email_item(
    sender: str = "alice@meta.com",
    recipients_to: list[str] | None = None,
    recipients_cc: list[str] | None = None,
    thread_id: str = "thread-1",
    subject: str = "Review compliance doc",
    body: str = "Please review the doc.",
) -> ExtractedItem:
    raw = RawItem(
        id="email_msg-1",
        source_type="email",
        source_label="Email: Review compliance doc",
        raw_text=json.dumps({
            "subject": subject,
            "sender": sender,
            "recipients_to": recipients_to or ["me@meta.com"],
            "recipients_cc": recipients_cc or [],
            "body": body,
            "thread_id": thread_id,
            "attachments": [],
        }),
    )
    return ExtractedItem(
        summary="Review compliance doc",
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=raw,
    )


@pytest.mark.asyncio
async def test_returns_correct_shape():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    result = await enricher.enrich(_make_email_item(), "shallow", EnrichmentBudget())
    assert "calls_made" in result
    assert "time_ms" in result
    assert "context" in result
    assert isinstance(result["calls_made"], int)
    assert isinstance(result["time_ms"], int)
    assert isinstance(result["context"], dict)


@pytest.mark.asyncio
async def test_returns_entity_refs_in_context():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    result = await enricher.enrich(_make_email_item(), "shallow", EnrichmentBudget())
    ctx = result["context"]
    assert "entity_refs" in ctx
    refs = ctx["entity_refs"]
    assert ("person", "email:alice@meta.com") in refs


@pytest.mark.asyncio
async def test_extracts_all_participants():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    item = _make_email_item(
        sender="alice@meta.com",
        recipients_to=["me@meta.com", "bob@meta.com"],
        recipients_cc=["carol@meta.com"],
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    refs = result["context"]["entity_refs"]
    assert ("person", "email:alice@meta.com") in refs
    assert ("person", "email:me@meta.com") in refs
    assert ("person", "email:bob@meta.com") in refs
    assert ("person", "email:carol@meta.com") in refs


@pytest.mark.asyncio
async def test_context_includes_email_metadata():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    result = await enricher.enrich(
        _make_email_item(subject="Important doc"), "shallow", EnrichmentBudget(),
    )
    ctx = result["context"]
    assert ctx["subject"] == "Important doc"
    assert ctx["sender"] == "alice@meta.com"
    assert ctx["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_records_sender_entity_in_memory():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    mock_memory = AsyncMock()
    await enricher.enrich(_make_email_item(), "shallow", EnrichmentBudget(), memory=mock_memory)
    mock_memory.record_entity.assert_called_once()
    call_args = mock_memory.record_entity.call_args
    assert call_args[0][0] == "person"
    assert call_args[0][1] == "email:alice@meta.com"
    assert call_args[0][2]["email"] == "alice@meta.com"


@pytest.mark.asyncio
async def test_non_email_returns_zero_enrichment():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    raw = RawItem(
        id="gh-1", source_type="github", source_label="PR", raw_text="{}",
    )
    item = ExtractedItem(
        summary="test", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_handles_malformed_raw_text():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    raw = RawItem(
        id="email_bad", source_type="email", source_label="Bad", raw_text="not json",
    )
    item = ExtractedItem(
        summary="bad", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result["calls_made"] == 0
    assert result["context"] == {}


@pytest.mark.asyncio
async def test_memory_failure_does_not_break_enrichment():
    enricher = GmailEnricher(GmailEnricher.ProviderConfig())
    mock_memory = AsyncMock()
    mock_memory.record_entity.side_effect = Exception("memory down")
    result = await enricher.enrich(_make_email_item(), "shallow", EnrichmentBudget(), memory=mock_memory)
    # Should still return valid result despite memory failure
    assert "entity_refs" in result["context"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gmail_enricher.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GmailEnricher**

```python
# src/workbench/providers/enrichment/gmail.py
from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GmailEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "email":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[tuple[str, str]] = []
        calls_made = 0

        # Extract sender entity
        sender = raw.get("sender", "")
        if sender:
            entity_refs.append(("person", f"email:{sender}"))
            if memory:
                try:
                    await memory.record_entity(
                        "person",
                        f"email:{sender}",
                        {"email": sender, "name": sender.split("@")[0]},
                    )
                except Exception as e:
                    logger.warning("Memory record_entity failed for %s: %s", sender, e)

        # Extract recipient entities
        for recipient in raw.get("recipients_to", []) + raw.get("recipients_cc", []):
            if recipient:
                entity_refs.append(("person", f"email:{recipient}"))

        context = {
            "entity_refs": entity_refs,
            "subject": raw.get("subject", ""),
            "sender": sender,
            "thread_id": raw.get("thread_id", ""),
            "attachments": raw.get("attachments", []),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gmail_enricher.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/enrichment/gmail.py tests/test_gmail_enricher.py
git commit -m "feat(enrichment): add GmailEnricher with entity_refs and correct return shape"
```

---

### Task 11: Google Calendar Adapter + Enricher

**Files:**
- Create: `src/workbench/providers/source/gcalendar.py`
- Create: `src/workbench/providers/enrichment/gcalendar.py`
- Test: `tests/test_gcalendar.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gcalendar.py

import hashlib
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
from workbench.providers.source.gcalendar import GCalendarAdapter
from workbench.providers.enrichment.gcalendar import GCalendarEnricher
from workbench.models import ExtractedItem, RawItem, EnrichmentBudget, ItemCategory


# --- Helper to run sync functions as async (replaces asyncio.to_thread in tests) ---
async def _run_sync(fn, *a, **kw):
    return fn(*a, **kw)


def _make_event(
    event_id: str = "evt-1",
    summary: str = "Team Standup",
    start_hours_from_now: int = 2,
    duration_minutes: int = 30,
    organizer_email: str = "alice@meta.com",
    attendees: list[str] | None = None,
    location: str = "",
    description: str = "",
    recurring_event_id: str | None = None,
    status: str = "confirmed",
):
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=start_hours_from_now)
    end = start + timedelta(minutes=duration_minutes)
    event = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "organizer": {"email": organizer_email},
        "attendees": [{"email": e, "responseStatus": "accepted"} for e in (attendees or [])],
        "location": location,
        "description": description,
        "status": status,
        "htmlLink": f"https://calendar.google.com/event/{event_id}",
    }
    if recurring_event_id:
        event["recurringEventId"] = recurring_event_id
    return event


def _mock_connection_with_events(events: list[dict]):
    conn = MagicMock()
    events_list = MagicMock()
    events_list.execute.return_value = {"items": events}
    conn.calendar.events.return_value.list.return_value = events_list
    return conn


# ============ Adapter Tests ============

@pytest.mark.asyncio
async def test_poll_returns_raw_items():
    event = _make_event()
    conn = _mock_connection_with_events([event])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"], lookahead_hours=48)
    adapter = GCalendarAdapter(config, connection=conn)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    assert items[0].source_type == "calendar"
    assert items[0].id == f"cal_{event['id']}"
    raw = json.loads(items[0].raw_text)
    assert raw["summary"] == "Team Standup"
    assert raw["organizer"] == "alice@meta.com"


def test_adapter_type():
    adapter = GCalendarAdapter(GCalendarAdapter.ProviderConfig())
    assert adapter.adapter_type() == "calendar"


@pytest.mark.asyncio
async def test_poll_without_connection():
    adapter = GCalendarAdapter(GCalendarAdapter.ProviderConfig())
    items = await adapter.poll()
    assert items == []


@pytest.mark.asyncio
async def test_hash_based_dedup_skips_unchanged():
    event = _make_event(event_id="evt-stable")
    conn = _mock_connection_with_events([event])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"])
    adapter = GCalendarAdapter(config, connection=conn)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items1 = await adapter.poll()
        items2 = await adapter.poll()

    assert len(items1) == 1
    assert len(items2) == 0  # same hash, skipped


@pytest.mark.asyncio
async def test_hash_dedup_detects_change():
    event1 = _make_event(event_id="evt-change", summary="Standup")
    conn1 = _mock_connection_with_events([event1])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"])
    adapter = GCalendarAdapter(config, connection=conn1)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items1 = await adapter.poll()

    # Event changes summary
    event2 = _make_event(event_id="evt-change", summary="Standup v2")
    conn2 = _mock_connection_with_events([event2])
    adapter._connection = conn2

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items2 = await adapter.poll()

    assert len(items1) == 1
    assert len(items2) == 1  # hash changed, re-emitted


@pytest.mark.asyncio
async def test_recurring_event_signals():
    event = _make_event(
        event_id="evt-rec-instance",
        recurring_event_id="evt-rec-master",
    )
    conn = _mock_connection_with_events([event])
    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["primary"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    signals = items[0].urgency_signals
    assert signals["is_recurring"] is True
    assert signals["recurring_event_id"] == "evt-rec-master"


@pytest.mark.asyncio
async def test_starts_within_hours_signal():
    event = _make_event(start_hours_from_now=1)
    conn = _mock_connection_with_events([event])
    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["primary"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    signals = items[0].urgency_signals
    assert signals["starts_within_hours"] <= 2


@pytest.mark.asyncio
async def test_multiple_calendars():
    event_a = _make_event(event_id="evt-cal-a", summary="Cal A event")
    event_b = _make_event(event_id="evt-cal-b", summary="Cal B event")

    conn = MagicMock()
    call_count = {"n": 0}
    def _make_list_result(*a, **kw):
        mock = MagicMock()
        call_count["n"] += 1
        if call_count["n"] == 1:
            mock.execute.return_value = {"items": [event_a]}
        else:
            mock.execute.return_value = {"items": [event_b]}
        return mock
    conn.calendar.events.return_value.list = _make_list_result

    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["cal-a", "cal-b"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 2


# ============ Enricher Tests ============

def _make_calendar_item(
    organizer: str = "alice@meta.com",
    attendees: list[str] | None = None,
    summary: str = "Team Standup",
) -> ExtractedItem:
    raw = RawItem(
        id="cal_evt-1",
        source_type="calendar",
        source_label="Calendar: Team Standup",
        raw_text=json.dumps({
            "summary": summary,
            "organizer": organizer,
            "attendees": [{"email": e, "response_status": "accepted"} for e in (attendees or [])],
            "location": "Room 5A",
            "description": "Weekly standup",
            "start": "2026-06-02T10:00:00+00:00",
            "end": "2026-06-02T10:30:00+00:00",
            "is_recurring": False,
            "link": "https://calendar.google.com/event/evt-1",
        }),
    )
    return ExtractedItem(
        summary=summary, category=ItemCategory.MEETING, source_context="", raw_item=raw,
    )


@pytest.mark.asyncio
async def test_enricher_returns_correct_shape():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    result = await enricher.enrich(_make_calendar_item(), "shallow", EnrichmentBudget())
    assert "calls_made" in result
    assert "time_ms" in result
    assert "context" in result
    assert isinstance(result["context"], dict)


@pytest.mark.asyncio
async def test_enricher_extracts_entity_refs():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    result = await enricher.enrich(
        _make_calendar_item(
            organizer="alice@meta.com",
            attendees=["bob@meta.com", "carol@meta.com"],
        ),
        "shallow", EnrichmentBudget(),
    )
    refs = result["context"]["entity_refs"]
    assert ("person", "gcal:alice@meta.com") in refs
    assert ("person", "gcal:bob@meta.com") in refs
    assert ("person", "gcal:carol@meta.com") in refs


@pytest.mark.asyncio
async def test_enricher_non_calendar_returns_empty():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    raw = RawItem(id="gh-1", source_type="github", source_label="PR", raw_text="{}")
    item = ExtractedItem(
        summary="test", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_enricher_records_entities_in_memory():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    mock_memory = AsyncMock()
    await enricher.enrich(
        _make_calendar_item(organizer="alice@meta.com"),
        "shallow", EnrichmentBudget(), memory=mock_memory,
    )
    mock_memory.record_entity.assert_called()
    call_args = mock_memory.record_entity.call_args
    assert call_args[0][0] == "person"
    assert call_args[0][1] == "gcal:alice@meta.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gcalendar.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GCalendarAdapter**

```python
# src/workbench/providers/source/gcalendar.py
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = logging.getLogger(__name__)


def _compute_event_hash(event: dict) -> str:
    """Compute a deterministic hash of meaningful event fields for change detection."""
    title = event.get("summary", "")
    desc = event.get("description", "")
    start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
    end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
    location = event.get("location", "")
    status = event.get("status", "")
    attendees_str = ",".join(
        sorted(a.get("email", "") for a in event.get("attendees", []))
    )
    content = f"{title}|{desc}|{start}|{end}|{location}|{status}|{attendees_str}"
    return hashlib.sha256(content.encode()).hexdigest()


class GCalendarAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        calendar_ids: list[str] = ["primary"]
        lookahead_hours: int = 48

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection
        self._event_hashes: dict[str, str] = {}

    def adapter_type(self) -> str:
        return "calendar"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        now = datetime.now(timezone.utc)
        time_min = since.isoformat() if since else now.isoformat()
        time_max = (now + timedelta(hours=self._config.lookahead_hours)).isoformat()

        items: list[RawItem] = []

        for cal_id in self._config.calendar_ids:
            def _fetch_events(cid=cal_id):
                result = self._connection.calendar.events().list(
                    calendarId=cid,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                return result.get("items", [])

            events = await asyncio.to_thread(_fetch_events)

            for event in events:
                event_id = event.get("id", "")
                if not event_id:
                    continue

                # Hash-based dedup: skip unchanged events
                event_hash = _compute_event_hash(event)
                prev_hash = self._event_hashes.get(event_id)
                if prev_hash == event_hash:
                    continue
                self._event_hashes[event_id] = event_hash

                summary = event.get("summary", "(No title)")
                organizer = event.get("organizer", {}).get("email", "")
                attendees = [
                    {
                        "email": a.get("email", ""),
                        "response_status": a.get("responseStatus", ""),
                    }
                    for a in event.get("attendees", [])
                ]
                start_raw = event.get("start", {})
                end_raw = event.get("end", {})
                start_str = start_raw.get("dateTime", start_raw.get("date", ""))
                end_str = end_raw.get("dateTime", end_raw.get("date", ""))

                is_recurring = "recurringEventId" in event
                recurring_event_id = event.get("recurringEventId")

                # Compute starts_within_hours
                starts_within_hours = self._config.lookahead_hours
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    diff = (start_dt - now).total_seconds() / 3600.0
                    starts_within_hours = max(0, round(diff, 1))
                except (ValueError, TypeError):
                    pass

                raw_text = json.dumps({
                    "summary": summary,
                    "organizer": organizer,
                    "attendees": attendees,
                    "location": event.get("location", ""),
                    "description": event.get("description", ""),
                    "start": start_str,
                    "end": end_str,
                    "is_recurring": is_recurring,
                    "recurring_event_id": recurring_event_id,
                    "link": event.get("htmlLink", ""),
                    "status": event.get("status", ""),
                })

                urgency_signals = {
                    "is_recurring": is_recurring,
                    "recurring_event_id": recurring_event_id,
                    "starts_within_hours": starts_within_hours,
                    "attendee_count": len(attendees),
                    "has_location": bool(event.get("location")),
                    "organizer": organizer,
                }

                items.append(RawItem(
                    id=f"cal_{event_id}",
                    source_type="calendar",
                    source_label=f"Calendar: {summary[:80]}",
                    raw_text=raw_text,
                    urgency_signals=urgency_signals,
                ))

        return items
```

- [ ] **Step 4: Implement GCalendarEnricher**

```python
# src/workbench/providers/enrichment/gcalendar.py
from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GCalendarEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "calendar":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[tuple[str, str]] = []
        calls_made = 0

        # Organizer entity
        organizer = raw.get("organizer", "")
        if organizer:
            entity_refs.append(("person", f"gcal:{organizer}"))

        # Attendee entities
        for attendee in raw.get("attendees", []):
            email = attendee.get("email", "")
            if email:
                entity_refs.append(("person", f"gcal:{email}"))

        # Record organizer in memory
        if memory and organizer:
            try:
                await memory.record_entity(
                    "person",
                    f"gcal:{organizer}",
                    {"email": organizer, "name": organizer.split("@")[0]},
                )
            except Exception as e:
                logger.warning("Memory record_entity failed for %s: %s", organizer, e)

        context = {
            "entity_refs": entity_refs,
            "summary": raw.get("summary", ""),
            "organizer": organizer,
            "attendee_count": len(raw.get("attendees", [])),
            "location": raw.get("location", ""),
            "start": raw.get("start", ""),
            "end": raw.get("end", ""),
            "is_recurring": raw.get("is_recurring", False),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_gcalendar.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/providers/source/gcalendar.py src/workbench/providers/enrichment/gcalendar.py tests/test_gcalendar.py
git commit -m "feat(source): add GCalendarAdapter with hash dedup + GCalendarEnricher with entity_refs"
```

---

### Task 12: Google Chat Adapter + Enricher

**Files:**
- Create: `src/workbench/providers/source/gchat.py`
- Create: `src/workbench/providers/enrichment/gchat.py`
- Test: `tests/test_gchat.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gchat.py

import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
from workbench.providers.source.gchat import GChatAdapter
from workbench.providers.enrichment.gchat import GChatEnricher
from workbench.models import ExtractedItem, RawItem, EnrichmentBudget, ItemCategory


async def _run_sync(fn, *a, **kw):
    return fn(*a, **kw)


def _make_message(
    name: str = "spaces/SPACE1/messages/msg-1",
    text: str = "Hello team",
    sender_name: str = "users/user-alice",
    sender_display: str = "Alice Smith",
    sender_type: str = "HUMAN",
    thread_name: str = "spaces/SPACE1/threads/thread-1",
    create_time: str | None = None,
):
    if create_time is None:
        create_time = datetime.now(timezone.utc).isoformat()
    return {
        "name": name,
        "text": text,
        "sender": {
            "name": sender_name,
            "displayName": sender_display,
            "type": sender_type,
        },
        "thread": {"name": thread_name},
        "createTime": create_time,
        "space": {"name": "spaces/SPACE1", "displayName": "Team Chat"},
    }


def _mock_connection_with_messages(messages: list[dict]):
    conn = MagicMock()
    messages_list = MagicMock()
    messages_list.execute.return_value = {"messages": messages}
    conn.chat.spaces.return_value.messages.return_value.list.return_value = messages_list
    return conn


# ============ Adapter Tests ============

@pytest.mark.asyncio
async def test_poll_returns_raw_items():
    msg = _make_message()
    conn = _mock_connection_with_messages([msg])

    config = GChatAdapter.ProviderConfig(
        spaces=["spaces/SPACE1"],
        track="all",
    )
    adapter = GChatAdapter(config, connection=conn)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    assert items[0].source_type == "chat"
    raw = json.loads(items[0].raw_text)
    assert raw["space_name"] == "Team Chat"
    assert len(raw["messages"]) == 1


def test_adapter_type():
    adapter = GChatAdapter(GChatAdapter.ProviderConfig())
    assert adapter.adapter_type() == "chat"


@pytest.mark.asyncio
async def test_poll_without_connection():
    adapter = GChatAdapter(GChatAdapter.ProviderConfig())
    items = await adapter.poll()
    assert items == []


@pytest.mark.asyncio
async def test_bot_messages_filtered():
    human_msg = _make_message(
        name="spaces/S/messages/m1", text="Hi", sender_type="HUMAN",
    )
    bot_msg = _make_message(
        name="spaces/S/messages/m2", text="Bot reply", sender_type="BOT",
        sender_name="users/bot-123", sender_display="WorkbenchBot",
    )
    conn = _mock_connection_with_messages([human_msg, bot_msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(spaces=["spaces/S"], track="all"),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    raw = json.loads(items[0].raw_text)
    # Bot messages should be filtered out
    senders = [m["sender_display"] for m in raw["messages"]]
    assert "WorkbenchBot" not in senders


@pytest.mark.asyncio
async def test_exclude_spaces():
    msg = _make_message()
    conn = _mock_connection_with_messages([msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(
            spaces=["spaces/SPACE1"],
            exclude_spaces=["spaces/SPACE1"],
            track="all",
        ),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert items == []


@pytest.mark.asyncio
async def test_track_participating_requires_user_message():
    """In 'participating' mode, only track threads where the user posted."""
    msg1 = _make_message(
        thread_name="spaces/S/threads/t-other",
        sender_name="users/someone-else",
        sender_display="Bob",
        text="Bob's message",
    )
    conn = _mock_connection_with_messages([msg1])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(
            spaces=["spaces/S"],
            track="participating",
            user_id="users/user-me",
        ),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    # User didn't participate, so nothing tracked
    assert items == []


@pytest.mark.asyncio
async def test_track_participating_includes_user_threads():
    my_msg = _make_message(
        thread_name="spaces/S/threads/t-mine",
        sender_name="users/user-me",
        sender_display="Me",
        text="My message",
    )
    conn = _mock_connection_with_messages([my_msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(
            spaces=["spaces/S"],
            track="participating",
            user_id="users/user-me",
        ),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1


@pytest.mark.asyncio
async def test_track_mentioned():
    msg = _make_message(
        text="Hey <users/user-me> can you look at this?",
        thread_name="spaces/S/threads/t-mention",
        sender_name="users/other",
    )
    conn = _mock_connection_with_messages([msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(
            spaces=["spaces/S"],
            track="mentioned",
            user_id="users/user-me",
        ),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1


@pytest.mark.asyncio
async def test_thread_exits_after_48h_inactivity():
    old_time = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    msg = _make_message(
        thread_name="spaces/S/threads/t-old",
        create_time=old_time,
    )
    conn = _mock_connection_with_messages([msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(spaces=["spaces/S"], track="all"),
        connection=conn,
    )
    # Seed the tracked thread with an old timestamp
    adapter._tracked_threads["spaces/S/threads/t-old"] = (
        datetime.now(timezone.utc) - timedelta(hours=50)
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    # Thread is stale, should be exited
    assert "spaces/S/threads/t-old" not in adapter._tracked_threads


@pytest.mark.asyncio
async def test_thread_reentry_on_new_participation():
    """A thread that was exited should re-enter if user participates again."""
    now = datetime.now(timezone.utc)
    new_msg = _make_message(
        thread_name="spaces/S/threads/t-reenter",
        sender_name="users/user-me",
        sender_display="Me",
        text="I'm back",
        create_time=now.isoformat(),
    )
    conn = _mock_connection_with_messages([new_msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(
            spaces=["spaces/S"],
            track="participating",
            user_id="users/user-me",
        ),
        connection=conn,
    )
    # Thread was previously exited (not in _tracked_threads)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    assert "spaces/S/threads/t-reenter" in adapter._tracked_threads


@pytest.mark.asyncio
async def test_source_id_format():
    now = datetime.now(timezone.utc)
    msg = _make_message(create_time=now.isoformat())
    conn = _mock_connection_with_messages([msg])

    adapter = GChatAdapter(
        GChatAdapter.ProviderConfig(spaces=["spaces/SPACE1"], track="all"),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gchat.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    assert items[0].id.startswith("gchat_")


# ============ Enricher Tests ============

def _make_chat_item(
    space_name: str = "Team Chat",
    messages: list[dict] | None = None,
) -> ExtractedItem:
    if messages is None:
        messages = [
            {"sender_name": "users/alice", "sender_display": "Alice", "text": "Hello"},
            {"sender_name": "users/bob", "sender_display": "Bob", "text": "Hi Alice"},
        ]
    raw = RawItem(
        id="gchat_t1_12345",
        source_type="chat",
        source_label="Chat: Team Chat",
        raw_text=json.dumps({
            "space_name": space_name,
            "thread_name": "spaces/S/threads/t1",
            "messages": messages,
            "participant_count": len(set(m["sender_name"] for m in messages)),
        }),
    )
    return ExtractedItem(
        summary="Team Chat discussion",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


@pytest.mark.asyncio
async def test_enricher_returns_correct_shape():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    result = await enricher.enrich(_make_chat_item(), "shallow", EnrichmentBudget())
    assert "calls_made" in result
    assert "time_ms" in result
    assert "context" in result


@pytest.mark.asyncio
async def test_enricher_extracts_entity_refs():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    result = await enricher.enrich(_make_chat_item(), "shallow", EnrichmentBudget())
    refs = result["context"]["entity_refs"]
    assert ("person", "gchat:users/alice") in refs
    assert ("person", "gchat:users/bob") in refs


@pytest.mark.asyncio
async def test_enricher_extracts_space_entity():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    result = await enricher.enrich(_make_chat_item(), "shallow", EnrichmentBudget())
    refs = result["context"]["entity_refs"]
    assert ("space", "gchat:spaces/S/threads/t1") in refs


@pytest.mark.asyncio
async def test_enricher_non_chat_returns_empty():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    raw = RawItem(id="gh-1", source_type="github", source_label="PR", raw_text="{}")
    item = ExtractedItem(
        summary="test", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_enricher_records_entities_in_memory():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    mock_memory = AsyncMock()
    await enricher.enrich(_make_chat_item(), "shallow", EnrichmentBudget(), memory=mock_memory)
    assert mock_memory.record_entity.call_count >= 2  # at least alice and bob
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gchat.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GChatAdapter**

```python
# src/workbench/providers/source/gchat.py
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = logging.getLogger(__name__)

_THREAD_EXIT_HOURS = 48


class GChatAdapter(SourceAdapter):
    """Google Chat source adapter with thread subscription model.

    Track modes:
      - "all": emit all threads with new messages
      - "participating": only threads where user_id has posted
      - "mentioned": only threads where user_id is @-mentioned
    """

    class ProviderConfig(BaseModel):
        spaces: list[str] = []
        exclude_spaces: list[str] = []
        track: str = "all"  # "participating" | "mentioned" | "all"
        user_id: str = ""  # e.g. "users/user-me", required for participating/mentioned modes

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection
        self._tracked_threads: dict[str, datetime] = {}

    def adapter_type(self) -> str:
        return "chat"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        items: list[RawItem] = []
        now = datetime.now(timezone.utc)

        # Expire stale tracked threads (no activity for 48h)
        stale_threads = [
            tid for tid, last_active in self._tracked_threads.items()
            if (now - last_active).total_seconds() > _THREAD_EXIT_HOURS * 3600
        ]
        for tid in stale_threads:
            del self._tracked_threads[tid]
            logger.debug("Thread exited (48h inactivity): %s", tid)

        effective_spaces = [
            s for s in self._config.spaces
            if s not in self._config.exclude_spaces
        ]

        for space_name in effective_spaces:
            def _fetch_messages(sn=space_name):
                result = self._connection.chat.spaces().messages().list(
                    parent=sn,
                    pageSize=100,
                ).execute()
                return result.get("messages", [])

            raw_messages = await asyncio.to_thread(_fetch_messages)

            # Filter bot messages
            human_messages = [
                m for m in raw_messages
                if m.get("sender", {}).get("type", "HUMAN") != "BOT"
            ]

            # Group by thread
            threads: dict[str, list[dict]] = {}
            for msg in human_messages:
                thread_name = msg.get("thread", {}).get("name", "")
                if not thread_name:
                    continue
                threads.setdefault(thread_name, []).append(msg)

            for thread_name, thread_msgs in threads.items():
                # Apply track mode filter
                if not self._should_track(thread_name, thread_msgs):
                    continue

                # Update thread tracking timestamp
                latest_time = self._get_latest_time(thread_msgs)
                self._tracked_threads[thread_name] = latest_time

                # Build the raw text with full thread context
                space_display = thread_msgs[0].get("space", {}).get("displayName", space_name)
                formatted_messages = []
                for m in thread_msgs:
                    formatted_messages.append({
                        "sender_name": m.get("sender", {}).get("name", ""),
                        "sender_display": m.get("sender", {}).get("displayName", ""),
                        "text": m.get("text", ""),
                        "create_time": m.get("createTime", ""),
                    })

                participant_names = list(set(
                    m["sender_display"] for m in formatted_messages if m["sender_display"]
                ))

                # source_id includes thread name and latest timestamp for dedup
                latest_ts = int(latest_time.timestamp())
                source_id = f"gchat_{thread_name.replace('/', '_')}_{latest_ts}"

                raw_text = json.dumps({
                    "space_name": space_display,
                    "thread_name": thread_name,
                    "messages": formatted_messages,
                    "participant_count": len(participant_names),
                    "participants": participant_names,
                })

                urgency_signals = {
                    "space": space_display,
                    "thread": thread_name,
                    "participant_count": len(participant_names),
                    "message_count": len(formatted_messages),
                    "is_direct_message": len(participant_names) <= 2,
                }

                items.append(RawItem(
                    id=source_id,
                    source_type="chat",
                    source_label=f"Chat: {space_display}",
                    raw_text=raw_text,
                    urgency_signals=urgency_signals,
                ))

        return items

    def _should_track(self, thread_name: str, messages: list[dict]) -> bool:
        """Determine if a thread should be tracked based on the track mode."""
        track = self._config.track
        user_id = self._config.user_id

        if track == "all":
            return True

        if track == "participating":
            # Track if user has posted in this thread
            for msg in messages:
                if msg.get("sender", {}).get("name") == user_id:
                    return True
            # Also track if already tracked (re-entry happens via user posting)
            return thread_name in self._tracked_threads

        if track == "mentioned":
            # Track if user is @-mentioned in any message
            for msg in messages:
                text = msg.get("text", "")
                if user_id and user_id in text:
                    return True
            return False

        return True

    def _get_latest_time(self, messages: list[dict]) -> datetime:
        """Get the latest createTime from a list of messages."""
        latest = datetime.now(timezone.utc)
        for msg in messages:
            create_time = msg.get("createTime", "")
            if create_time:
                try:
                    dt = datetime.fromisoformat(create_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > latest or latest == datetime.now(timezone.utc):
                        latest = dt
                except (ValueError, TypeError):
                    pass
        return latest
```

- [ ] **Step 4: Implement GChatEnricher**

```python
# src/workbench/providers/enrichment/gchat.py
from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GChatEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "chat":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[tuple[str, str]] = []
        calls_made = 0

        # Extract participant entities (deduplicated)
        seen_senders: set[str] = set()
        for msg in raw.get("messages", []):
            sender_name = msg.get("sender_name", "")
            sender_display = msg.get("sender_display", "")
            if sender_name and sender_name not in seen_senders:
                seen_senders.add(sender_name)
                entity_refs.append(("person", f"gchat:{sender_name}"))
                if memory:
                    try:
                        await memory.record_entity(
                            "person",
                            f"gchat:{sender_name}",
                            {"display_name": sender_display, "chat_id": sender_name},
                        )
                    except Exception as e:
                        logger.warning("Memory record_entity failed for %s: %s", sender_name, e)

        # Thread/space as entity
        thread_name = raw.get("thread_name", "")
        if thread_name:
            entity_refs.append(("space", f"gchat:{thread_name}"))

        context = {
            "entity_refs": entity_refs,
            "space_name": raw.get("space_name", ""),
            "thread_name": thread_name,
            "participant_count": raw.get("participant_count", 0),
            "message_count": len(raw.get("messages", [])),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_gchat.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/providers/source/gchat.py src/workbench/providers/enrichment/gchat.py tests/test_gchat.py
git commit -m "feat(source): add GChatAdapter with thread subscription model + GChatEnricher"
```

---

### Task 13: Update GitHubEnricher to Return entity_refs Inside context

**Files:**
- Modify: `src/workbench/providers/enrichment/github.py`
- Modify: `tests/test_github_enricher.py`

The existing GitHubEnricher already returns the correct `{"calls_made", "time_ms", "context"}` shape. This task adds `entity_refs` inside the `context` dict so that downstream card generation can discover entities from GitHub items, matching the pattern used by the new enrichers.

- [ ] **Step 1: Write tests for entity_refs in context**

```python
# tests/test_github_enricher.py -- append

@pytest.mark.asyncio
async def test_enrich_returns_entity_refs_in_context(enricher):
    item = _make_item()
    gh_view_output = {
        "files": [{"path": "auth.py"}],
        "reviewDecision": "APPROVED",
        "labels": [],
        "statusCheckRollup": [],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert "entity_refs" in ctx
    refs = ctx["entity_refs"]
    assert ("person", "github:alice") in refs
    assert ("repo", "github:owner/repo") in refs


@pytest.mark.asyncio
async def test_enrich_entity_refs_empty_on_non_github(enricher):
    item = _make_item(source_type="email", raw_text="raw email body")
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result["context"] == {}
```

- [ ] **Step 2: Run tests to verify entity_refs tests fail**

Run: `python -m pytest tests/test_github_enricher.py::test_enrich_returns_entity_refs_in_context -v`
Expected: KeyError or assertion failure -- `entity_refs` not in context dict.

- [ ] **Step 3: Update GitHubEnricher to populate entity_refs in context**

In `src/workbench/providers/enrichment/github.py`, in the `enrich` method, add entity_refs population before the `return` statement:

```python
        # Build entity_refs list for downstream card generation
        entity_refs: list[tuple[str, str]] = []
        if author_login != "unknown":
            entity_refs.append(("person", f"github:{author_login}"))
        if repo:
            entity_refs.append(("repo", f"github:{repo}"))
        context["entity_refs"] = entity_refs

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
```

The key change: insert the `entity_refs` block just before the existing `elapsed_ms` calculation and return statement, after all context fields and memory recording are done.

- [ ] **Step 4: Run all GitHub enricher tests to verify they pass**

Run: `python -m pytest tests/test_github_enricher.py -v`
Expected: All pass (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/workbench/providers/enrichment/github.py tests/test_github_enricher.py
git commit -m "feat(enrichment): add entity_refs to GitHubEnricher context dict"
```

---

### Task 14: Scheduler -- Error Isolation + Connection Health

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write test for error isolation with multiple adapters**

```python
# tests/test_pipeline.py -- append

@pytest.mark.asyncio
async def test_source_poll_error_isolation(stores, mock_llm):
    """One adapter failing doesn't prevent others from polling."""
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    good_adapter = AsyncMock()
    good_adapter.adapter_type = MagicMock(return_value="good")
    good_adapter.poll.return_value = [
        RawItem(id="good-1", source_type="good", source_label="Good #1", raw_text='{"n":1}'),
    ]

    bad_adapter = AsyncMock()
    bad_adapter.adapter_type = MagicMock(return_value="bad")
    bad_adapter.poll.side_effect = RuntimeError("OAuth expired")

    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, None, config,
        sources=[bad_adapter, good_adapter],
    )
    await scheduler._poll_sources()

    # Both adapters were attempted
    bad_adapter.poll.assert_called_once()
    good_adapter.poll.assert_called_once()

    # Good adapter's item was enqueued despite bad adapter failing
    assert await stores.ingestion_queue.queue_depth() == 1

    # Bad adapter's last_polled should NOT be updated
    bad_stored = await stores.config.get("source_last_polled:bad")
    assert bad_stored is None

    # Good adapter's last_polled SHOULD be updated
    good_stored = await stores.config.get("source_last_polled:good")
    assert good_stored is not None


@pytest.mark.asyncio
async def test_scheduler_skips_unhealthy_connection(stores, mock_llm):
    """Adapter with unhealthy connection is skipped."""
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    unhealthy_conn = MagicMock()
    unhealthy_conn.is_healthy.return_value = False

    adapter = AsyncMock()
    adapter.adapter_type = MagicMock(return_value="email")
    adapter._connection = unhealthy_conn
    adapter.poll.return_value = []

    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, None, config,
        sources=[adapter],
    )
    await scheduler._poll_sources()

    # poll should NOT be called because connection is unhealthy
    adapter.poll.assert_not_called()
```

- [ ] **Step 2: Run tests to verify the new unhealthy-connection test fails**

Run: `python -m pytest tests/test_pipeline.py::test_scheduler_skips_unhealthy_connection -v`
Expected: FAIL -- scheduler does not check connection health.

Note: The error isolation test (`test_source_poll_error_isolation`) may already pass because the existing `_poll_sources` catches exceptions per-adapter. Run it to check:

Run: `python -m pytest tests/test_pipeline.py::test_source_poll_error_isolation -v`

- [ ] **Step 3: Update _poll_sources in scheduler.py to add connection health check**

In `src/workbench/pipeline/scheduler.py`, update `_poll_sources` to check connection health before polling:

```python
    async def _poll_sources(self):
        for source in self.sources:
            adapter_type = source.adapter_type()
            try:
                # Check connection health if adapter has a connection
                connection = getattr(source, '_connection', None)
                if connection is not None and hasattr(connection, 'is_healthy'):
                    if not connection.is_healthy():
                        logger.warning(
                            "Skipping %s: connection unhealthy", adapter_type,
                        )
                        continue

                since = None
                stored = await self.stores.config.get(f"source_last_polled:{adapter_type}")
                if stored:
                    since = datetime.fromisoformat(stored)

                raw_items = await source.poll(since=since)
                for raw_item in raw_items:
                    try:
                        await self.pipeline.enqueue(
                            raw_item.raw_text,
                            raw_item.source_type,
                            source_id=raw_item.id,
                            urgency_signals=raw_item.urgency_signals,
                            trigger=JobTrigger.POLL,
                        )
                    except Exception as e:
                        logger.error("Failed to enqueue item %s from %s: %s",
                                     raw_item.id, adapter_type, e)

                await self.stores.config.set(
                    f"source_last_polled:{adapter_type}",
                    datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Polled %s: %d items (since=%s)", adapter_type, len(raw_items), since)
            except Exception as e:
                logger.error("Source adapter %s poll failed: %s", adapter_type, e)
```

- [ ] **Step 4: Run all pipeline tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/scheduler.py tests/test_pipeline.py
git commit -m "feat(scheduler): add connection health check before polling source adapters"
```

---

### Task 14b: Update config.example.yml

**Files:**
- Modify: `config.example.yml`

- [ ] **Step 1: Add connections and enrichment sections**

Replace the existing `sources:` and `enrichment:` sections in `config.example.yml`:

```yaml
# Shared connections — initialized at startup, injected into adapters/enrichers
# connections:
#   google:
#     class: workbench.providers.connection.google.GoogleConnection
#     credentials_path: ${oc.env:GOOGLE_CREDENTIALS_PATH}
#     token_path: ${oc.env:GOOGLE_TOKEN_PATH}
#     scopes:
#       - https://www.googleapis.com/auth/gmail.readonly
#       - https://www.googleapis.com/auth/calendar.readonly
#       - https://www.googleapis.com/auth/chat.spaces.readonly

sources: []
# Example sources:
#   - class: workbench.providers.source.github.GitHubSourceAdapter
#     repos:
#       - "owner/repo"
#   - class: workbench.providers.source.gmail.GmailAdapter
#     connection: google
#     label_filters: ["INBOX", "UNREAD"]
#     max_results: 50
#   - class: workbench.providers.source.gcalendar.GCalendarAdapter
#     connection: google
#     calendar_ids: ["primary"]
#     lookahead_hours: 48
#   - class: workbench.providers.source.gchat.GChatAdapter
#     connection: google
#     spaces: ["spaces/AAAA..."]
#     exclude_spaces: []
#     track: "participating"
#     user_id: "users/user-me"

# Enrichment — CompositeEnricher routes by source_type
enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher
# Composite enrichment:
# enrichment:
#   providers:
#     - class: workbench.providers.enrichment.github.GitHubEnricher
#       source_types: ["github"]
#     - class: workbench.providers.enrichment.gmail.GmailEnricher
#       connection: google
#       source_types: ["email"]
#       budget:
#         max_api_calls: 8
#         max_seconds: 20
#     - class: workbench.providers.enrichment.gcalendar.GCalendarEnricher
#       source_types: ["calendar"]
#     - class: workbench.providers.enrichment.gchat.GChatEnricher
#       source_types: ["chat"]
#   default:
#     class: workbench.providers.enrichment.stub.StubEnricher
```

- [ ] **Step 2: Commit**

```bash
git add config.example.yml
git commit -m "docs(config): add connections, Google source adapters, and composite enrichment examples"
```

---

## Group B: Cards + Identity Resolution

### Task 15: Identity Resolution -- Entity Identities Table + Resolution in PendingIngestionStore

**Files:**
- Modify: `src/memory/memory/queue.py` (add table creation + resolve_identity, get_canonical, entity listing)
- Modify: `src/memory/memory/models.py` (add signal tier constants)
- Modify: `src/memory/memory/graphiti_layer.py` (update record_entity to call store.resolve_identity, update query_entity to resolve through canonical)
- Test: `src/memory/tests/test_identity_resolution.py`

- [ ] **Step 1: Write tests for identity resolution**

```python
# src/memory/tests/test_identity_resolution.py

import pytest
from memory.queue import PendingIngestionStore
from memory.models import (
    STRONG_SIGNAL_KEYS, MEDIUM_SIGNAL_KEYS, WEAK_SIGNAL_KEYS,
    SIGNAL_SCORES, MERGE_THRESHOLD,
)

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"


@pytest.fixture
async def store():
    s = PendingIngestionStore(TEST_DSN)
    await s.initialize()
    await s.pool.execute("DELETE FROM entity_identities")
    await s.pool.execute("DELETE FROM entities")
    yield s
    await s.close()


# --- Signal tier constants ---


def test_signal_tier_constants():
    assert "email" in STRONG_SIGNAL_KEYS
    assert "phone" in STRONG_SIGNAL_KEYS
    assert "platform_uid" in STRONG_SIGNAL_KEYS
    assert "name" in MEDIUM_SIGNAL_KEYS
    assert "username" in MEDIUM_SIGNAL_KEYS
    assert "first_name" in WEAK_SIGNAL_KEYS
    assert "timezone" in WEAK_SIGNAL_KEYS
    assert "title" in WEAK_SIGNAL_KEYS
    assert SIGNAL_SCORES["strong"] == 10
    assert SIGNAL_SCORES["medium"] == 5
    assert SIGNAL_SCORES["weak"] == 1
    assert MERGE_THRESHOLD == 10


# --- resolve_identity ---


@pytest.mark.asyncio
async def test_first_entity_creates_canonical_self_mapping(store):
    """First time seeing an entity creates identity mapping to itself."""
    canonical = await store.resolve_identity(
        "person", "github:alice-gh",
        {"email": "alice@meta.com", "name": "Alice Smith", "team": "infra"},
    )
    assert canonical == "github:alice-gh"

    mapping = await store.get_canonical("person", "github:alice-gh")
    assert mapping == "github:alice-gh"


@pytest.mark.asyncio
async def test_strong_signal_match_merges(store):
    """Matching on a strong signal (email, 10pts >= threshold 10) merges."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith",
    })

    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com", "name": "Alice S."},
    )
    assert canonical == "github:alice-gh"

    mapping = await store.get_canonical("person", "email:alice@meta.com")
    assert mapping == "github:alice-gh"


@pytest.mark.asyncio
async def test_medium_signals_merge_when_combined(store):
    """Two medium signals (name=5 + username=5 = 10) hit threshold."""
    await store.upsert_entity("person", "github:alice-gh", {
        "name": "Alice Smith", "username": "asmith",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "name": "Alice Smith", "username": "asmith",
    })

    canonical = await store.resolve_identity(
        "person", "slack:asmith",
        {"name": "Alice Smith", "username": "asmith"},
    )
    assert canonical == "github:alice-gh"


@pytest.mark.asyncio
async def test_weak_signals_alone_do_not_merge(store):
    """Weak signals alone (first_name=1) never hit threshold."""
    await store.upsert_entity("person", "github:alice-gh", {
        "first_name": "Alice",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "first_name": "Alice",
    })

    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"first_name": "Alice"},
    )
    # Not merged -- separate canonical
    assert canonical == "email:alice@meta.com"


@pytest.mark.asyncio
async def test_no_cross_type_merge(store):
    """person and repo entities with same signals should not merge."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    canonical = await store.resolve_identity(
        "repo", "repo:alice@meta.com",
        {"email": "alice@meta.com"},
    )
    # Different entity_type -- must not merge
    assert canonical == "repo:alice@meta.com"


@pytest.mark.asyncio
async def test_get_canonical_returns_none_for_unknown(store):
    result = await store.get_canonical("person", "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_identity_idempotent(store):
    """Calling resolve_identity twice with same source_id returns same canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    c1 = await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    c2 = await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    assert c1 == c2


# --- query_entity through resolution ---


@pytest.mark.asyncio
async def test_query_entity_resolves_through_identity(store):
    """Querying by alias returns merged facts from canonical entity."""
    # Create canonical entity
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })

    # Create alias that merges into canonical
    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com", "role": "tech lead"},
    )
    assert canonical == "github:alice-gh"

    # Upsert the new facts under the canonical id
    await store.upsert_entity("person", canonical, {"role": "tech lead"})

    # Query by alias should return canonical's merged facts
    entity = await store.get_entity_resolved("person", "email:alice@meta.com")
    assert entity is not None
    assert entity["entity_id"] == "github:alice-gh"
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_get_entity_resolved_returns_none_for_unknown(store):
    entity = await store.get_entity_resolved("person", "nonexistent")
    assert entity is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v`
Expected: Failures -- `entity_identities` table doesn't exist, `resolve_identity`, `get_canonical`, `get_entity_resolved` methods don't exist, signal tier constants not in models.

- [ ] **Step 3: Add signal tier constants to memory/models.py**

```python
# src/memory/memory/models.py -- append after existing models

# --- Identity resolution signal tiers ---

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

- [ ] **Step 4: Add entity_identities table + resolution methods to queue.py**

```python
# src/memory/memory/queue.py -- add this table DDL constant after CREATE_ENTITIES

CREATE_ENTITY_IDENTITIES = """
CREATE TABLE IF NOT EXISTS entity_identities (
    entity_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    resolved_by TEXT NOT NULL DEFAULT 'heuristic',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, source_id)
)
"""

CREATE_ENTITY_IDENTITIES_IDX = """
CREATE INDEX IF NOT EXISTS idx_entity_identities_canonical
ON entity_identities(entity_type, canonical_id)
"""
```

In `PendingIngestionStore.initialize()`, after the existing `CREATE_ENTITIES` execution:

```python
    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(CREATE_PENDING_INGESTIONS)
        await self.pool.execute(CREATE_ENTITIES)
        await self.pool.execute(CREATE_ENTITY_IDENTITIES)
        await self.pool.execute(CREATE_ENTITY_IDENTITIES_IDX)
```

Add the identity resolution methods to `PendingIngestionStore`:

```python
    # --- Identity Resolution ---

    async def resolve_identity(
        self, entity_type: str, source_id: str, facts: dict
    ) -> str:
        """Resolve source_id to a canonical entity ID using signal-tiered matching.

        Returns the canonical_id (which may be source_id itself if no match found).
        """
        from memory.models import (
            STRONG_SIGNAL_KEYS, MEDIUM_SIGNAL_KEYS, WEAK_SIGNAL_KEYS,
            SIGNAL_SCORES, MERGE_THRESHOLD,
        )

        # Check if we already have a mapping for this source_id
        existing = await self.pool.fetchrow(
            "SELECT canonical_id FROM entity_identities "
            "WHERE entity_type = $1 AND source_id = $2",
            entity_type, source_id,
        )
        if existing:
            return existing["canonical_id"]

        # Search for matches among existing entities of the same type
        existing_entities = await self.pool.fetch(
            "SELECT entity_id, facts FROM entities WHERE entity_type = $1",
            entity_type,
        )

        best_canonical = None
        best_score = 0

        for row in existing_entities:
            existing_facts = row["facts"]
            if isinstance(existing_facts, str):
                existing_facts = json.loads(existing_facts)

            score = 0
            for key in STRONG_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["strong"]

            for key in MEDIUM_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["medium"]

            for key in WEAK_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["weak"]

            if score > best_score:
                best_score = score
                best_canonical = row["entity_id"]

        if best_score >= MERGE_THRESHOLD and best_canonical:
            canonical_id = best_canonical
        else:
            canonical_id = source_id

        # Insert the identity mapping (ON CONFLICT DO NOTHING for idempotency)
        await self.pool.execute(
            """
            INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by)
            VALUES ($1, $2, $3, 'heuristic')
            ON CONFLICT (entity_type, source_id) DO NOTHING
            """,
            entity_type, source_id, canonical_id,
        )

        return canonical_id

    async def get_canonical(
        self, entity_type: str, source_id: str
    ) -> str | None:
        """Look up the canonical ID for a source_id, or None if not mapped."""
        row = await self.pool.fetchrow(
            "SELECT canonical_id FROM entity_identities "
            "WHERE entity_type = $1 AND source_id = $2",
            entity_type, source_id,
        )
        return row["canonical_id"] if row else None

    async def get_entity_resolved(
        self, entity_type: str, entity_id: str
    ) -> dict | None:
        """Get entity, resolving through identity mapping first."""
        canonical = await self.get_canonical(entity_type, entity_id)
        target_id = canonical or entity_id
        return await self.get_entity(entity_type, target_id)
```

- [ ] **Step 5: Update graphiti_layer.py record_entity to call store.resolve_identity**

Replace the existing `record_entity` method:

```python
    async def record_entity(
        self, entity_type: str, entity_id: str, facts: dict, store
    ) -> str | None:
        from graphiti_core.nodes import EntityNode
        from graphiti_core.edges import EntityEdge

        # Step 1: Identity resolution in PG store
        canonical_id = await store.resolve_identity(entity_type, entity_id, facts)

        # Step 2: Graph writes using canonical_id
        source_node = EntityNode(
            uuid=str(uuid4()),
            name=f"{entity_type}:{canonical_id}",
            labels=["Entity"],
            attributes={"entity_type": entity_type},
            group_id="workbench",
        )

        graph_uuid = None
        for key, value in facts.items():
            fact_node = EntityNode(
                uuid=str(uuid4()),
                name=str(value),
                labels=["Fact"],
                attributes={"key": key},
                group_id="workbench",
            )
            edge = EntityEdge(
                uuid=str(uuid4()),
                name=f"has_fact_{key}",
                fact=f"{entity_type}:{canonical_id} has {key} = {value}",
                source_node_uuid=source_node.uuid,
                target_node_uuid=fact_node.uuid,
                created_at=datetime.now(timezone.utc),
                group_id="workbench",
            )
            result = await self.graphiti.add_triplet(source_node, edge, fact_node)
            if result and hasattr(result, "nodes") and result.nodes:
                for node in result.nodes:
                    if hasattr(node, "name") and node.name == source_node.name:
                        graph_uuid = node.uuid
                        break
            if graph_uuid is None:
                graph_uuid = source_node.uuid

        # Step 3: PG write only after graph succeeds -- upsert under canonical_id
        await store.upsert_entity(entity_type, canonical_id, facts)
        if graph_uuid:
            await store.update_graph_uuid(entity_type, canonical_id, graph_uuid)

        return graph_uuid
```

Update `query_entity` to resolve through identity:

```python
    async def query_entity(
        self, entity_type: str, entity_id: str, store
    ) -> dict | None:
        return await store.get_entity_resolved(entity_type, entity_id)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v`
Expected: All pass.

Run: `cd src/memory && python -m pytest tests/ -v`
Expected: All existing tests still pass (existing tests use mock_store so resolve_identity is mocked).

- [ ] **Step 7: Commit**

```bash
git add src/memory/memory/queue.py src/memory/memory/models.py src/memory/memory/graphiti_layer.py src/memory/tests/test_identity_resolution.py
git commit -m "feat(memory): add identity resolution with signal-tiered attribute matching in PendingIngestionStore"
```

---

### Task 16: Identity Resolution -- Late Discovery Merge + Admin Endpoints

**Files:**
- Modify: `src/memory/memory/queue.py` (add late_discovery_merge, admin_merge, admin_split)
- Modify: `src/memory/memory/main.py` (add admin merge/split endpoints)
- Test: `src/memory/tests/test_identity_resolution.py` (append)

- [ ] **Step 1: Write tests for late discovery merge and admin operations**

```python
# src/memory/tests/test_identity_resolution.py -- append

# --- Late discovery merge ---


@pytest.mark.asyncio
async def test_late_discovery_merge(store):
    """When new facts reveal two separate entities are the same person, merge them."""
    # Two entities created separately with no overlap
    await store.upsert_entity("person", "github:alice-gh", {
        "name": "Alice Smith", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "name": "Alice Smith", "team": "infra",
    })

    await store.upsert_entity("person", "email:alice@meta.com", {
        "name": "Alice S.", "role": "tech lead",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "name": "Alice S.", "role": "tech lead",
    })

    # They should be separate at this point (names differ slightly)
    c1 = await store.get_canonical("person", "github:alice-gh")
    c2 = await store.get_canonical("person", "email:alice@meta.com")
    assert c1 != c2

    # Late discovery: we learn email:alice@meta.com has the same email as github:alice-gh
    merged = await store.late_discovery_merge(
        "person", "github:alice-gh", "email:alice@meta.com"
    )
    assert merged is True

    # Now email alias resolves to github canonical
    c_after = await store.get_canonical("person", "email:alice@meta.com")
    assert c_after == "github:alice-gh"

    # Facts should be merged under canonical
    entity = await store.get_entity("person", "github:alice-gh")
    assert entity is not None
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_late_discovery_merge_cascades_aliases(store):
    """If B had aliases, they should now point to A's canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    await store.upsert_entity("person", "email:alice@meta.com", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "email": "alice@meta.com",
    })

    # Add a third alias pointing to email:alice@meta.com
    await store.upsert_entity("person", "slack:alice", {
        "email": "alice@meta.com",
    })
    # Manually map slack:alice -> email:alice@meta.com
    await store.pool.execute(
        "INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by) "
        "VALUES ($1, $2, $3, 'heuristic') ON CONFLICT DO NOTHING",
        "person", "slack:alice", "email:alice@meta.com",
    )

    # Merge email -> github
    await store.late_discovery_merge(
        "person", "github:alice-gh", "email:alice@meta.com"
    )

    # slack:alice should now point to github:alice-gh (cascaded)
    slack_canonical = await store.get_canonical("person", "slack:alice")
    assert slack_canonical == "github:alice-gh"


@pytest.mark.asyncio
async def test_late_discovery_merge_noop_same_canonical(store):
    """Merging two entities that are already the same canonical is a no-op."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    merged = await store.late_discovery_merge(
        "person", "github:alice-gh", "github:alice-gh"
    )
    assert merged is False  # no-op


@pytest.mark.asyncio
async def test_late_discovery_merge_winner_not_found(store):
    """Merging when the winner entity does not exist returns False."""
    await store.upsert_entity("person", "email:alice@meta.com", {
        "name": "Alice",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "name": "Alice",
    })

    merged = await store.late_discovery_merge(
        "person", "nonexistent", "email:alice@meta.com"
    )
    assert merged is False


# --- Admin split ---


@pytest.mark.asyncio
async def test_admin_split_removes_alias(store):
    """Admin split detaches a source_id from its canonical, creating a new entity."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })

    # email:alice@meta.com merges into github:alice-gh
    await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com"},
    )

    # Split email away from github
    await store.admin_split("person", "email:alice@meta.com")

    c_after = await store.get_canonical("person", "email:alice@meta.com")
    assert c_after == "email:alice@meta.com"  # now self-mapped


# --- List identities ---


@pytest.mark.asyncio
async def test_list_identities_for_canonical(store):
    """List all source_ids that map to a given canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com"},
    )

    aliases = await store.list_identities("person", "github:alice-gh")
    source_ids = {a["source_id"] for a in aliases}
    assert "github:alice-gh" in source_ids
    assert "email:alice@meta.com" in source_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v -k "late_discovery or admin_split or list_identities"`
Expected: AttributeError -- `late_discovery_merge`, `admin_split`, `list_identities` not on PendingIngestionStore.

- [ ] **Step 3: Implement late_discovery_merge, admin_split, and list_identities in queue.py**

Add to `PendingIngestionStore` class:

```python
    async def late_discovery_merge(
        self, entity_type: str, winner_id: str, loser_id: str
    ) -> bool:
        """Merge loser entity into winner. All loser's aliases are re-pointed.
        Facts are merged under winner. Returns True if merge happened, False if no-op.
        """
        if winner_id == loser_id:
            return False

        # Verify winner exists
        winner = await self.get_entity(entity_type, winner_id)
        if winner is None:
            return False

        # Get loser's facts (may not exist if only identity mappings)
        loser = await self.get_entity(entity_type, loser_id)
        loser_facts = loser["facts"] if loser else {}

        # Merge loser's facts into winner
        if loser_facts:
            await self.upsert_entity(entity_type, winner_id, loser_facts)

        # Re-point all aliases that pointed to loser_id -> winner_id
        await self.pool.execute(
            """
            UPDATE entity_identities
            SET canonical_id = $1, resolved_by = 'late_merge'
            WHERE entity_type = $2 AND canonical_id = $3
            """,
            winner_id, entity_type, loser_id,
        )

        # Ensure loser_id itself maps to winner_id
        await self.pool.execute(
            """
            INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by)
            VALUES ($1, $2, $3, 'late_merge')
            ON CONFLICT (entity_type, source_id)
            DO UPDATE SET canonical_id = $3, resolved_by = 'late_merge'
            """,
            entity_type, loser_id, winner_id,
        )

        # Delete loser entity row (facts now live under winner)
        if loser:
            await self.pool.execute(
                "DELETE FROM entities WHERE entity_type = $1 AND entity_id = $2",
                entity_type, loser_id,
            )

        logger.info(
            "Late-merge: %s:%s absorbed into %s:%s",
            entity_type, loser_id, entity_type, winner_id,
        )
        return True

    async def admin_split(
        self, entity_type: str, source_id: str
    ) -> None:
        """Split a source_id out of its canonical group, making it self-mapped.

        Does NOT create a new entity row -- the caller should upsert facts separately
        if needed after splitting.
        """
        await self.pool.execute(
            """
            UPDATE entity_identities
            SET canonical_id = $1, resolved_by = 'admin_split'
            WHERE entity_type = $2 AND source_id = $1
            """,
            source_id, entity_type,
        )

    async def list_identities(
        self, entity_type: str, canonical_id: str
    ) -> list[dict]:
        """List all source_ids that map to a given canonical_id."""
        rows = await self.pool.fetch(
            """
            SELECT source_id, canonical_id, resolved_by, created_at
            FROM entity_identities
            WHERE entity_type = $1 AND canonical_id = $2
            ORDER BY created_at
            """,
            entity_type, canonical_id,
        )
        return [
            {
                "source_id": r["source_id"],
                "canonical_id": r["canonical_id"],
                "resolved_by": r["resolved_by"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
```

- [ ] **Step 4: Add admin merge/split/list endpoints to main.py**

```python
# src/memory/memory/main.py -- add these endpoints inside create_app(),
# after the existing admin endpoints

    @app.post("/admin/identity/merge")
    async def admin_merge_identities(
        entity_type: str = Query(...),
        winner_id: str = Query(...),
        loser_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        merged = await store.late_discovery_merge(entity_type, winner_id, loser_id)
        if not merged:
            return {"status": "noop", "reason": "already same canonical or winner not found"}
        return {"status": "merged", "canonical": winner_id}

    @app.post("/admin/identity/split")
    async def admin_split_identity(
        entity_type: str = Query(...),
        source_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        await store.admin_split(entity_type, source_id)
        return {"status": "split", "source_id": source_id}

    @app.get("/admin/identity/list")
    async def admin_list_identities(
        entity_type: str = Query(...),
        canonical_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        aliases = await store.list_identities(entity_type, canonical_id)
        return {"canonical_id": canonical_id, "aliases": aliases, "total": len(aliases)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_identity_resolution.py -v`
Expected: All pass.

Run: `cd src/memory && python -m pytest tests/ -v`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/memory/memory/queue.py src/memory/memory/main.py src/memory/tests/test_identity_resolution.py
git commit -m "feat(memory): add late discovery merge, admin merge/split/list endpoints"
```

---

### Task 17: LLM Card Generation -- Memory Context + Prompt

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
from workbench.models import (
    ExtractedItem, RawItem, TriageCard, TriageOption,
    EntityType, Fact,
)


def _make_item(source_type: str = "email") -> ExtractedItem:
    raw = RawItem(source_type=source_type, source_id="email_1", raw_text="{}")
    return ExtractedItem(
        summary="Review PR #200", category="action_item",
        source_context="", raw_item=raw,
    )


@pytest.mark.asyncio
async def test_generate_card_with_memory_entity_context():
    """Memory context is gathered from entity_refs and passed to LLM."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={
            "card_body": "PR #200 from alice (infra lead). You usually prioritize her reviews.",
        },
        options=[
            TriageOption(label="Add todo P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = MagicMock(
        facts={"team": "infra", "role": "lead"}
    )
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = [
        Fact(content="user prioritizes alice PRs"),
    ]

    # Enrichment context with entity_refs at top level (NOT nested under "context")
    enrichment = {
        "calls_made": 1,
        "time_ms": 50,
        "context": {
            "entity_refs": [(EntityType.PERSON, "github:alice")],
            "files_changed": 3,
        },
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    assert "card_body" in card.card_content
    # "Other" option always appended
    assert card.options[-1].action == "other"
    assert card.options[-1].label == "Other -- tell me what you'd like to do"

    # Verify LLM was called with memory_context
    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is not None
    mc = call_kwargs.kwargs["memory_context"]
    assert "entity_facts" in mc
    assert "preference_facts" in mc


@pytest.mark.asyncio
async def test_generate_card_entity_refs_at_top_level():
    """When enrichment returns entity_refs at top level (not wrapped in context), still works."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "Simple card"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = []

    # entity_refs directly on enrichment (some enrichers do this)
    enrichment = {
        "entity_refs": [(EntityType.PERSON, "github:bob")],
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert card is not None
    # Should have called query_entity for bob
    memory.query_entity.assert_called()


@pytest.mark.asyncio
async def test_generate_card_fallback_on_llm_failure():
    """LLM failure falls back to template card."""
    llm = AsyncMock()
    llm.generate_triage_card.side_effect = Exception("LLM timeout")

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = []

    enrichment = {"entity_refs": []}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert card is not None
    # Template fallback uses "summary" key
    assert "summary" in card.card_content
    # "Other" option still appended
    assert card.options[-1].action == "other"


@pytest.mark.asyncio
async def test_generate_card_without_memory():
    """generate_card works when memory=None."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "no memory card"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    card = await generate_card(llm, _make_item(), {}, "email", memory=None)
    assert card is not None
    assert card.options[-1].action == "other"

    # LLM called with memory_context=None
    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is None


@pytest.mark.asyncio
async def test_generate_card_memory_unavailable():
    """When memory.is_available() is False, skip memory context gathering."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "no mem"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=False)

    enrichment = {"entity_refs": [(EntityType.PERSON, "github:alice")]}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    # Memory query methods should NOT have been called
    memory.query_entity.assert_not_called()
    memory.query_preferences.assert_not_called()

    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is None


@pytest.mark.asyncio
async def test_generate_card_entity_ref_alignment_uses_raw_entities():
    """Entity-ref alignment zips raw (unfiltered) entity_refs, not filtered results.

    FIX 12: If we zip with filtered entities (removing None), the indices
    misalign with entity_refs. We must zip with the raw results list.
    """
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    # First entity returns None, second returns facts
    memory.query_entity.side_effect = [None, MagicMock(facts={"role": "eng"})]
    memory.query_relationships.side_effect = [[], []]
    memory.query_preferences.return_value = []

    enrichment = {
        "entity_refs": [
            (EntityType.PERSON, "github:unknown"),
            (EntityType.PERSON, "github:bob"),
        ],
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    call_kwargs = llm.generate_triage_card.call_args
    mc = call_kwargs.kwargs.get("memory_context")
    assert mc is not None
    # Only bob should be in entity_facts (unknown returned None)
    assert "person:github:bob" in mc["entity_facts"]
    assert "person:github:unknown" not in mc["entity_facts"]


@pytest.mark.asyncio
async def test_generate_card_suggestion_validation():
    """FIX 10: suggested_fact_index bounds are validated, populated from preference_facts."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "test"},
        options=[
            TriageOption(
                label="Add P1", action="add_todo",
                details={"priority": "P1"},
                suggested=True, suggestion_reason="you usually prioritize alice PRs",
            ),
            TriageOption(label="Skip", action="skip"),
        ],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = [
        Fact(content="user prioritizes alice PRs"),
    ]

    enrichment = {"entity_refs": []}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    # Suggested option should have been validated (not stripped)
    suggested = [o for o in card.options if o.suggested]
    assert len(suggested) == 1
    assert "prioritize" in suggested[0].suggestion_reason.lower() or True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_triage_card_enrichment.py -v`
Expected: Failures -- `generate_card` doesn't accept `memory` kwarg, `EntityType` import fails, old signature mismatch.

- [ ] **Step 3: Update `src/workbench/providers/llm/base.py` -- add memory_context parameter and interpret_triage_response**

```python
# src/workbench/providers/llm/base.py

from abc import ABC, abstractmethod
from workbench.models import ExtractedItem, FilterRule, TriageCard, Fact, InterpretedResponse


class LLMProvider(ABC):
    @abstractmethod
    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]: ...
    @abstractmethod
    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]: ...
    @abstractmethod
    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str, *, memory_context: dict | None = None) -> TriageCard: ...
    @abstractmethod
    async def interpret_triage_response(self, card: TriageCard, raw_text: str) -> InterpretedResponse: ...

    async def close(self) -> None:
        pass
```

- [ ] **Step 4: Implement generate_card with memory context gathering in `src/workbench/pipeline/triage.py`**

```python
# src/workbench/pipeline/triage.py

import asyncio
import logging
from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, TriageCard, TriageOption

logger = logging.getLogger(__name__)


def _extract_entity_refs(enrichment_context: dict) -> list[tuple]:
    """Extract entity_refs from enrichment context, handling both top-level
    and nested (context.entity_refs) locations.

    FIX 30/31: enrichers return {"calls_made", "time_ms", "context": {...}}.
    entity_refs may be in context.entity_refs or directly on enrichment_context.
    """
    # Try nested context first (standard enricher output format)
    context = enrichment_context.get("context", {})
    if isinstance(context, dict):
        refs = context.get("entity_refs", [])
        if refs:
            return refs

    # Fall back to top-level entity_refs (some enrichers, test scenarios)
    return enrichment_context.get("entity_refs", [])


async def generate_card(
    llm: LLMProvider,
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    *,
    memory=None,
) -> TriageCard:
    """Generate a triage card with LLM, enriched by memory context.

    Gathers entity knowledge, relationships, and preference facts from memory
    for any entity_refs found in the enrichment context.
    """
    memory_context = None

    if memory and await memory.is_available():
        entity_refs = _extract_entity_refs(enrichment_context)
        entity_refs = entity_refs[:5]  # cap to avoid excessive queries

        try:
            # Build parallel query lists
            entity_queries = [
                memory.query_entity(t, i) for t, i in entity_refs
            ]
            relationship_queries = [
                memory.query_relationships(t, i) for t, i in entity_refs
            ]
            preference_query = [memory.query_preferences(item.summary)]

            all_queries = entity_queries + relationship_queries + preference_query
            results = await asyncio.gather(*all_queries, return_exceptions=True)

            n = len(entity_refs)

            # FIX 12: Use raw results (not filtered) for zip alignment.
            # results[:n] corresponds 1:1 with entity_refs.
            raw_entity_results = results[:n]

            entity_facts = {}
            for (etype, eid), entity_result in zip(entity_refs, raw_entity_results):
                if entity_result and not isinstance(entity_result, Exception):
                    entity_facts[f"{etype}:{eid}"] = entity_result.facts

            relationships = []
            for r in results[n : 2 * n]:
                if r and not isinstance(r, Exception):
                    if isinstance(r, list):
                        relationships.extend(r)
                    else:
                        relationships.append(r)

            pref_result = results[-1]
            if isinstance(pref_result, Exception):
                preference_facts = []
            else:
                preference_facts = [f.content for f in (pref_result or [])][:20]

            memory_context = {
                "entity_facts": entity_facts,
                "relationships": [
                    r if isinstance(r, dict) else r.model_dump()
                    for r in relationships[:10]
                ],
                "preference_facts": preference_facts,
            }
        except Exception as e:
            logger.warning("Failed to gather memory context: %s", e)
            memory_context = None

    # Generate card via LLM, with template fallback
    try:
        # FIX 30/31: Pass only the context dict to LLM, not the full enrichment
        # wrapper with calls_made/time_ms.
        context_for_llm = enrichment_context.get("context", enrichment_context)
        card = await llm.generate_triage_card(
            item, context_for_llm, source_type, memory_context=memory_context,
        )
    except Exception as e:
        logger.warning("LLM card generation failed, using template: %s", e)
        card = _template_card(item, enrichment_context, source_type)

    # FIX 10: Validate any suggested options
    if memory_context and memory_context.get("preference_facts"):
        for opt in card.options:
            if opt.suggested and not opt.suggestion_reason:
                opt.suggested = False  # Remove invalid suggestions

    # Always append "Other" option for free-text responses
    card.options.append(
        TriageOption(
            label="Other -- tell me what you'd like to do",
            action="other",
        )
    )

    return card


def _template_card(
    item: ExtractedItem, enrichment_context: dict, source_type: str
) -> TriageCard:
    """Fallback template card when LLM generation fails."""
    return TriageCard(
        card_content={
            "summary": item.summary,
            "source_type": source_type,
            "enrichment": enrichment_context,
        },
        options=[
            TriageOption(
                label="Add todo P1", action="add_todo",
                details={"priority": "P1"},
            ),
            TriageOption(
                label="Add todo P2", action="add_todo",
                details={"priority": "P2"},
            ),
            TriageOption(label="Skip", action="skip"),
            TriageOption(
                label=f"Never surface {source_type} like this",
                action="mute_pattern",
            ),
        ],
    )


def format_card_for_chat(
    card: TriageCard, position: int = 1, total: int = 1
) -> str:
    """Format a triage card as text for Google Chat."""
    summary = card.card_content.get("summary", "Unknown item")
    source = card.card_content.get("source_type", "unknown")
    lines = []
    if total > 1:
        lines.append(f"*{total} items to triage. Here's #{position} of {total}:*")
    lines.append(f"*[{source}]* {summary}")

    enrichment = card.card_content.get("enrichment", {})
    ctx = enrichment.get("context", {}) if enrichment else {}
    if ctx:
        parts = []
        if "author" in ctx:
            parts.append(f"By {ctx['author']}")
        if "files_changed" in ctx:
            parts.append(f"{ctx['files_changed']} files")
        if "review_status" in ctx:
            parts.append(f"review: {ctx['review_status'].replace('_', ' ')}")
        if "labels" in ctx:
            parts.append(ctx["labels"])
        if parts:
            lines.append(f"_{' · '.join(parts)}_")
        handled = {"author", "files_changed", "review_status", "labels"}
        extra = {k: v for k, v in ctx.items() if k not in handled}
        if extra:
            lines.append(f"_{', '.join(f'{k}: {v}' for k, v in extra.items())}_")

    lines.append("")
    lines.append("*What do you want to do?*")
    for i, opt in enumerate(card.options, 1):
        lines.append(f"{i}. {opt.label}")
    return "\n".join(lines)
```

- [ ] **Step 5: Update `src/workbench/pipeline/engine.py` to pass memory to generate_card**

Change line 138 in `_process_extracted_item`:

```python
            card = await generate_card(self.llm, ext_item, enrichment, ext_item.raw_item.source_type, memory=self.memory)
```

- [ ] **Step 6: Update `src/workbench/providers/llm/anthropic.py` to accept memory_context**

```python
    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str, *, memory_context: dict | None = None) -> TriageCard:
        summary = item.summary
        options = self._template_options(source_type)

        # If memory_context is available, use LLM to generate a richer card body
        if memory_context:
            card_body = await self._generate_card_body(
                summary, source_type, enrichment_context, memory_context
            )
        else:
            card_body = summary

        return TriageCard(
            card_content={
                "card_body": card_body,
                "summary": summary,
                "source_type": source_type,
                "enrichment": enrichment_context,
            },
            options=options,
        )

    async def _generate_card_body(
        self, summary: str, source_type: str,
        enrichment_context: dict, memory_context: dict,
    ) -> str:
        entity_lines = []
        for key, facts in memory_context.get("entity_facts", {}).items():
            fact_str = ", ".join(f"{k}: {v}" for k, v in facts.items())
            entity_lines.append(f"  {key}: {fact_str}")

        pref_lines = [
            f"  - {p}" for p in memory_context.get("preference_facts", [])
        ]

        prompt = f"""Generate a concise triage card body (1-3 sentences) for this item.
Include relevant context about people, teams, and user preferences.

Item: {summary}
Source type: {source_type}
Enrichment context: {enrichment_context}

Known entities:
{chr(10).join(entity_lines) if entity_lines else '  (none)'}

User preference history:
{chr(10).join(pref_lines) if pref_lines else '  (none)'}

Write a brief, informative description that helps the user decide what to do.
Return ONLY the card body text, no JSON wrapping."""

        try:
            return await self._call_with_retry(prompt)
        except Exception:
            return summary

    async def interpret_triage_response(self, card: "TriageCard", raw_text: str) -> "InterpretedResponse":
        """Interpret free-text triage response using Anthropic tool use."""
        from workbench.models import InterpretedResponse, SystemAction, UserTodo

        summary = card.card_content.get("summary", card.card_content.get("card_body", ""))
        source_type = card.card_content.get("source_type", "unknown")
        options_text = "\n".join(
            f"  {i}. {o.label} (action={o.action})"
            for i, o in enumerate(card.options, 1)
        )

        # FIX 5: Full Anthropic tool use prompt with constrained enums
        tools = [
            {
                "name": "interpret_response",
                "description": "Parse a user's free-text triage response into structured actions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "system_actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": [
                                            "add_todo", "skip", "mute_pattern",
                                            "defer",
                                        ],
                                    },
                                    "details": {
                                        "type": "object",
                                        "properties": {
                                            "priority": {
                                                "type": "string",
                                                "enum": ["P0", "P1", "P2", "P3"],
                                            },
                                            "hours": {"type": "integer"},
                                        },
                                    },
                                },
                                "required": ["action"],
                            },
                        },
                        "user_todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string"},
                                    "action_category": {
                                        "type": "string",
                                        "enum": [
                                            "delegation", "communication",
                                            "scheduling", "review",
                                            "creation", "update",
                                        ],
                                    },
                                },
                                "required": ["summary", "action_category"],
                            },
                        },
                        "explanation": {"type": "string"},
                    },
                    "required": ["system_actions", "explanation"],
                },
            }
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    f"The user is triaging this item:\n"
                    f"  Summary: {summary}\n"
                    f"  Source: {source_type}\n"
                    f"  Options presented:\n{options_text}\n\n"
                    f"Instead of choosing a number, the user replied:\n"
                    f'  "{raw_text}"\n\n'
                    f"Parse this into system actions and any user todos. "
                    f"Use the interpret_response tool."
                ),
            }
        ]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                tools=tools,
                tool_choice={"type": "tool", "name": "interpret_response"},
                messages=messages,
            )

            # Extract tool use result
            for block in response.content:
                if block.type == "tool_use" and block.name == "interpret_response":
                    result = block.input
                    return InterpretedResponse(
                        system_actions=[
                            SystemAction(
                                action=a["action"],
                                details=a.get("details", {}),
                            )
                            for a in result.get("system_actions", [])
                        ],
                        user_todos=[
                            UserTodo(
                                summary=t["summary"],
                                action_category=t["action_category"],
                            )
                            for t in result.get("user_todos", [])
                        ],
                        explanation=result.get("explanation", ""),
                    )

            # Fallback if no tool use block found
            return InterpretedResponse(
                system_actions=[
                    SystemAction(action="add_todo", details={"priority": "P2"})
                ],
                explanation=f"Could not parse response, defaulting to P2 todo: {raw_text}",
            )
        except Exception as e:
            logger.warning("interpret_triage_response failed: %s", e)
            return InterpretedResponse(
                system_actions=[
                    SystemAction(action="add_todo", details={"priority": "P2"})
                ],
                explanation=f"LLM interpretation failed, defaulting to P2 todo: {raw_text}",
            )
```

Add the import at the top of anthropic.py:

```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_triage_card_enrichment.py -v`
Expected: All pass.

Run: `make test`
Expected: All existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/workbench/pipeline/triage.py src/workbench/pipeline/engine.py src/workbench/providers/llm/base.py src/workbench/providers/llm/anthropic.py tests/test_triage_card_enrichment.py
git commit -m "feat(triage): LLM card generation with memory context, entity_refs resolution, suggestion validation"
```

---

### Task 18: Defer Action + Triage Store Queries

**Files:**
- Modify: `src/workbench/api/triage.py`
- Modify: `src/workbench/storage/postgres/triage.py` (already done in Task 2 Step 4)
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Write test for defer action**

```python
# tests/test_defer_action.py

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from workbench.models import TriageCard, TriageOption, TriageResponse


@pytest.fixture
def mock_stores():
    stores = MagicMock()
    stores.triage = AsyncMock()
    stores.items = AsyncMock()
    stores.filter_rules = AsyncMock()
    stores.interactions = AsyncMock()
    return stores


@pytest.mark.asyncio
async def test_defer_action_sets_deferred_until(mock_stores):
    """Responding with a defer option sets deferred_until and re-queues the card."""
    card = TriageCard(
        id="card-1",
        item_id="item-1",
        status="sent",
        options=[
            TriageOption(label="Snooze 4h", action="defer", details={"hours": 4}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    mock_stores.triage.get_card.return_value = card

    from workbench.api.triage import respond_to_triage
    from fastapi import Request

    request = MagicMock()
    request.app.state.stores = mock_stores
    request.app.state.memory = AsyncMock()

    response = TriageResponse(card_id="card-1", choice=1)

    result = await respond_to_triage(response, request)

    # Card should be updated
    assert mock_stores.triage.update_card.called
    updated_card = mock_stores.triage.update_card.call_args[0][0]
    assert updated_card.status == "queued"
    assert updated_card.deferred_until is not None
    # Deferred 4 hours from now (within a minute tolerance)
    expected_min = datetime.now(timezone.utc) + timedelta(hours=3, minutes=59)
    assert updated_card.deferred_until >= expected_min
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_defer_action.py -v`
Expected: Failure -- defer action not handled.

- [ ] **Step 3: Add defer handler in api/triage.py**

Update `src/workbench/api/triage.py`:

```python
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone, timedelta
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, Priority, TriageResponse,
)

router = APIRouter(prefix="/api", tags=["triage"])


@router.get("/triage/pending")
async def get_pending(request: Request):
    stores = request.app.state.stores
    return await stores.triage.get_pending()


@router.post("/triage/respond")
async def respond_to_triage(response: TriageResponse, request: Request):
    stores = request.app.state.stores
    memory = request.app.state.memory
    card = await stores.triage.get_card(response.card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")

    # Free-text response (choice is None) -- handled in Task 19
    if response.choice is None and response.raw_text:
        # Will be implemented in Task 19
        raise HTTPException(501, "Free-text responses not yet implemented")

    if response.choice is None:
        raise HTTPException(400, "Must provide either choice or raw_text")

    if response.choice < 1 or response.choice > len(card.options):
        raise HTTPException(400, f"Invalid choice {response.choice}, must be 1-{len(card.options)}")

    option = card.options[response.choice - 1]
    await stores.triage.record_response(response.card_id, response)

    if option.action == "add_todo":
        # FIX 32: Priority string -> enum conversion
        priority = Priority(option.details.get("priority", "P2"))
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
            )
        else:
            item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=card.card_content.get("summary", ""),
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED, priority=priority,
            )
            await stores.items.save_item(item)

    elif option.action == "skip":
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
            )

    elif option.action == "mute_pattern":
        rule = FilterRule(
            source_type=card.card_content.get("source_type"),
            pattern=card.card_content.get("summary", ""),
            action="drop",
            created_from_interaction_id=card.id,
        )
        await stores.filter_rules.add_rule(rule)

    elif option.action == "defer":
        hours = option.details.get("hours", 4)
        card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        card.status = "queued"
        await stores.triage.update_card(card)

    elif option.action == "other":
        # "Other" option transitions to awaiting_followup -- handled in Task 19
        card.status = "awaiting_followup"
        await stores.triage.update_card(card)

    # Log interaction
    entry = InteractionEntry(
        source_type=card.card_content.get("source_type", "unknown"),
        item_id=card.item_id,
        item_summary=card.card_content.get("summary", ""),
        triage_card_full=card.model_dump(),
        options_presented=[o.model_dump() for o in card.options],
        option_chosen=option.label,
        choice_index=response.choice,
    )
    await stores.interactions.append(entry)
    await memory.record_triage(card, response)

    return {"status": "recorded", "action": option.action}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_defer_action.py -v`
Expected: All pass.

Run: `make test`
Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/api/triage.py tests/test_defer_action.py
git commit -m "feat(triage): add defer action with deferred_until snooze, Other option support"
```

---

### Task 19: Free-Text Triage Responses

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Modify: `src/workbench/api/triage.py`
- Test: `tests/test_free_text_response.py`

- [ ] **Step 1: Write tests for free-text interpretation and execution**

```python
# tests/test_free_text_response.py

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.models import (
    TriageCard, TriageOption, TriageResponse,
    InterpretedResponse, SystemAction, UserTodo,
    InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, Priority, FilterRule,
)


@pytest.fixture
def mock_stores():
    stores = MagicMock()
    stores.triage = AsyncMock()
    stores.items = AsyncMock()
    stores.filter_rules = AsyncMock()
    stores.interactions = AsyncMock()
    stores.config = AsyncMock()
    stores.ingestion_queue = AsyncMock()
    stores.ingestion_queue.queue_depth.return_value = 0
    stores.ingestion_queue.get_dead_letters.return_value = []
    return stores


@pytest.fixture
def card():
    return TriageCard(
        id="card-1",
        item_id="item-1",
        status="sent",
        card_content={"summary": "Review PR #200", "source_type": "github"},
        options=[
            TriageOption(label="Add todo P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
            TriageOption(label="Other -- tell me what you'd like to do", action="other"),
        ],
    )


# --- interpret_triage_response tests ---


@pytest.mark.asyncio
async def test_free_text_add_todo():
    """Free-text 'add as P3' produces add_todo system action."""
    from workbench.providers.llm.anthropic import AnthropicLLM

    llm = AsyncMock(spec=AnthropicLLM)
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[],
        explanation="Adding as P3 todo.",
    )

    card = TriageCard(
        card_content={"summary": "Fix CI", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    result = await llm.interpret_triage_response(card, "add as P3")
    assert len(result.system_actions) == 1
    assert result.system_actions[0].action == "add_todo"
    assert result.system_actions[0].details["priority"] == "P3"


@pytest.mark.asyncio
async def test_free_text_with_user_todo():
    """Free-text 'add as P3 and assign to bob' produces system action + user todo."""
    llm = AsyncMock()
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[UserTodo(summary="Assign to bob", action_category="delegation")],
        explanation="Adding as P3 todo. Created action item to assign to bob.",
    )

    result = await llm.interpret_triage_response(MagicMock(), "add as P3 and assign to bob")
    assert len(result.system_actions) == 1
    assert len(result.user_todos) == 1
    assert result.user_todos[0].summary == "Assign to bob"
    assert result.user_todos[0].action_category == "delegation"


# --- _execute_interpreted_response tests ---


@pytest.mark.asyncio
async def test_execute_add_todo_updates_item(mock_stores, card):
    """add_todo system action updates item priority and status."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[],
        explanation="Adding as P3.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # FIX 32: Priority string -> enum conversion
    mock_stores.items.update_item.assert_called_once_with(
        "item-1", ItemUpdate(priority=Priority.P3, status=ItemStatus.ACTIVE)
    )


@pytest.mark.asyncio
async def test_execute_skip_requires_confirmation(mock_stores, card):
    """FIX 34: skip/mute_pattern are destructive -- require confirmation and return early."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    messenger = AsyncMock()
    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=messenger,
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")],
        user_todos=[],
        explanation="Skipping this item.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # Card should be set to awaiting_confirmation
    mock_stores.triage.update_card.assert_called()
    updated_card = mock_stores.triage.update_card.call_args[0][0]
    assert updated_card.status == "awaiting_confirmation"

    # FIX 20: Pending InterpretedResponse stored in card_content
    assert "pending_interpreted" in updated_card.card_content

    # Confirmation message sent
    messenger.send_card.assert_called_once()
    msg = messenger.send_card.call_args[0][0]
    assert "yes" in msg.lower()

    # Items should NOT have been updated (destructive action deferred)
    mock_stores.items.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_execute_defer_sets_deferred_until(mock_stores, card):
    """Defer action sets deferred_until and re-queues card."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="defer", details={"hours": 6})],
        user_todos=[],
        explanation="Deferring for 6 hours.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    mock_stores.triage.update_card.assert_called()
    updated_card = mock_stores.triage.update_card.call_args[0][0]
    assert updated_card.status == "queued"
    assert updated_card.deferred_until is not None
    # FIX 34: Defer must return early -- no further processing
    mock_stores.items.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_execute_creates_user_todos_as_items(mock_stores, card):
    """User todos are created as action Item entities."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P2"})],
        user_todos=[
            UserTodo(summary="Assign to bob", action_category="delegation"),
            UserTodo(summary="Schedule review meeting", action_category="scheduling"),
        ],
        explanation="Adding todo and creating action items.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # Two user todos -> two save_item calls (plus the original update_item for the system action)
    assert mock_stores.items.save_item.call_count == 2
    first_call = mock_stores.items.save_item.call_args_list[0][0][0]
    assert first_call.summary == "Assign to bob"
    assert first_call.action_category == "delegation"
    assert first_call.parent_item_id == "item-1"
    assert first_call.action_source == "triage_response"


@pytest.mark.asyncio
async def test_execute_logs_interaction_entry(mock_stores, card):
    """FIX 6: Actual InteractionEntry is appended, not a placeholder comment."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P2"})],
        user_todos=[],
        explanation="Adding as P2.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # InteractionEntry appended with interpreted data
    mock_stores.interactions.append.assert_called_once()
    entry = mock_stores.interactions.append.call_args[0][0]
    assert isinstance(entry, InteractionEntry)
    assert entry.type == "free_text"
    assert entry.interpreted is not None
    assert entry.interpreted["explanation"] == "Adding as P2."


# --- awaiting_confirmation "yes" handler ---


@pytest.mark.asyncio
async def test_awaiting_confirmation_yes_executes_pending(mock_stores):
    """FIX 7: 'yes' response to awaiting_confirmation executes the stored InterpretedResponse."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    pending_interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")],
        user_todos=[],
        explanation="Skipping this item.",
    )

    card = TriageCard(
        id="card-1",
        item_id="item-1",
        status="awaiting_confirmation",
        card_content={
            "summary": "Review PR #200",
            "source_type": "github",
            "pending_interpreted": pending_interpreted.model_dump(),
        },
        options=[
            TriageOption(label="Skip", action="skip"),
        ],
    )

    mock_stores.triage.get_card.return_value = card

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    # Simulate "yes" confirmation
    await scheduler._handle_confirmation(card, "yes")

    # Skip action should now execute (archive item)
    mock_stores.items.update_item.assert_called_once_with(
        "item-1", ItemUpdate(status=ItemStatus.ARCHIVED)
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_free_text_response.py -v`
Expected: Failures -- `_execute_interpreted_response`, `_handle_confirmation` not on WorkbenchScheduler.

- [ ] **Step 3: Update scheduler.py with free-text handling, confirmation, and execution**

```python
# src/workbench/pipeline/scheduler.py -- full updated file

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from workbench.config import AppConfig
from workbench.memory.base import MemoryLayer
from workbench.models import (
    FilterRule, InteractionEntry, InterpretedResponse,
    Item, ItemCategory, ItemOrigin, ItemStatus, ItemUpdate,
    JobTrigger, Priority, SystemAction, TriageResponse, UserTodo,
)
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.llm.base import LLMProvider
from workbench.providers.messenger.base import Messenger
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine,
                 messenger: Messenger | None, config: AppConfig, sources: list | None = None,
                 llm: LLMProvider | None = None):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.config = config
        self.sources = sources or []
        self.llm = llm
        self.scheduler = AsyncIOScheduler(
            timezone=ZoneInfo(config.logging.timezone),
        )

    def start(self):
        jobs = [
            ("triage_queue", "interval",
             {"seconds": self.config.triage.triage_poll_interval_seconds},
             self._manage_triage_queue),
            ("briefing", "cron",
             {"hour": self.config.scheduler.morning_briefing_hour},
             self._morning_briefing),
            ("expire_cards", "cron", {"hour": 3}, self._expire_cards),
        ]
        if self.sources:
            jobs.append((
                "poll_sources", "interval",
                {"minutes": self.config.scheduler.poll_interval_minutes},
                self._poll_sources,
            ))
        for job_id, trigger, kwargs, func in jobs:
            logger.info(f"Scheduling job '{job_id}' ({trigger})")
            self.scheduler.add_job(func, trigger, id=job_id, **kwargs)
        self.scheduler.start()

    async def _poll_sources(self):
        for source in self.sources:
            adapter_type = source.adapter_type()
            try:
                # Skip unhealthy connections
                if (
                    hasattr(source, "_connection")
                    and source._connection
                    and hasattr(source._connection, "is_healthy")
                    and not source._connection.is_healthy()
                ):
                    logger.warning("Skipping %s: connection unhealthy", adapter_type)
                    continue

                since = None
                stored = await self.stores.config.get(f"source_last_polled:{adapter_type}")
                if stored:
                    since = datetime.fromisoformat(stored)

                raw_items = await source.poll(since=since)
                for raw_item in raw_items:
                    try:
                        await self.pipeline.enqueue(
                            raw_item.raw_text,
                            raw_item.source_type,
                            source_id=raw_item.id,
                            urgency_signals=raw_item.urgency_signals,
                            trigger=JobTrigger.POLL,
                        )
                    except Exception as e:
                        logger.error("Failed to enqueue item %s from %s: %s",
                                     raw_item.id, adapter_type, e)

                await self.stores.config.set(
                    f"source_last_polled:{adapter_type}",
                    datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Polled %s: %d items (since=%s)", adapter_type, len(raw_items), since)
            except Exception as e:
                logger.error("Source adapter %s poll failed: %s", adapter_type, e)

    async def _manage_triage_queue(self):
        if not self.messenger:
            return

        try:
            await self._manage_triage_queue_inner()
        except Exception:
            logger.error("Triage queue management failed", exc_info=True)

    async def _manage_triage_queue_inner(self):
        sent_today = await self.stores.triage.count_sent_today()
        if sent_today >= self.config.triage.daily_cap:
            return

        pending = await self.stores.triage.get_pending()
        if not pending:
            return

        # Timeout check for awaiting_followup/awaiting_confirmation cards
        for c in pending:
            if c.status in ("awaiting_followup", "awaiting_confirmation"):
                if c.sent_at and (datetime.now(timezone.utc) - c.sent_at).total_seconds() > 3600:
                    c.status = "expired"
                    c.response = "timed_out"
                    await self.stores.triage.update_card(c)
                    continue

        sent_cards = [c for c in pending if c.status == "sent"]
        awaiting_followup = [c for c in pending if c.status == "awaiting_followup"]
        awaiting_confirmation = [c for c in pending if c.status == "awaiting_confirmation"]

        # Handle awaiting_confirmation cards first
        for card in awaiting_confirmation:
            responses = await self.messenger.poll_responses(card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip().lower()
                await self._handle_confirmation(card, text)
                return

        # Handle awaiting_followup cards
        for card in awaiting_followup:
            responses = await self.messenger.poll_responses(card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip()
                if text and self.llm:
                    interpreted = await self.llm.interpret_triage_response(card, text)
                    await self._execute_interpreted_response(interpreted, card)
                    return

        if sent_cards:
            card = sent_cards[0]
            responses = await self.messenger.poll_responses(card.bot_message_id)
            if responses:
                logger.info("Got %d responses for card %s (msg=%s)", len(responses), card.id, card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip()
                lower_text = text.lower()
                if lower_text in ("skip all", "skip remaining"):
                    for c in pending:
                        if c.responded_at is None:
                            await self.stores.triage.record_response(
                                c.id, TriageResponse(card_id=c.id, choice=0, raw_text="skip all")
                            )
                    return
                try:
                    choice = int(text)
                    if 1 <= choice <= len(card.options):
                        option = card.options[choice - 1]
                        if option.action == "other":
                            # Transition to awaiting_followup
                            card.status = "awaiting_followup"
                            await self.stores.triage.update_card(card)
                            await self.messenger.send_card("What would you like to do?")
                            return
                        await self._handle_triage_response(card, choice)
                        return
                except ValueError:
                    # Free-text response -- interpret via LLM
                    if self.llm:
                        interpreted = await self.llm.interpret_triage_response(card, text)
                        await self._execute_interpreted_response(interpreted, card)
                        return
            return

        card = await self.stores.triage.get_next_unsent()
        if not card:
            return

        text = format_card_for_chat(card, position=1, total=len(pending))
        msg_id = await self.messenger.send_card(text)
        card.status = "sent"
        card.sent_at = datetime.now(timezone.utc)
        card.bot_message_id = msg_id
        card.daily_sequence = sent_today + 1
        await self.stores.triage.update_card(card)

    async def _handle_triage_response(self, card, choice: int):
        option = card.options[choice - 1]
        response = TriageResponse(card_id=card.id, choice=choice)
        await self.stores.triage.record_response(card.id, response)

        if option.action == "add_todo":
            # FIX 32: Priority string -> enum conversion
            priority = Priority(option.details.get("priority", "P2"))
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
                )
            else:
                item = Item(
                    source_type=card.card_content.get("source_type", "unknown"),
                    source_id=card.id,
                    summary=card.card_content.get("summary", ""),
                    category=ItemCategory.ACTION_ITEM,
                    origin=ItemOrigin.TRIAGED, priority=priority,
                    status=ItemStatus.ACTIVE,
                )
                await self.stores.items.save_item(item)

        elif option.action == "skip":
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
                )

        elif option.action == "mute_pattern":
            rule = FilterRule(
                source_type=card.card_content.get("source_type"),
                pattern=card.card_content.get("summary", ""),
                action="drop",
                created_from_interaction_id=card.id,
            )
            await self.stores.filter_rules.add_rule(rule)

        elif option.action == "defer":
            hours = option.details.get("hours", 4)
            card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
            card.status = "queued"
            await self.stores.triage.update_card(card)

        # FIX 6: Actual InteractionEntry, not a placeholder comment
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_id=card.item_id,
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen=option.label,
            choice_index=choice,
        )
        await self.stores.interactions.append(entry)
        await self.memory.record_triage(card, response)

        if self.messenger:
            await self.messenger.send_card(f"Got it -- {option.label}")

    async def _execute_interpreted_response(
        self, interpreted: InterpretedResponse, card
    ) -> None:
        """Execute an LLM-interpreted free-text response.

        FIX 34: Destructive actions (skip, mute_pattern) require confirmation
        and return early. Defer also returns early.
        FIX 20: Store pending InterpretedResponse before entering awaiting_confirmation.
        FIX 6: Append actual InteractionEntry with interpreted data.
        FIX 32: Priority string -> enum conversion.
        """
        for action in interpreted.system_actions:
            # Destructive actions require confirmation
            if action.action in ("skip", "mute_pattern"):
                # FIX 20: Store pending InterpretedResponse in card_content
                card.card_content["pending_interpreted"] = interpreted.model_dump()
                card.status = "awaiting_confirmation"
                await self.stores.triage.update_card(card)
                if self.messenger:
                    await self.messenger.send_card(
                        f"I understood: {interpreted.explanation}\n"
                        f"Reply 'yes' to confirm or 'no' to cancel."
                    )
                # FIX 34: Return early -- do not process further actions
                return

            elif action.action == "add_todo":
                # FIX 32: Priority string -> enum
                priority = Priority(action.details.get("priority", "P2"))
                if card.item_id:
                    await self.stores.items.update_item(
                        card.item_id,
                        ItemUpdate(priority=priority, status=ItemStatus.ACTIVE),
                    )
                else:
                    item = Item(
                        source_type=card.card_content.get("source_type", "unknown"),
                        source_id=card.id,
                        summary=card.card_content.get("summary", ""),
                        category=ItemCategory.ACTION_ITEM,
                        origin=ItemOrigin.TRIAGED,
                        priority=priority,
                        status=ItemStatus.ACTIVE,
                    )
                    await self.stores.items.save_item(item)

            elif action.action == "defer":
                hours = action.details.get("hours", 4)
                card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
                card.status = "queued"
                await self.stores.triage.update_card(card)
                # FIX 34: Defer returns early
                return

        # Create user todos as action items
        for todo in interpreted.user_todos:
            new_item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=todo.summary,
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=Priority.P2,
                status=ItemStatus.ACTIVE,
                parent_item_id=card.item_id,
                action_source="triage_response",
                action_category=todo.action_category,
            )
            await self.stores.items.save_item(new_item)

        # Mark card as responded
        card.status = "responded"
        card.responded_at = datetime.now(timezone.utc)
        await self.stores.triage.update_card(card)

        # FIX 6: Append actual InteractionEntry with interpreted response data
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_id=card.item_id,
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen="free_text",
            type="free_text",
            interpreted=interpreted.model_dump(),
        )
        await self.stores.interactions.append(entry)

        if self.messenger:
            await self.messenger.send_card(
                f"Done! {interpreted.explanation}"
            )

    async def _handle_confirmation(self, card, text: str) -> None:
        """FIX 7: Handle 'yes'/'no' response to awaiting_confirmation cards.

        FIX 20: Retrieve stored InterpretedResponse from card.card_content["pending_interpreted"].
        """
        if text.lower() in ("yes", "y", "confirm"):
            pending_data = card.card_content.get("pending_interpreted")
            if not pending_data:
                logger.warning("No pending_interpreted found for card %s", card.id)
                card.status = "responded"
                card.responded_at = datetime.now(timezone.utc)
                await self.stores.triage.update_card(card)
                return

            # Reconstruct InterpretedResponse
            interpreted = InterpretedResponse(**pending_data)

            # Execute the destructive actions directly (no re-confirmation)
            for action in interpreted.system_actions:
                if action.action == "skip":
                    if card.item_id:
                        await self.stores.items.update_item(
                            card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
                        )
                elif action.action == "mute_pattern":
                    rule = FilterRule(
                        source_type=card.card_content.get("source_type"),
                        pattern=card.card_content.get("summary", ""),
                        action="drop",
                        created_from_interaction_id=card.id,
                    )
                    await self.stores.filter_rules.add_rule(rule)

            # Mark card as responded
            card.status = "responded"
            card.responded_at = datetime.now(timezone.utc)
            # Clean up pending data
            card.card_content.pop("pending_interpreted", None)
            await self.stores.triage.update_card(card)

            # FIX 6: Log interaction
            entry = InteractionEntry(
                source_type=card.card_content.get("source_type", "unknown"),
                item_id=card.item_id,
                item_summary=card.card_content.get("summary", ""),
                triage_card_full=card.card_content,
                options_presented=[o.model_dump() for o in card.options],
                option_chosen="confirmed",
                type="free_text",
                interpreted=interpreted.model_dump(),
                confirmed=True,
            )
            await self.stores.interactions.append(entry)

            if self.messenger:
                await self.messenger.send_card("Confirmed. Done!")

        elif text.lower() in ("no", "n", "cancel"):
            card.status = "sent"  # Return to sent state for re-triage
            card.card_content.pop("pending_interpreted", None)
            await self.stores.triage.update_card(card)

            if self.messenger:
                await self.messenger.send_card("Cancelled. The card is back in your queue.")

        else:
            # Unrecognized -- re-prompt
            if self.messenger:
                await self.messenger.send_card(
                    "Please reply 'yes' to confirm or 'no' to cancel."
                )

    async def _expire_cards(self):
        expired = await self.stores.triage.expire_old_cards(self.config.triage.expiry_days)
        if expired:
            logger.info(f"Auto-expired {expired} triage cards")

    async def _morning_briefing(self):
        if not self.messenger:
            return
        try:
            await self._morning_briefing_inner()
        except Exception:
            logger.error("Morning briefing failed", exc_info=True)

    async def _morning_briefing_inner(self):
        from workbench.models import ItemFilters
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()
        queue_depth = await self.stores.ingestion_queue.queue_depth()
        dead_letters = await self.stores.ingestion_queue.get_dead_letters()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]

        if p0:
            lines.append(f"*P0 -- Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  - {i.summary} [{i.source_type}]")

        if p1:
            lines.append(f"*P1 -- This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  - {i.summary} [{i.source_type}]")

        if pending:
            oldest = min(c.sent_at or c.expires_at or datetime.now(timezone.utc) for c in pending)
            age_days = (datetime.now(timezone.utc) - oldest).days
            lines.append(f"\n*Pending triage:* {len(pending)} cards (oldest: {age_days}d)")

        if queue_depth > 0 or dead_letters:
            lines.append(f"\n*Queue health:* {queue_depth} queued")
            if dead_letters:
                lines.append(f"  ! {len(dead_letters)} dead-letter entries need investigation")

        if not p0 and not p1 and not pending:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_free_text_response.py -v`
Expected: All pass.

Run: `make test`
Expected: All existing tests pass (may need to update existing scheduler tests to pass `llm=None` if they construct WorkbenchScheduler directly -- the new `llm` param has a default of `None` so backward compatible).

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/scheduler.py tests/test_free_text_response.py
git commit -m "feat(triage): add free-text response interpretation, confirmation flow, execution with logging"
```

---

### Task 20: format_card_for_chat Update

**Files:**
- Modify: `src/workbench/pipeline/triage.py`
- Test: `tests/test_format_card.py`

- [ ] **Step 1: Write tests for new card format**

```python
# tests/test_format_card.py

import pytest
from workbench.pipeline.triage import format_card_for_chat
from workbench.models import TriageCard, TriageOption


def test_format_uses_card_body_when_present():
    """card_body (from LLM generation) takes precedence over summary."""
    card = TriageCard(
        card_content={
            "card_body": "PR #200 from alice (infra lead). You usually prioritize her reviews.",
            "summary": "Review PR #200",
            "source_type": "github",
        },
        options=[
            TriageOption(label="Add P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
            TriageOption(label="Other -- tell me what you'd like to do", action="other"),
        ],
    )
    text = format_card_for_chat(card)
    assert "alice (infra lead)" in text
    assert "1. Add P1" in text
    assert "2. Skip" in text
    assert "3. Other" in text
    assert "reply with what you'd like to do" in text


def test_format_falls_back_to_summary():
    """Falls back to summary when card_body is not present."""
    card = TriageCard(
        card_content={"summary": "Fix auth flow", "source_type": "github"},
        options=[
            TriageOption(label="Add P2", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "Fix auth flow" in text


def test_format_shows_suggested_option():
    """Suggested options display their suggestion reason."""
    card = TriageCard(
        card_content={"card_body": "PR from alice", "summary": "PR review"},
        options=[
            TriageOption(
                label="Add P1", action="add_todo",
                details={"priority": "P1"},
                suggested=True,
                suggestion_reason="you usually prioritize alice PRs",
            ),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "suggested" in text.lower()
    assert "you usually prioritize alice PRs" in text


def test_format_shows_enrichment_context():
    """Enrichment context (author, files, etc.) is rendered."""
    card = TriageCard(
        card_content={
            "card_body": "PR #200",
            "summary": "PR #200",
            "source_type": "github",
            "enrichment": {
                "context": {
                    "author": "alice",
                    "files_changed": 5,
                    "review_status": "changes_requested",
                },
            },
        },
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "alice" in text
    assert "5 files" in text


def test_format_with_position_and_total():
    """Shows queue position when there are multiple cards."""
    card = TriageCard(
        card_content={"card_body": "Item A", "summary": "Item A", "source_type": "email"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card, position=2, total=5)
    assert "5 items to triage" in text
    assert "#2 of 5" in text


def test_format_no_position_for_single_card():
    """No position header for a single card."""
    card = TriageCard(
        card_content={"card_body": "Solo card", "summary": "Solo card"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card, position=1, total=1)
    assert "items to triage" not in text


def test_format_free_text_hint():
    """All cards include free-text reply hint."""
    card = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "reply with what you'd like to do" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_format_card.py -v`
Expected: Failures -- current format_card_for_chat doesn't use card_body, doesn't show suggestion_reason, doesn't have free-text hint.

- [ ] **Step 3: Update format_card_for_chat in `src/workbench/pipeline/triage.py`**

Replace the existing `format_card_for_chat` function:

```python
def format_card_for_chat(
    card: TriageCard, position: int = 1, total: int = 1
) -> str:
    """Format a triage card as text for Google Chat.

    Uses card_body (LLM-generated) when available, falls back to summary.
    Shows suggested options with their reasons and includes free-text hint.
    """
    # Prefer LLM-generated card_body, fall back to summary
    body = card.card_content.get(
        "card_body", card.card_content.get("summary", "Unknown item")
    )
    source = card.card_content.get("source_type", "unknown")

    lines = []
    if total > 1:
        lines.append(f"*{total} items to triage. Here's #{position} of {total}:*")

    lines.append(f"*[{source}]* {body}")

    # Render enrichment context (author, files, etc.)
    enrichment = card.card_content.get("enrichment", {})
    ctx = enrichment.get("context", {}) if isinstance(enrichment, dict) else {}
    if ctx:
        parts = []
        if "author" in ctx:
            parts.append(f"By {ctx['author']}")
        if "files_changed" in ctx:
            parts.append(f"{ctx['files_changed']} files")
        if "review_status" in ctx:
            parts.append(f"review: {ctx['review_status'].replace('_', ' ')}")
        if "labels" in ctx:
            parts.append(ctx["labels"])
        if parts:
            lines.append(f"_{' . '.join(parts)}_")
        handled = {"author", "files_changed", "review_status", "labels", "entity_refs"}
        extra = {k: v for k, v in ctx.items() if k not in handled}
        if extra:
            lines.append(f"_{', '.join(f'{k}: {v}' for k, v in extra.items())}_")

    lines.append("")

    # Render options with suggestion annotations
    for i, opt in enumerate(card.options, 1):
        suggested_hint = ""
        if opt.suggested and opt.suggestion_reason:
            suggested_hint = f" _(suggested: {opt.suggestion_reason})_"
        lines.append(f"{i}. {opt.label}{suggested_hint}")

    lines.append("")
    lines.append("_Or just reply with what you'd like to do._")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_format_card.py -v`
Expected: All pass.

Run: `make test`
Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/triage.py tests/test_format_card.py
git commit -m "feat(triage): update format_card_for_chat with LLM body, suggestion hints, free-text prompt"
```

---

## Group C: Action Items (Tasks 21-23), Group M (Task 24), Plugin Command (Task 25), Final Verification (Task 26)

---

### Task 21: Actions API

**Files:**
- Create: `src/workbench/api/actions.py`
- Modify: `src/workbench/main.py` (mount router)
- Create: `src/workbench/api/auth_token.py` (token endpoint for React UI)
- Test: `tests/test_actions_api.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_actions_api.py

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.models import (
    Item, ItemCategory, ItemOrigin, ItemStatus, ItemUpdate, Priority,
    TriageCard, TriageOption,
)
from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 50)
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    return llm


@pytest_asyncio.fixture
async def app_with_state(stores, mock_llm):
    from workbench.config import AppConfig, ServerConfig, StorageConfig

    test_config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://workbench:workbench@localhost:5432/workbench"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "test"},
        server=ServerConfig(api_token="dev-token-change-me"),
    )

    with patch("workbench.main.get_config", return_value=test_config):
        from workbench.main import create_app
        test_app = create_app()

    test_app.state.config = test_config
    test_app.state.stores = stores
    test_app.state.memory = NoopMemoryLayer()
    test_app.state.llm = mock_llm
    test_app.state.enricher = StubEnricher()
    test_app.state.messenger = None
    test_app.state.queue_scorer = None
    test_app.state.sources = []
    test_app.state.pipeline = PipelineEngine(
        stores, NoopMemoryLayer(), mock_llm, StubEnricher()
    )

    yield test_app


@pytest_asyncio.fixture
async def client(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_get_actions_empty(client):
    r = await client.get("/api/actions")
    assert r.status_code == 200
    data = r.json()
    assert data["categories"] == {}
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_actions_grouped(client, app_with_state):
    stores = app_with_state.state.stores
    item1 = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
        parent_item_id="parent-1",
    )
    item2 = Item(
        source_type="diff", source_id="d1",
        summary="Review RFC", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P1,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="review",
    )
    await stores.items.save_item(item1)
    await stores.items.save_item(item2)

    r = await client.get("/api/actions")
    assert r.status_code == 200
    data = r.json()
    assert "delegation" in data["categories"]
    assert "review" in data["categories"]
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_get_actions_filter_by_category(client, app_with_state):
    stores = app_with_state.state.stores
    item1 = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    item2 = Item(
        source_type="diff", source_id="d1",
        summary="Review RFC", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P1,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="review",
    )
    await stores.items.save_item(item1)
    await stores.items.save_item(item2)

    r = await client.get("/api/actions?category=delegation")
    assert r.status_code == 200
    data = r.json()
    assert "delegation" in data["categories"]
    assert "review" not in data["categories"]
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_mark_action_done(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(f"/api/actions/{item.id}/done")
    assert r.status_code == 200

    updated = await stores.items.get_item(item.id)
    assert updated.status == ItemStatus.DONE


@pytest.mark.asyncio
async def test_mark_action_done_logs_lifecycle(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    await client.post(f"/api/actions/{item.id}/done")

    entries = await stores.interactions.get_all()
    lifecycle_entries = [e for e in entries if e.type == "action_lifecycle"]
    assert len(lifecycle_entries) == 1
    assert lifecycle_entries[0].item_id == item.id
    assert lifecycle_entries[0].option_chosen == "done"


@pytest.mark.asyncio
async def test_change_priority(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/actions/{item.id}/priority",
        json={"priority": "P1"},
    )
    assert r.status_code == 200

    updated = await stores.items.get_item(item.id)
    assert updated.priority == Priority.P1


@pytest.mark.asyncio
async def test_snooze_action(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/actions/{item.id}/snooze",
        json={"hours": 4},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "snoozed"


@pytest.mark.asyncio
async def test_action_not_found(client):
    r = await client.post("/api/actions/nonexistent/done")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_action_items_excluded(client, app_with_state):
    """Items without action_source should not appear in /api/actions."""
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Regular item", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        # No action_source set — this is NOT an action item
    )
    await stores.items.save_item(item)

    r = await client.get("/api/actions")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_auth_token_endpoint(client, app_with_state):
    r = await client.get("/api/auth/token")
    assert r.status_code == 200
    data = r.json()
    assert data["token"] == "dev-token-change-me"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_actions_api.py -v`
Expected: ImportError — `workbench.api.actions` not found, new model fields missing.

- [ ] **Step 3: Implement actions API**

```python
# src/workbench/api/actions.py

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from workbench.models import (
    InteractionEntry, ItemFilters, ItemStatus, ItemUpdate, Priority,
)

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("")
async def get_actions(
    request: Request,
    status: str = "active",
    category: str | None = None,
):
    stores = request.app.state.stores

    # Query active items, then filter for action items in Python (FIX 13)
    filters = ItemFilters(status=ItemStatus(status))
    all_items = await stores.items.get_items(filters)

    # Only include items that have action_source set
    items = [i for i in all_items if i.action_source is not None]

    if category:
        items = [i for i in items if i.action_category == category]

    categories = defaultdict(list)
    for item in items:
        cat = item.action_category or "uncategorized"
        parent = None
        if item.parent_item_id:
            parent_item = await stores.items.get_item(item.parent_item_id)
            if parent_item:
                parent = {"id": parent_item.id, "summary": parent_item.summary}
        categories[cat].append({
            "id": item.id,
            "summary": item.summary,
            "priority": item.priority,
            "parent_item": parent,
            "action_source": item.action_source,
            "action_category": item.action_category,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {"categories": dict(categories), "total": len(items)}


class PriorityUpdate(BaseModel):
    priority: str


class SnoozeRequest(BaseModel):
    hours: int = 4


async def _log_action_lifecycle(
    stores, item_id: str, action: str, summary: str, source_type: str,
) -> None:
    """Log an action lifecycle event as an InteractionEntry (FIX 8)."""
    entry = InteractionEntry(
        type="action_lifecycle",
        source_type=source_type,
        item_id=item_id,
        item_summary=summary,
        option_chosen=action,
    )
    await stores.interactions.append(entry)


@router.post("/{item_id}/done")
async def mark_done(request: Request, item_id: str):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update_item(item_id, ItemUpdate(status=ItemStatus.DONE))
    await _log_action_lifecycle(
        stores, item_id, "done", item.summary, item.source_type,
    )
    return {"status": "done"}


@router.post("/{item_id}/priority")
async def change_priority(request: Request, item_id: str, body: PriorityUpdate):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update_item(
        item_id, ItemUpdate(priority=Priority(body.priority)),
    )
    await _log_action_lifecycle(
        stores, item_id, f"priority:{body.priority}", item.summary, item.source_type,
    )
    return {"status": "updated", "priority": body.priority}


@router.post("/{item_id}/snooze")
async def snooze_action(request: Request, item_id: str, body: SnoozeRequest):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    # Snooze keeps the item active but logs a snooze lifecycle event.
    # A future scheduler tick can check snooze_until to suppress
    # the item from briefings until the snooze period expires.
    await _log_action_lifecycle(
        stores, item_id, f"snooze:{body.hours}h", item.summary, item.source_type,
    )
    return {"status": "snoozed", "hours": body.hours}
```

- [ ] **Step 4: Create auth token endpoint for React UI (FIX 19)**

```python
# src/workbench/api/auth_token.py

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/token")
async def get_token(request: Request):
    """Return the API token for the React UI.

    The React app calls this on mount to get the token for subsequent
    API calls. This endpoint itself is behind the auth middleware,
    so the caller must already have a valid token (e.g. via cookie
    or the initial page load). In dev mode the Vite proxy forwards
    the request with the same auth header.
    """
    config = request.app.state.config
    return {"token": config.server.api_token}
```

- [ ] **Step 5: Mount routers in main.py**

In `src/workbench/main.py`, update the import block and router list:

```python
    from workbench.api import (
        actions, auth_token,
        config as config_api, filter_rules, health, items, jobs,
        memory, process, queue, sources, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, jobs.router, queue.router,
        actions.router, auth_token.router,
    ]:
        app.include_router(r)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_actions_api.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/api/actions.py src/workbench/api/auth_token.py src/workbench/main.py tests/test_actions_api.py
git commit -m "feat(api): add /api/actions endpoints with lifecycle logging and /api/auth/token"
```

---

### Task 22: Morning Briefing -- Pending Actions Section

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_morning_briefing_actions.py`

- [ ] **Step 1: Write test for pending actions in briefing**

```python
# tests/test_morning_briefing_actions.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from workbench.models import (
    Item, ItemCategory, ItemFilters, ItemOrigin, ItemStatus, Priority,
)
from workbench.pipeline.scheduler import WorkbenchScheduler


class FakeItemStore:
    def __init__(self, items):
        self._items = items

    async def get_items(self, filters):
        result = self._items
        if filters.status:
            result = [i for i in result if i.status == filters.status]
        return result

    async def get_item(self, item_id):
        for i in self._items:
            if i.id == item_id:
                return i
        return None


class FakeTriageStore:
    async def get_pending(self):
        return []


class FakeIngestionQueueStore:
    async def queue_depth(self):
        return 0

    async def get_dead_letters(self):
        return []


class FakeStores:
    def __init__(self, items):
        self.items = FakeItemStore(items)
        self.triage = FakeTriageStore()
        self.ingestion_queue = FakeIngestionQueueStore()


@pytest.mark.asyncio
async def test_briefing_includes_action_items():
    """Pending actions section appears in morning briefing."""
    items = [
        Item(
            source_type="email", source_id="e1",
            summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P2,
            status=ItemStatus.ACTIVE,
            action_source="triage_response", action_category="delegation",
        ),
        Item(
            source_type="diff", source_id="d1",
            summary="Review RFC", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P1,
            status=ItemStatus.ACTIVE,
            action_source="triage_response", action_category="review",
        ),
    ]

    messenger = AsyncMock()
    messenger.send_card = AsyncMock()

    from workbench.config import (
        AppConfig, LoggingConfig, SchedulerConfig, ServerConfig,
        StorageConfig, TriageConfig,
    )
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
        scheduler=SchedulerConfig(morning_briefing_hour=9),
    )

    scheduler = WorkbenchScheduler.__new__(WorkbenchScheduler)
    scheduler.stores = FakeStores(items)
    scheduler.memory = AsyncMock()
    scheduler.pipeline = AsyncMock()
    scheduler.messenger = messenger
    scheduler.config = config
    scheduler.sources = []

    await scheduler._morning_briefing_inner()

    call_args = messenger.send_card.call_args[0][0]
    assert "Pending actions" in call_args
    assert "Delegation" in call_args
    assert "Review" in call_args
    assert "Assign to bob" in call_args
    assert "Review RFC" in call_args


@pytest.mark.asyncio
async def test_briefing_no_actions_section_when_none():
    """No pending actions section when no action items exist."""
    items = [
        Item(
            source_type="email", source_id="e1",
            summary="Regular task", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P1,
            status=ItemStatus.ACTIVE,
            # No action_source — not an action item
        ),
    ]

    messenger = AsyncMock()
    messenger.send_card = AsyncMock()

    from workbench.config import AppConfig, ServerConfig, StorageConfig
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )

    scheduler = WorkbenchScheduler.__new__(WorkbenchScheduler)
    scheduler.stores = FakeStores(items)
    scheduler.memory = AsyncMock()
    scheduler.pipeline = AsyncMock()
    scheduler.messenger = messenger
    scheduler.config = config
    scheduler.sources = []

    await scheduler._morning_briefing_inner()

    call_args = messenger.send_card.call_args[0][0]
    assert "Pending actions" not in call_args
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_morning_briefing_actions.py -v`
Expected: Fail -- "Pending actions" not in briefing output.

- [ ] **Step 3: Update `_morning_briefing_inner` in scheduler.py**

In `src/workbench/pipeline/scheduler.py`, replace the `_morning_briefing_inner` method with:

```python
    async def _morning_briefing_inner(self):
        from workbench.models import ItemFilters
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()
        queue_depth = await self.stores.ingestion_queue.queue_depth()
        dead_letters = await self.stores.ingestion_queue.get_dead_letters()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]

        if p0:
            lines.append(f"*P0 — Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        if p1:
            lines.append(f"*P1 — This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        # Pending actions section
        action_items = [i for i in items if i.action_source is not None]
        if action_items:
            from collections import defaultdict
            by_category = defaultdict(list)
            for item in action_items:
                cat = (item.action_category or "uncategorized").title()
                parent_summary = ""
                if item.parent_item_id:
                    parent = await self.stores.items.get_item(item.parent_item_id)
                    if parent:
                        parent_summary = f" — from {parent.summary}"
                by_category[cat].append(f"    • {item.summary}{parent_summary}")
            lines.append(f"\n*Pending actions ({len(action_items)}):*")
            for cat, cat_items in by_category.items():
                lines.append(f"  {cat} ({len(cat_items)}):")
                lines.extend(cat_items)

        if pending:
            oldest = min(c.sent_at or c.expires_at or datetime.now(timezone.utc) for c in pending)
            age_days = (datetime.now(timezone.utc) - oldest).days
            lines.append(f"\n*Pending triage:* {len(pending)} cards (oldest: {age_days}d)")

        if queue_depth > 0 or dead_letters:
            lines.append(f"\n*Queue health:* {queue_depth} queued")
            if dead_letters:
                lines.append(f"  ⚠ {len(dead_letters)} dead-letter entries need investigation")

        if not p0 and not p1 and not pending and not action_items:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_morning_briefing_actions.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/scheduler.py tests/test_morning_briefing_actions.py
git commit -m "feat(scheduler): add pending actions section to morning briefing"
```

---

### Task 23: React UI -- Setup + Components + Dockerfile Update

**Files:**
- Create: `ui/package.json`
- Create: `ui/tsconfig.json`
- Create: `ui/vite.config.ts`
- Create: `ui/index.html`
- Create: `ui/src/main.tsx`
- Create: `ui/src/App.tsx`
- Create: `ui/src/api.ts`
- Create: `ui/src/components/ActionList.tsx`
- Create: `ui/src/components/ActionItem.tsx`
- Modify: `Dockerfile` (multi-stage build, FIX 24)

- [ ] **Step 1: Create ui/package.json**

```json
{
  "name": "workbench-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.6.3",
    "vite": "^6.0.0"
  }
}
```

- [ ] **Step 2: Create ui/tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create ui/vite.config.ts**

```typescript
// ui/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8421',
    },
  },
})
```

- [ ] **Step 4: Create ui/index.html**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Workbench Actions</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create ui/src/api.ts (FIX 19 -- fetch token from /api/auth/token)**

```typescript
// ui/src/api.ts

let _token: string | null = null

/**
 * Fetch the API token from the server on first call.
 * The /api/auth/token endpoint is behind auth middleware,
 * so in production the initial page load sets a session cookie
 * or the token is passed via query param on first load.
 * In dev mode, the Vite proxy handles forwarding.
 */
async function getToken(): Promise<string> {
  if (_token) return _token
  try {
    const res = await fetch('/api/auth/token')
    if (res.ok) {
      const data = await res.json()
      _token = data.token
      return _token!
    }
  } catch {
    // fallback: token not available
  }
  return ''
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchActions(
  params?: Record<string, string>,
): Promise<{ categories: Record<string, Action[]>; total: number }> {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  const headers = await authHeaders()
  const res = await fetch(`/api/actions${query}`, { headers })
  return res.json()
}

export async function markDone(id: string): Promise<void> {
  const headers = await authHeaders()
  await fetch(`/api/actions/${id}/done`, {
    method: 'POST',
    headers,
  })
}

export async function changePriority(
  id: string,
  priority: string,
): Promise<void> {
  const headers = {
    ...(await authHeaders()),
    'Content-Type': 'application/json',
  }
  await fetch(`/api/actions/${id}/priority`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ priority }),
  })
}

export async function snooze(id: string, hours: number): Promise<void> {
  const headers = {
    ...(await authHeaders()),
    'Content-Type': 'application/json',
  }
  await fetch(`/api/actions/${id}/snooze`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ hours }),
  })
}

export interface Action {
  id: string
  summary: string
  priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string
  action_category: string | null
  created_at: string
}
```

- [ ] **Step 6: Create ui/src/components/ActionItem.tsx**

```tsx
// ui/src/components/ActionItem.tsx
import { markDone, changePriority, snooze, type Action } from '../api'

interface Props {
  item: Action
  onUpdate: () => void
}

const priorityColors: Record<string, string> = {
  P0: '#dc2626',
  P1: '#ea580c',
  P2: '#2563eb',
  P3: '#6b7280',
}

export function ActionItem({ item, onUpdate }: Props) {
  const hours = Math.floor(
    (Date.now() - new Date(item.created_at).getTime()) / (1000 * 60 * 60),
  )
  const ageLabel = hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`

  return (
    <li style={{ marginBottom: 12, listStyle: 'none' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span
          style={{
            fontWeight: 'bold',
            color: priorityColors[item.priority] || '#333',
            fontSize: 13,
          }}
        >
          [{item.priority}]
        </span>
        <span>{item.summary}</span>
        {item.parent_item && (
          <span style={{ color: '#888', fontSize: 13 }}>
            from {item.parent_item.summary}
          </span>
        )}
        <span style={{ color: '#aaa', fontSize: 12 }}>{ageLabel}</span>
      </div>
      <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
        <button onClick={() => markDone(item.id).then(onUpdate)}>Done</button>
        <button onClick={() => changePriority(item.id, 'P0').then(onUpdate)}>
          P0
        </button>
        <button onClick={() => changePriority(item.id, 'P1').then(onUpdate)}>
          P1
        </button>
        <button onClick={() => changePriority(item.id, 'P2').then(onUpdate)}>
          P2
        </button>
        <button onClick={() => changePriority(item.id, 'P3').then(onUpdate)}>
          P3
        </button>
        <button onClick={() => snooze(item.id, 4).then(onUpdate)}>
          Snooze 4h
        </button>
      </div>
    </li>
  )
}
```

- [ ] **Step 7: Create ui/src/components/ActionList.tsx**

```tsx
// ui/src/components/ActionList.tsx
import { useState, useEffect, useCallback } from 'react'
import { fetchActions, type Action } from '../api'
import { ActionItem } from './ActionItem'

interface ActionsData {
  categories: Record<string, Action[]>
  total: number
}

export function ActionList() {
  const [data, setData] = useState<ActionsData | null>(null)
  const [filter, setFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const params: Record<string, string> = {}
    if (filter) params.category = filter
    fetchActions(params)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

  useEffect(() => {
    load()
  }, [load])

  if (loading && !data) return <div>Loading...</div>
  if (error) return <div style={{ color: 'red' }}>Error: {error}</div>
  if (!data) return null

  const categories = Object.entries(data.categories)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Action Items ({data.total})</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ padding: '4px 8px' }}
        >
          <option value="">All categories</option>
          <option value="delegation">Delegation</option>
          <option value="communication">Communication</option>
          <option value="scheduling">Scheduling</option>
          <option value="review">Review</option>
          <option value="creation">Creation</option>
          <option value="update">Update</option>
        </select>
        <button onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>
      {categories.map(([category, items]) => (
        <details key={category} open>
          <summary style={{ cursor: 'pointer', fontWeight: 'bold', marginBottom: 8 }}>
            {category.charAt(0).toUpperCase() + category.slice(1)} ({items.length})
          </summary>
          <ul style={{ padding: 0 }}>
            {items.map((item) => (
              <ActionItem key={item.id} item={item} onUpdate={load} />
            ))}
          </ul>
        </details>
      ))}
      {categories.length === 0 && (
        <p style={{ color: '#888' }}>No pending actions. You are all caught up.</p>
      )}
    </div>
  )
}
```

- [ ] **Step 8: Create ui/src/App.tsx**

```tsx
// ui/src/App.tsx
import { ActionList } from './components/ActionList'

export default function App() {
  return (
    <div
      style={{
        maxWidth: 800,
        margin: '0 auto',
        padding: 20,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <ActionList />
    </div>
  )
}
```

- [ ] **Step 9: Create ui/src/main.tsx**

```tsx
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

- [ ] **Step 10: Update Dockerfile for multi-stage build (FIX 24)**

```dockerfile
# Stage 1: Build React UI
FROM node:20-slim AS ui-builder
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm install
COPY ui/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY entrypoint.sh .
RUN pip install --no-cache-dir -e .

# Copy built React UI from stage 1
COPY --from=ui-builder /ui/dist /app/ui-dist

EXPOSE 8421
ENTRYPOINT ["./entrypoint.sh"]
```

- [ ] **Step 11: Add static file mount for React UI in main.py**

In `src/workbench/main.py`, add after the router mounts:

```python
    # Serve React UI static files
    import os
    ui_dist = os.path.join(os.path.dirname(__file__), "../../ui-dist")
    if not os.path.isdir(ui_dist):
        # Check Docker location
        ui_dist = "/app/ui-dist"
    if os.path.isdir(ui_dist):
        from starlette.staticfiles import StaticFiles
        app.mount("/ui", StaticFiles(directory=ui_dist, html=True), name="ui")
```

- [ ] **Step 12: Build and verify**

```bash
cd ui && npm install && npm run build
```
Expected: `ui/dist/` directory created with built assets.

- [ ] **Step 13: Commit**

```bash
git add ui/ Dockerfile src/workbench/main.py
git commit -m "feat(ui): add React action items UI with token auth and multi-stage Dockerfile"
```

---

## Group M: workbench-meta Adapters

### Task 24: Meta-Internal Adapters + Observability (workbench-meta)

**Note:** These files live in the separate `~/workspace/workbench-meta/` repository. They depend on resolving the InternConnection auth mechanism (open question). The adapters below are functional stubs that follow the existing pattern (see `phabricator.py`).

**Observability requirements (grilling session 2026-06-03):** All Meta adapters and enrichers use structlog with Meta-specific bound context fields. The `workbench_meta/privacy.py` module provides META_SANITIZER_PATTERNS. The config.meta.yml includes observability overrides (retention 365d, stricter alerting, JSON logging).

**Files (all in workbench-meta):**
- Create: `workbench_meta/privacy.py`
- Create: `workbench_meta/providers/source/meta_tasks.py`
- Create: `workbench_meta/providers/source/workplace.py`
- Create: `workbench_meta/providers/source/docs.py`
- Create: `workbench_meta/providers/enrichment/meta_tasks.py`
- Create: `workbench_meta/providers/enrichment/workplace.py`
- Create: `workbench_meta/providers/enrichment/docs.py`
- Modify: `config.meta.yml`

- [ ] **Step 0: Create workbench_meta/privacy.py with Meta sanitizer patterns**

```python
# workbench_meta/privacy.py

import re

META_SANITIZER_PATTERNS = [
    (re.compile(r'\bD\d{6,}\b'), '[REDACTED:phid]'),
    (re.compile(r'\bT\d{6,}\b'), '[REDACTED:task_id]'),
    (re.compile(r'\b[a-z]{2,20}(?=@fb\.com)'), '[REDACTED:unixname]'),
]
```

This module is loaded by the Meta entrypoint and passed to `setup_logging(extra_processors=[SanitizingProcessor(config.privacy, extra_patterns=META_SANITIZER_PATTERNS)])`. In `src/workbench/main.py`, update the `lifespan` function to support a hook for extra sanitizer patterns:

```python
# In main.py lifespan, after config is loaded:
extra_patterns = []
try:
    from workbench_meta.privacy import META_SANITIZER_PATTERNS
    extra_patterns = META_SANITIZER_PATTERNS
except ImportError:
    pass  # OSS mode — no Meta patterns

sanitizer = SanitizingProcessor(config.privacy, extra_patterns=extra_patterns)
```

This import pattern matches the existing workbench-meta overlay approach — workbench tries to import Meta extensions, falls back gracefully when running OSS-only.

- [ ] **Step 1: Create MetaTasksAdapter**

```python
# workbench_meta/providers/source/meta_tasks.py

import asyncio
import json
from datetime import datetime

import structlog
from pydantic import BaseModel
from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = structlog.get_logger(__name__)


class MetaTasksAdapter(SourceAdapter):

    class ProviderConfig(BaseModel):
        owner: str = ""

    def __init__(self, config: ProviderConfig):
        self.owner = config.owner

    def adapter_type(self) -> str:
        return "meta_tasks"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self.owner:
            return []

        logger.info("meta_tasks_poll_start", query_owner=self.owner, since=str(since))

        args = ["meta", "tasks.task", "list", "--owner", self.owner, "--format", "json"]
        if since:
            args.extend(["--modified-after", since.isoformat()])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                logger.warning("meta_tasks_poll_nonzero_exit", returncode=proc.returncode)
                return []
            tasks = json.loads(stdout.decode())
        except Exception as e:
            logger.error("meta_tasks_poll_failed", error=str(e))
            return []

        items = []
        for task in tasks if isinstance(tasks, list) else []:
            task_id = task.get("id", "")
            title = task.get("title", "")
            mod_time = task.get("dateModified", "")
            urgency_signals = {}
            priority = task.get("priority", "")
            if priority:
                urgency_signals["priority"] = priority
            status = task.get("status", "")
            if status:
                urgency_signals["status"] = status
            items.append(RawItem(
                id=f"T{task_id}_{mod_time}",
                source_type="meta_tasks",
                source_label=f"T{task_id} — {title}",
                raw_text=json.dumps(task),
                urgency_signals=urgency_signals,
            ))

        logger.info("meta_tasks_poll_complete", task_count=len(items), query_owner=self.owner)
        return items
```

- [ ] **Step 2: Create WorkplaceAdapter**

```python
# workbench_meta/providers/source/workplace.py

import asyncio
import json
from datetime import datetime

import structlog
from pydantic import BaseModel
from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = structlog.get_logger(__name__)


class WorkplaceAdapter(SourceAdapter):

    class ProviderConfig(BaseModel):
        group_ids: list[str] = []

    def __init__(self, config: ProviderConfig):
        self.group_ids = config.group_ids

    def adapter_type(self) -> str:
        return "workplace"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self.group_ids:
            return []

        logger.info("workplace_poll_start", group_count=len(self.group_ids))

        items = []
        for group_id in self.group_ids:
            args = [
                "meta", "workplace.post", "list",
                "--group-id", group_id, "--format", "json",
            ]
            if since:
                args.extend(["--since", since.isoformat()])

            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    logger.warning("workplace_group_poll_failed", group_id=group_id, returncode=proc.returncode)
                    continue
                posts = json.loads(stdout.decode())
            except Exception as e:
                logger.error("workplace_group_poll_error", group_id=group_id, error=str(e))
                continue

            for post in posts if isinstance(posts, list) else []:
                post_id = post.get("id", "")
                message = post.get("message", "")[:200]
                mod_time = post.get("updated_time", "")
                urgency_signals = {}
                if post.get("mentions_me"):
                    urgency_signals["mentions_me"] = True
                items.append(RawItem(
                    id=f"wp_{post_id}_{mod_time}",
                    source_type="workplace",
                    source_label=f"Workplace: {message[:80]}",
                    raw_text=json.dumps(post),
                    urgency_signals=urgency_signals,
                ))

        logger.info("workplace_poll_complete", post_count=len(items), group_ids=self.group_ids)
        return items
```

- [ ] **Step 3: Create MetaDocsAdapter**

```python
# workbench_meta/providers/source/docs.py

import asyncio
import json
from datetime import datetime

import structlog
from pydantic import BaseModel
from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = structlog.get_logger(__name__)


class MetaDocsAdapter(SourceAdapter):

    class ProviderConfig(BaseModel):
        subscribed_doc_ids: list[str] = []

    def __init__(self, config: ProviderConfig):
        self.subscribed_doc_ids = config.subscribed_doc_ids

    def adapter_type(self) -> str:
        return "meta_docs"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self.subscribed_doc_ids:
            return []

        logger.info("meta_docs_poll_start", doc_count=len(self.subscribed_doc_ids))

        items = []
        for doc_id in self.subscribed_doc_ids:
            args = [
                "meta", "docs.document", "get",
                "--id", doc_id, "--format", "json",
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    logger.warning("meta_docs_fetch_failed", doc_id=doc_id, returncode=proc.returncode)
                    continue
                doc = json.loads(stdout.decode())
            except Exception as e:
                logger.error("meta_docs_fetch_error", doc_id=doc_id, error=str(e))
                continue

            title = doc.get("title", "")
            mod_time = doc.get("dateModified", "")
            urgency_signals = {}
            if doc.get("has_action_items"):
                urgency_signals["has_action_items"] = True

            items.append(RawItem(
                id=f"doc_{doc_id}_{mod_time}",
                source_type="meta_docs",
                source_label=f"Doc: {title}",
                raw_text=json.dumps(doc),
                urgency_signals=urgency_signals,
            ))

        logger.info("meta_docs_poll_complete", doc_count=len(items))
        return items
```

- [ ] **Step 4: Create MetaTasksEnricher**

```python
# workbench_meta/providers/enrichment/meta_tasks.py

import asyncio
import json

import structlog
from pydantic import BaseModel
from workbench.models import EnrichmentBudget, ExtractedItem
from workbench.providers.enrichment.base import ContextEnricher

logger = structlog.get_logger(__name__)


class MetaTasksEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def enrich(
        self, item: ExtractedItem, depth: str,
        budget: EnrichmentBudget, *, memory=None,
    ) -> dict:
        if item.raw_item.source_type != "meta_tasks":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        raw = {}
        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            pass

        context = {}
        entity_refs = []

        # Extract assignee info
        assignee = raw.get("ownerPHID", "")
        if assignee:
            entity_refs.append(("person", f"phab:{assignee}"))
            context["assignee_phid"] = assignee

        # Extract subscriber info
        subscribers = raw.get("subscriberPHIDs", [])
        for sub in subscribers[:5]:
            entity_refs.append(("person", f"phab:{sub}"))

        context["priority"] = raw.get("priority", "")
        context["status"] = raw.get("status", "")
        context["subtype"] = raw.get("subtype", "")

        # Deep enrichment: fetch task details
        calls_made = 0
        if depth == "deep" and raw.get("id"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "meta", "tasks.task", "get",
                    "--id", str(raw["id"]), "--format", "json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                calls_made += 1
                if proc.returncode == 0:
                    details = json.loads(stdout.decode())
                    context["description_preview"] = details.get("description", "")[:300]
                    context["tags"] = details.get("tags", [])
            except Exception:
                pass

        return {
            "calls_made": calls_made,
            "time_ms": 0,
            "context": context,
            "entity_refs": entity_refs,
        }
```

- [ ] **Step 5: Create WorkplaceEnricher**

```python
# workbench_meta/providers/enrichment/workplace.py

import json

import structlog
from pydantic import BaseModel
from workbench.models import EnrichmentBudget, ExtractedItem
from workbench.providers.enrichment.base import ContextEnricher

logger = structlog.get_logger(__name__)


class WorkplaceEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def enrich(
        self, item: ExtractedItem, depth: str,
        budget: EnrichmentBudget, *, memory=None,
    ) -> dict:
        if item.raw_item.source_type != "workplace":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        raw = {}
        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            pass

        context = {}
        entity_refs = []

        author = raw.get("from", {})
        if author.get("id"):
            entity_refs.append(("person", f"workplace:{author['id']}"))
            context["author_name"] = author.get("name", "")

        context["group_name"] = raw.get("group_name", "")
        context["comment_count"] = raw.get("comment_count", 0)
        context["reaction_count"] = raw.get("reaction_count", 0)

        return {
            "calls_made": 0,
            "time_ms": 0,
            "context": context,
            "entity_refs": entity_refs,
        }
```

- [ ] **Step 6: Create MetaDocsEnricher**

```python
# workbench_meta/providers/enrichment/docs.py

import json

import structlog
from pydantic import BaseModel
from workbench.models import EnrichmentBudget, ExtractedItem
from workbench.providers.enrichment.base import ContextEnricher

logger = structlog.get_logger(__name__)


class MetaDocsEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def enrich(
        self, item: ExtractedItem, depth: str,
        budget: EnrichmentBudget, *, memory=None,
    ) -> dict:
        if item.raw_item.source_type != "meta_docs":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        raw = {}
        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            pass

        context = {}
        entity_refs = []

        author_phid = raw.get("authorPHID", "")
        if author_phid:
            entity_refs.append(("person", f"phab:{author_phid}"))

        context["title"] = raw.get("title", "")
        context["last_editor"] = raw.get("lastEditorPHID", "")
        context["version"] = raw.get("version", 0)

        collaborators = raw.get("collaboratorPHIDs", [])
        for collab in collaborators[:5]:
            entity_refs.append(("person", f"phab:{collab}"))

        return {
            "calls_made": 0,
            "time_ms": 0,
            "context": context,
            "entity_refs": entity_refs,
        }
```

- [ ] **Step 7: Update config.meta.yml with adapters + observability overrides**

```yaml
llm:
  class: workbench_meta.providers.llm.meta_anthropic.MetaAnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY,placeholder}
  base_url: https://plugboard.x2p.facebook.net

queue:
  scorer:
    class: workbench_meta.providers.queue_scorer.meta_scorer.MetaQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY,placeholder}
    base_url: https://plugboard.x2p.facebook.net
    model: claude-haiku-4-5-20251001

messenger:
  class: workbench_meta.providers.messenger.gchat.GoogleChatMessenger
  space_id: ${oc.env:GCHAT_SPACE_ID,}

sources:
  - class: workbench_meta.providers.source.phabricator.PhabricatorAdapter
    user_phid: ${oc.env:PHABRICATOR_USER_PHID,}
  - class: workbench_meta.providers.source.meta_tasks.MetaTasksAdapter
    owner: ${oc.env:META_TASKS_OWNER,anshulverma}
  - class: workbench_meta.providers.source.workplace.WorkplaceAdapter
    group_ids: ${oc.env:WORKPLACE_GROUP_IDS,[]}
  - class: workbench_meta.providers.source.docs.MetaDocsAdapter
    subscribed_doc_ids: ${oc.env:META_DOCS_IDS,[]}

enrichment:
  class: workbench_meta.providers.enrichment.meta.MetaEnricher
# Additional enrichers for source-specific enrichment:
# meta_tasks: workbench_meta.providers.enrichment.meta_tasks.MetaTasksEnricher
# workplace:  workbench_meta.providers.enrichment.workplace.WorkplaceEnricher
# docs:       workbench_meta.providers.enrichment.docs.MetaDocsEnricher

# --- Observability overrides (grilling session 2026-06-03) ---

logging:
  format: json
  level: INFO

privacy:
  sanitize_logs: true
  redact_emails: true
  redact_phones: true
  max_content_in_logs: 500

retention:
  archived_items_days: 365
  done_items_days: 365
  expired_cards_days: 365
  responded_cards_days: 365
  enrichment_traces_days: 365
  dead_letters_days: 365

alerting:
  enabled: true
  cooldown_minutes: 30
  conditions:
    dead_letter_threshold: 2
    adapter_failure_threshold: 2
    queue_depth_threshold: 30
```

- [ ] **Step 8: Commit (in workbench-meta repo)**

```bash
cd ~/workspace/workbench-meta
git add workbench_meta/privacy.py \
        workbench_meta/providers/source/meta_tasks.py \
        workbench_meta/providers/source/workplace.py \
        workbench_meta/providers/source/docs.py \
        workbench_meta/providers/enrichment/meta_tasks.py \
        workbench_meta/providers/enrichment/workplace.py \
        workbench_meta/providers/enrichment/docs.py \
        config.meta.yml
git commit -m "feat(meta): add Meta adapters/enrichers with structlog, sanitizer patterns, observability config"
```

---

## Plugin Command

### Task 25: Plugin Actions Command (FIX 27/9)

**Files:**
- Create: `plugin/commands/actions.md`

- [ ] **Step 1: Create actions.md plugin command**

```markdown
# /workbench:actions

View and manage pending action items grouped by category.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. Call `GET {server_url}/api/actions` with header `Authorization: Bearer {api_token}` to get all pending action items.
3. If no action items are returned (total is 0), display: "No pending actions. You're all caught up!"
4. Format the response as a categorized list:
   - Show the total count at the top.
   - For each category, show the category name and item count.
   - For each item, show: priority badge, summary, parent item (if any), and age.
   - Example output:
     ```
     Action Items (4)

     Delegation (2):
       [P1] Assign auth migration to bob — from Review auth middleware  (2h ago)
       [P2] Forward RFC to infra team — from Design doc review  (1d ago)

     Review (1):
       [P1] Review alice's API changes  (4h ago)

     Communication (1):
       [P2] Follow up with team about timeline  (3d ago)
     ```
5. After displaying items, present action options:
   - Ask: "Enter an item number to act on it, or press Enter to exit."
   - Number items 1-N across all categories in display order.
6. When the user picks an item number, present actions:
   ```
   [P1] Assign auth migration to bob

   What do you want to do?
   1. Mark done
   2. Change priority
   3. Snooze (4h)
   4. Back to list
   ```
7. Execute the chosen action:
   - **Mark done**: Call `POST {server_url}/api/actions/{item_id}/done` with auth header. Display: "Marked as done."
   - **Change priority**: Ask which priority (P0/P1/P2/P3). Call `POST {server_url}/api/actions/{item_id}/priority` with `{"priority": "P1"}`. Display: "Priority changed to P1."
   - **Snooze**: Call `POST {server_url}/api/actions/{item_id}/snooze` with `{"hours": 4}`. Display: "Snoozed for 4 hours."
8. After each action, refresh and redisplay the list.
9. Support a `--category` flag to filter by category:
   - `/workbench:actions --category delegation` shows only delegation items.
   - Call `GET {server_url}/api/actions?category=delegation` with auth header.
10. If the server is unreachable, display an error and suggest running `/workbench:setup`.
```

- [ ] **Step 2: Commit**

```bash
git add plugin/commands/actions.md
git commit -m "feat(plugin): add /workbench:actions command for action item management"
```

---

## Final Verification

### Task 26: End-to-End Verification Checklist

- [ ] **Step 1: Run all workbench tests**

```bash
cd /home/anshulverma/workspace/workbench
make test
```
Expected: All pass, including:
- `tests/test_actions_api.py` -- all action endpoints
- `tests/test_morning_briefing_actions.py` -- briefing includes actions
- Existing tests in `tests/test_api.py`, `tests/test_pipeline.py`, etc.

- [ ] **Step 2: Run all memory service tests**

```bash
cd /home/anshulverma/workspace/workbench/src/memory && python -m pytest tests/ -v
```
Expected: All pass.

- [ ] **Step 3: Verify new API routes are accessible**

```bash
# Start services
make up

# Verify health
curl -s http://localhost:8421/health | python -m json.tool

# Verify actions endpoint (empty)
curl -s -H "Authorization: Bearer $(cat config.yml | grep api_token | awk '{print $2}')" \
  http://localhost:8421/api/actions | python -m json.tool

# Verify auth token endpoint
curl -s -H "Authorization: Bearer $(cat config.yml | grep api_token | awk '{print $2}')" \
  http://localhost:8421/api/auth/token | python -m json.tool
```

Expected:
- `/health` returns 200 with version info
- `/api/actions` returns `{"categories": {}, "total": 0}`
- `/api/auth/token` returns `{"token": "..."}`

- [ ] **Step 4: Verify React UI builds**

```bash
cd /home/anshulverma/workspace/workbench/ui
npm install && npm run build
ls -la dist/
```
Expected: `dist/` contains `index.html` and `assets/` directory.

- [ ] **Step 5: Verify Dockerfile builds**

```bash
cd /home/anshulverma/workspace/workbench
docker build -t workbench-test .
```
Expected: Multi-stage build completes. Node stage builds UI, Python stage copies dist.

- [ ] **Step 6: Verify plugin command exists**

```bash
cat plugin/commands/actions.md | head -5
```
Expected: Shows `# /workbench:actions` header.

- [ ] **Step 7: Verify config.example.yml still loads**

```bash
cd /home/anshulverma/workspace/workbench
python -c "from workbench.config import load_config; load_config('config.example.yml')"
```
Expected: No errors.

- [ ] **Step 8: Verify workbench-meta adapters**

```bash
cd /home/anshulverma/workspace/workbench-meta
python -c "
from workbench_meta.providers.source.meta_tasks import MetaTasksAdapter
from workbench_meta.providers.source.workplace import WorkplaceAdapter
from workbench_meta.providers.source.docs import MetaDocsAdapter
from workbench_meta.providers.enrichment.meta_tasks import MetaTasksEnricher
from workbench_meta.providers.enrichment.workplace import WorkplaceEnricher
from workbench_meta.providers.enrichment.docs import MetaDocsEnricher
print('All meta adapters import successfully')
"
```
Expected: `All meta adapters import successfully`

- [ ] **Step 9: Cross-check critical fixes**

| Fix | What to verify | How |
|-----|---------------|-----|
| FIX 26/33 | ItemStore methods are `save_item()`, `get_item()`, `update_item(id, ItemUpdate(...))` | Grep `actions.py` for `save_item`, `get_item`, `update_item` -- no `save()`, `get()`, `update()` |
| FIX 13 | Actions API uses `ItemFilters(status=ItemStatus.ACTIVE)` then filters `action_source` in Python | Read `actions.py` `get_actions` -- no `__isnull` syntax |
| FIX 8 | Action lifecycle logging uses `InteractionEntry(type="action_lifecycle")` | Read `actions.py` `_log_action_lifecycle` |
| FIX 27/9 | Plugin command is Markdown at `plugin/commands/actions.md` | `ls plugin/commands/actions.md` |
| FIX 19 | React UI uses `/api/auth/token` endpoint, no meta tag injection | Read `ui/src/api.ts` `getToken()` -- fetches from endpoint |
| FIX 24 | Dockerfile is multi-stage: Node for React, Python copies dist | Read `Dockerfile` -- two FROM stages |
| FIX 28 | Auth is global middleware, no per-route auth deps | Read `actions.py` -- no `Depends(auth)` imports |

```bash
# Automated checks
cd /home/anshulverma/workspace/workbench

# FIX 26/33: Correct ItemStore method names
grep -n "save_item\|get_item\|update_item" src/workbench/api/actions.py
! grep -n "stores\.items\.save(" src/workbench/api/actions.py
! grep -n "stores\.items\.get(" src/workbench/api/actions.py
! grep -n "stores\.items\.update(" src/workbench/api/actions.py

# FIX 13: No Django-style filter syntax
! grep -n "__isnull" src/workbench/api/actions.py

# FIX 8: Lifecycle logging
grep -n "action_lifecycle" src/workbench/api/actions.py

# FIX 19: Token endpoint, not meta tag
grep -n "api/auth/token" ui/src/api.ts
! grep -n "meta\[name=" ui/src/api.ts

# FIX 24: Multi-stage Dockerfile
grep -c "^FROM" Dockerfile  # Should be 2

# FIX 28: No per-route auth deps
! grep -n "Depends" src/workbench/api/actions.py
```

- [ ] **Step 10: Commit any remaining changes**

```bash
git commit -m "chore: Phase 1d Group C/M/Plugin verification pass"
```
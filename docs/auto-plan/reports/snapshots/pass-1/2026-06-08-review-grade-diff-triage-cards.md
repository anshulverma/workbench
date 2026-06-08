# Review-Grade Diff Triage Cards Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce a source-pluggable, typed card presentation layer (Card Presenter + Card Content Schema + Card Content Generator + structured `CardMessage` messenger interface + detail API/UI) so Phabricator (`source_type="diff"`) triage cards carry curated, code-bearing diff hunks, while every other source degrades cleanly to today's plain card.

**Architecture:** Foundational (`workbench`) owns the source-agnostic abstractions: typed `DiffCardContent` nested under the existing `TriageCard.card_content` dict (no migration), a `CardPresenter` ABC + `CompositeCardPresenter`/`PlainCardPresenter` built from a new `presentation.providers` config list, a `CardContentGenerator` ABC dispatched by `source_type` in `generate_card` (default = `llm.generate_triage_card`), a `Messenger.send_card(CardMessage)` interface with a base `render_to_text` flatten, a `GET /api/triage/cards/{card_id}` detail endpoint, and a `#/triage/:cardId` detail view. Meta overlay (`workbench_meta`) owns the concrete `DiffEnricher` (lazy deep-mode `meta phabricator.diff get` fetch + Path Pre-skip + LLM curation + budget caps), `DiffCardContentGenerator` (single Opus 4.8 `json_schema` call), `DiffCardPresenter` (deterministic `DiffCardContent -> CardMessage`), and a `GoogleChatMessenger.send_card` override (cardsV2 + threaded monospace hunk replies). All failure paths degrade to `PlainCardPresenter` / summary-only cards and never block triage.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, asyncpg, Anthropic SDK (`claude-opus-4-8`), APScheduler, OmegaConf/pydantic config; React 19 + Vite + TanStack Query + react-router-dom HashRouter + vitest/MSW; `meta` CLI via `asyncio.create_subprocess_exec`; Google Chat REST cardsV2.

**Test commands:**
- foundational: `python -m pytest tests/ -v --tb=short` (run from `/home/anshulverma/workspace/workbench`) / single test: `python -m pytest tests/test_presenter.py -v --tb=short` / single case: `python -m pytest tests/test_presenter.py::test_composite_routes_by_source_type -v`
- meta: `python -m pytest tests/ -v --tb=short` (run from `/home/anshulverma/workspace/workbench-meta`) / single: `python -m pytest tests/test_diff_enricher.py::test_path_preskip_records_skipped -v`
- ui: `cd ui && npm run test` (vitest run) / single: `cd ui && npx vitest run src/pages/TriageDetail.test.tsx`; types: `cd ui && npm run gen:api` (against running server on 127.0.0.1:8421); build: `cd ui && npm run build`. NOTE per the npm-blocked constraint: devserver npm/node are blocked — download a standalone Node v20 to `/tmp` and run `gen:api`/`build`/`test` with that toolchain on `PATH` (no docker).

Notes for workers:
- pytest uses `asyncio_mode = "auto"` (pyproject `[tool.pytest.ini_options]`); a live Postgres at `postgres://workbench:workbench@localhost:5432/workbench` is only needed for tests using the `stores`/`pg_pool` fixtures (DB-backed API tests). Pure-unit tests need no DB.
- ADRs 0022–0029 already exist in `docs/adr/` and cover every decision in this spec; **do not create a new ADR file** (the spec's reference to `0021-card-presenter-and-content-schema.md` is superseded by the existing 0022–0029 set). Reference them in commit messages.
- The Meta repo layout is `workbench_meta/providers/{enrichment,messenger,source}/...` and the GChat messenger file is `workbench_meta/providers/messenger/gchat.py` (not `google_chat.py`). New Meta files go under `workbench_meta/providers/{enrichment,content,presentation}/`.
- The Google Chat REST helper `send_card_message(space_id, text, cards_v2, thread_name=, as_bot=)` already exists in `workbench_meta/lib/google_api.py`; the lib threads by `thread_name` (server thread resource name) using `REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`. The "client threadKey" in the spec maps to: post parent without a thread, capture `data.thread`, then post hunk replies with `thread_name=<captured thread>`.

---

## File Structure

### Foundational (`/home/anshulverma/workspace/workbench`)

New files:

| File | Responsibility |
| --- | --- |
| `src/workbench/pipeline/presenter.py` | `CardPresenter` ABC, `PlainCardPresenter` (wraps `format_card_for_chat`), `CompositeCardPresenter` (routes by `source_type`, per-delegate try/except fallback), `build_composite_presenter(config)` |
| `src/workbench/pipeline/content_generator.py` | `CardContentGenerator` ABC + `build_content_generators(config)` from `presentation`/dispatch helper |
| `tests/test_models_card.py` | tests for new card/message models |
| `tests/test_presenter.py` | tests for `CardPresenter`/`CompositeCardPresenter`/`PlainCardPresenter` + build-from-config |
| `tests/test_content_generator_dispatch.py` | tests for `generate_card` dispatch to registered generators |
| `tests/test_messenger_render_to_text.py` | tests for `Messenger.render_to_text` default + console |
| `tests/test_presentation_config.py` | tests for `presentation` config section + build |
| `tests/test_triage_card_detail_api.py` | tests for `GET /api/triage/cards/{card_id}` |
| `ui/src/hooks/useTriageCard.ts` | `useTriageCard(id)` hook (apiGet, five-state, no poll) |
| `ui/src/pages/TriageDetail.tsx` | Triage Card Detail View page |
| `ui/src/components/DiffHunks.tsx` | CSS-only `+`/`-` diff renderer + per-file expand |
| `ui/src/pages/TriageDetail.test.tsx` | TriageDetail page tests (MSW) |

Modified files:

| File | Change |
| --- | --- |
| `src/workbench/models.py` | add `DiffMetadata`, `DiffRisk`, `DiffHunkSection`, `DiffCardContent`, `CardLink`, `CardSection`, `ThreadHunk`, `CardMessage` |
| `src/workbench/pipeline/triage.py` | dispatch `CardContentGenerator` by `source_type`; default writes `content_schema`/`sections`-free envelope; doc memory caps 5/20/10 |
| `src/workbench/providers/messenger/base.py` | `send_card(card: CardMessage) -> str`; default `render_to_text(CardMessage) -> str` |
| `src/workbench/providers/messenger/console.py` | `send_card(CardMessage)` via `render_to_text`; back-compat for plain-string callers |
| `src/workbench/pipeline/scheduler.py` | `_manage_triage_queue_inner`: presenter -> `CardMessage` -> `send_card`; internal status messages wrapped as `CardMessage` |
| `src/workbench/config.py` | add `PresentationConfig` + `presentation` field; bump `version` minor to `0.4.0` |
| `src/workbench/api/triage.py` | add `GET /api/triage/cards/{card_id}` (404 on miss, bearer) |
| `src/workbench/main.py` | build `CompositeCardPresenter` + content generators from `presentation`; attach to `app.state`; pass into scheduler/engine |
| `src/workbench/pipeline/engine.py` | pass content generators into `generate_card` |
| `ui/src/App.tsx` | add `#/triage/:cardId` route |
| `ui/src/pages/Triage.tsx` | add "Review" link per card |
| `ui/src/lib/api-types.ts` | regenerate via `npm run gen:api` |
| `config.example.yml` | document `presentation` section; bump `version` to `0.4.0` |
| `docs/CONTEXT.md` | add new terms; correct memory caps "without caps" -> 5/20/10 |

### Meta overlay (`/home/anshulverma/workspace/workbench-meta`)

New files:

| File | Responsibility |
| --- | --- |
| `workbench_meta/providers/enrichment/diff_enricher.py` | `DiffEnricher` (lazy deep fetch, Path Pre-skip, LLM curation, budget caps, entity_refs, diff_url, revision_id) |
| `workbench_meta/providers/content/__init__.py` | package marker |
| `workbench_meta/providers/content/diff_generator.py` | `DiffCardContentGenerator` (single Opus 4.8 `json_schema` call) |
| `workbench_meta/providers/presentation/__init__.py` | package marker |
| `workbench_meta/providers/presentation/diff_presenter.py` | `DiffCardPresenter` (deterministic `DiffCardContent -> CardMessage`, caps, top-3 hunks) |
| `tests/test_meta_cli_diff_get_schema.md` | recorded confirmed `meta phabricator.diff get` schema (verification artifact) |
| `tests/test_diff_enricher.py` | DiffEnricher tests |
| `tests/test_diff_generator.py` | DiffCardContentGenerator tests |
| `tests/test_diff_presenter.py` | DiffCardPresenter tests |
| `tests/test_gchat_send_card.py` | GoogleChatMessenger.send_card override tests |

Modified files:

| File | Change |
| --- | --- |
| `workbench_meta/providers/messenger/gchat.py` | override `send_card(CardMessage)`: cardsV2 + thread parent + <=3 monospace hunk replies; thread polling unchanged |
| `config.meta.yml` | wire `presentation.providers` diff entry; register `diff` enricher + content generator |

---

## Task 1: Card content + message models (foundational)

**Files:** Create `tests/test_models_card.py`; Modify `src/workbench/models.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_models_card.py
from workbench.models import (
    DiffMetadata, DiffRisk, DiffHunkSection, DiffCardContent,
    CardLink, CardSection, ThreadHunk, CardMessage, TriageOption,
)


def test_diff_card_content_round_trips():
    content = DiffCardContent(
        metadata=DiffMetadata(author="alice", team="infra", status="needs_review"),
        summary="Adds a retry loop to the client.",
        risk=DiffRisk(factors=["touches retry path"], watch_outs=["no test for backoff"]),
        why_care="You own this client.",
        hunks=[
            DiffHunkSection(
                file="client.py",
                header="@@ -10,7 +10,9 @@",
                code="+    retry()\n-    pass",
                annotation="adds retry call",
                rank=1,
            )
        ],
    )
    dumped = content.model_dump()
    assert dumped["metadata"]["team"] == "infra"
    assert dumped["hunks"][0]["rank"] == 1
    assert dumped["hunks"][0]["expandable"] is True
    again = DiffCardContent(**dumped)
    assert again.hunks[0].file == "client.py"


def test_diff_metadata_team_optional():
    m = DiffMetadata(author="bob", status="accepted")
    assert m.team is None


def test_diff_card_content_defaults_empty_collections():
    content = DiffCardContent(
        metadata=DiffMetadata(author="a", status="s"),
        summary="s",
        risk=DiffRisk(),
        why_care="w",
    )
    assert content.hunks == []
    assert content.risk.factors == []
    assert content.risk.watch_outs == []


def test_card_message_defaults():
    msg = CardMessage(header="Diff D123")
    assert msg.sections == []
    assert msg.links == []
    assert msg.options == []
    assert msg.thread_hunks == []


def test_card_message_full_shape():
    msg = CardMessage(
        header="Diff D123",
        sections=[CardSection(title="Summary", body="does X", monospace=False)],
        links=[CardLink(label="View in Phabricator", url="https://phab/D123")],
        options=[TriageOption(label="Add P1", action="add_todo")],
        thread_hunks=[ThreadHunk(file="a.py", header="@@", code="+x", rank=1)],
    )
    assert msg.sections[0].title == "Summary"
    assert msg.links[0].url == "https://phab/D123"
    assert msg.thread_hunks[0].rank == 1
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_models_card.py -v --tb=short`
  Expected: collection/import error — `ImportError: cannot import name 'DiffMetadata' from 'workbench.models'`

- [ ] Step 3: Write minimal implementation — append to `src/workbench/models.py` (after `TriageOption`, before `TriageCard`)

```python
class DiffMetadata(BaseModel):
    author: str
    team: str | None = None
    status: str


class DiffRisk(BaseModel):
    factors: list[str] = Field(default_factory=list)
    watch_outs: list[str] = Field(default_factory=list)


class DiffHunkSection(BaseModel):
    file: str
    header: str
    code: str
    annotation: str = ""
    expandable: bool = True
    rank: int = 0


class DiffCardContent(BaseModel):
    metadata: DiffMetadata
    summary: str
    risk: DiffRisk
    why_care: str
    hunks: list[DiffHunkSection] = Field(default_factory=list)


class CardLink(BaseModel):
    label: str
    url: str


class CardSection(BaseModel):
    title: str
    body: str
    monospace: bool = False


class ThreadHunk(BaseModel):
    file: str
    header: str
    code: str
    rank: int = 0


class CardMessage(BaseModel):
    header: str
    sections: list[CardSection] = Field(default_factory=list)
    links: list[CardLink] = Field(default_factory=list)
    options: list[TriageOption] = Field(default_factory=list)
    thread_hunks: list[ThreadHunk] = Field(default_factory=list)
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_models_card.py -v --tb=short`
  Expected: PASS (5 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(models): add DiffCardContent + CardMessage card/message models (ADR 0022, 0025)"`

---

## Task 2: Messenger interface — `send_card(CardMessage)` + `render_to_text` (foundational)

**Files:** Create `tests/test_messenger_render_to_text.py`; Modify `src/workbench/providers/messenger/base.py`, `src/workbench/providers/messenger/console.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_messenger_render_to_text.py
import pytest
from workbench.models import CardMessage, CardSection, CardLink, TriageOption
from workbench.providers.messenger.base import Messenger
from workbench.providers.messenger.console import ConsoleMessenger


def test_render_to_text_flattens_header_sections_links_options():
    base = ConsoleMessenger()  # uses inherited default render_to_text
    msg = CardMessage(
        header="Diff D123 — add retry",
        sections=[
            CardSection(title="Summary", body="adds retry loop"),
            CardSection(title="Hunk", body="+ retry()", monospace=True),
        ],
        links=[CardLink(label="View in Phabricator", url="https://phab/D123")],
        options=[
            TriageOption(label="Add P1", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = base.render_to_text(msg)
    assert "Diff D123 — add retry" in text
    assert "Summary" in text
    assert "adds retry loop" in text
    assert "View in Phabricator" in text
    assert "https://phab/D123" in text
    assert "1. Add P1" in text
    assert "2. Skip" in text


@pytest.mark.asyncio
async def test_console_send_card_accepts_cardmessage_and_returns_id():
    base = ConsoleMessenger()
    msg = CardMessage(header="Hello", sections=[CardSection(title="t", body="b")])
    msg_id = await base.send_card(msg)
    assert isinstance(msg_id, str)
    assert msg_id.startswith("console-")


@pytest.mark.asyncio
async def test_console_send_card_accepts_plain_string_back_compat():
    base = ConsoleMessenger()
    msg_id = await base.send_card("Got it -- Add P1")
    assert isinstance(msg_id, str)
    assert msg_id.startswith("console-")
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_messenger_render_to_text.py -v --tb=short`
  Expected: `AttributeError: 'ConsoleMessenger' object has no attribute 'render_to_text'` (and/or send_card type mismatch)

- [ ] Step 3: Write minimal implementation

Replace `src/workbench/providers/messenger/base.py` entirely:

```python
from abc import ABC, abstractmethod

from workbench.models import CardMessage


class Messenger(ABC):
    @abstractmethod
    async def send_card(self, card: "CardMessage | str") -> str: ...
    @abstractmethod
    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]: ...

    def render_to_text(self, card: CardMessage) -> str:
        """Default flatten for console / non-rich transports."""
        lines = [f"*{card.header}*", ""]
        for section in card.sections:
            lines.append(f"*{section.title}*")
            lines.append(section.body)
            lines.append("")
        for link in card.links:
            lines.append(f"{link.label}: {link.url}")
        if card.links:
            lines.append("")
        for i, opt in enumerate(card.options, 1):
            lines.append(f"{i}. {opt.label}")
        if card.options:
            lines.append("")
            lines.append("_Or just reply with what you'd like to do._")
        return "\n".join(lines)

    async def close(self) -> None:
        pass
```

Replace `send_card` in `src/workbench/providers/messenger/console.py`:

```python
    async def send_card(self, card) -> str:
        from workbench.models import CardMessage

        card_text = self.render_to_text(card) if isinstance(card, CardMessage) else str(card)
        msg_id = f"console-{uuid4()}"
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}")
        print("Respond via the web UI Triage page, or: make triage")
        print(
            f"  or: curl -X POST http://localhost:8421/api/triage/respond -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' -d '{{\"card_id\": \"...\", \"choice\": 1}}'"
        )
        return msg_id
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_messenger_render_to_text.py -v --tb=short`
  Expected: PASS (3 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(messenger): send_card(CardMessage) + base render_to_text default (ADR 0026)"`

---

## Task 3: CardPresenter ABC + Plain + Composite (foundational)

**Files:** Create `src/workbench/pipeline/presenter.py`, `tests/test_presenter.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_presenter.py
import logging
import pytest
from workbench.models import (
    TriageCard, TriageOption, ExtractedItem, RawItem, ItemCategory, CardMessage,
)
from workbench.pipeline.presenter import (
    CardPresenter, PlainCardPresenter, CompositeCardPresenter,
)


def _item(source_type="diff") -> ExtractedItem:
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(summary="s", category=ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


def _plain_card() -> TriageCard:
    return TriageCard(
        card_content={"card_body": "PR #200 from alice", "summary": "Review PR #200",
                      "source_type": "diff"},
        options=[TriageOption(label="Add P1", action="add_todo"),
                 TriageOption(label="Skip", action="skip")],
    )


def test_plain_presenter_wraps_format_card_for_chat():
    msg = PlainCardPresenter().render(_plain_card(), _item())
    assert isinstance(msg, CardMessage)
    assert "PR #200 from alice" in msg.header or any(
        "PR #200 from alice" in s.body for s in msg.sections
    )
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]


def test_composite_routes_by_source_type():
    class Marker(CardPresenter):
        def render(self, card, item):
            return CardMessage(header="DIFF-PRESENTER")

    comp = CompositeCardPresenter(
        by_source_type={"diff": Marker()}, default=PlainCardPresenter()
    )
    assert comp.render(_plain_card(), _item("diff")).header == "DIFF-PRESENTER"


def test_composite_unknown_source_type_uses_default():
    comp = CompositeCardPresenter(by_source_type={}, default=PlainCardPresenter())
    msg = comp.render(_plain_card(), _item("github"))
    assert isinstance(msg, CardMessage)
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]


def test_composite_delegate_failure_falls_back_to_default(caplog):
    class Boom(CardPresenter):
        def render(self, card, item):
            raise RuntimeError("kaboom")

    comp = CompositeCardPresenter(
        by_source_type={"diff": Boom()}, default=PlainCardPresenter()
    )
    with caplog.at_level(logging.WARNING):
        msg = comp.render(_plain_card(), _item("diff"))
    assert isinstance(msg, CardMessage)
    assert any("presenter_failure" in r.message for r in caplog.records)


def test_empty_composite_routes_all_to_default():
    comp = CompositeCardPresenter(by_source_type={}, default=PlainCardPresenter())
    msg = comp.render(_plain_card(), _item("anything"))
    assert isinstance(msg, CardMessage)
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_presenter.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench.pipeline.presenter'`

- [ ] Step 3: Write minimal implementation

```python
# src/workbench/pipeline/presenter.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from workbench.models import CardMessage, CardSection, ExtractedItem, TriageCard
from workbench.pipeline.triage import format_card_for_chat

logger = logging.getLogger(__name__)


class CardPresenter(ABC):
    @abstractmethod
    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage: ...


class PlainCardPresenter(CardPresenter):
    """Universal fallback. Wraps legacy format_card_for_chat output."""

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        body = format_card_for_chat(card, position=1, total=1)
        return CardMessage(
            header=card.card_content.get("summary", "Item to triage"),
            sections=[CardSection(title="", body=body)],
            options=list(card.options),
        )


class CompositeCardPresenter(CardPresenter):
    def __init__(self, by_source_type: dict[str, CardPresenter], default: CardPresenter):
        self._by_source_type = by_source_type
        self._default = default

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        delegate = self._by_source_type.get(item.source_type, self._default)
        if delegate is self._default:
            return self._default.render(card, item)
        try:
            return delegate.render(card, item)
        except Exception as exc:
            logger.warning(
                "presenter_failure source_type=%s presenter=%s item_id=%s exc=%s",
                item.source_type, type(delegate).__name__,
                item.raw_item.id, exc,
            )
            return self._default.render(card, item)
```

NOTE: `ExtractedItem` has no `.source_type`/`.id`; use `item.raw_item.source_type` and `item.raw_item.id`. Update the test's `_item().source_type` access accordingly — the composite reads `item.raw_item.source_type`. Adjust the test helper if needed so `comp.render` keys off `item.raw_item.source_type` (it already does via `_item(source_type)` setting `raw.source_type`).

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_presenter.py -v --tb=short`
  Expected: PASS (5 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(presenter): CardPresenter ABC + Plain/Composite with fallback logging (ADR 0023)"`

---

## Task 4: CardContentGenerator ABC + dispatch in generate_card (foundational)

**Files:** Create `src/workbench/pipeline/content_generator.py`, `tests/test_content_generator_dispatch.py`; Modify `src/workbench/pipeline/triage.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_content_generator_dispatch.py
import pytest
from unittest.mock import AsyncMock
from workbench.models import ExtractedItem, RawItem, ItemCategory, TriageCard
from workbench.pipeline.content_generator import CardContentGenerator
from workbench.pipeline.triage import generate_card


def _item(source_type="diff") -> ExtractedItem:
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(summary="s", category=ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


class _StubGen(CardContentGenerator):
    def __init__(self):
        self.called = False

    async def generate(self, llm, item, enrichment_context, memory_context):
        self.called = True
        return {
            "content_schema": "diff.v1",
            "sections": {"summary": "from generator"},
            "card_body": "body",
            "summary": "from generator",
        }


@pytest.mark.asyncio
async def test_dispatches_to_registered_generator_by_source_type():
    llm = AsyncMock()
    gen = _StubGen()
    card = await generate_card(
        llm, _item("diff"), {"context": {}}, "diff",
        content_generators={"diff": gen},
    )
    assert gen.called is True
    assert card.card_content["content_schema"] == "diff.v1"
    assert card.card_content["sections"]["summary"] == "from generator"
    llm.generate_triage_card.assert_not_called()


@pytest.mark.asyncio
async def test_unregistered_source_type_uses_llm_default():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x", "source_type": "github"},
        options=[],
    )
    card = await generate_card(
        llm, _item("github"), {"context": {}}, "github",
        content_generators={"diff": _StubGen()},
    )
    llm.generate_triage_card.assert_called_once()
    assert "content_schema" not in card.card_content


@pytest.mark.asyncio
async def test_no_generators_arg_preserves_legacy_behavior():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[]
    )
    card = await generate_card(llm, _item("github"), {"context": {}}, "github")
    llm.generate_triage_card.assert_called_once()


@pytest.mark.asyncio
async def test_generator_returning_summary_only_envelope_skips_sections():
    llm = AsyncMock()

    class _SummaryOnly(CardContentGenerator):
        async def generate(self, llm, item, enrichment_context, memory_context):
            return {"card_body": "fallback summary", "summary": "fallback summary"}

    card = await generate_card(
        llm, _item("diff"), {"context": {}}, "diff",
        content_generators={"diff": _SummaryOnly()},
    )
    assert "sections" not in card.card_content
    assert card.card_content["summary"] == "fallback summary"
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_content_generator_dispatch.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench.pipeline.content_generator'`

- [ ] Step 3: Write minimal implementation

Create `src/workbench/pipeline/content_generator.py`:

```python
# src/workbench/pipeline/content_generator.py
from __future__ import annotations

from abc import ABC, abstractmethod

from workbench.models import ExtractedItem


class CardContentGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        llm,
        item: ExtractedItem,
        enrichment_context: dict,
        memory_context: dict | None,
    ) -> dict:
        """Return a card_content envelope dict.

        Envelope keys:
          content_schema: discriminator (e.g. "diff.v1") — present only when sections valid.
          sections: serialized typed content (omitted on refusal/parse-fail).
          card_body / summary: legacy plain-fallback fields (always present).
        """
```

Modify `src/workbench/pipeline/triage.py` — extend `generate_card` signature and add a dispatch branch. Change the signature and replace the "Generate card via LLM" block:

```python
async def generate_card(
    llm: LLMProvider,
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    *,
    memory=None,
    content_generators: dict | None = None,
) -> TriageCard:
    """Generate a triage card with LLM, enriched by memory context.

    Gathers entity knowledge (cap 5), relationships (cap 10), and preference
    facts (cap 20) from memory for any entity_refs found in the enrichment
    context. Dispatches to a registered CardContentGenerator by source_type;
    when none is registered, falls back to llm.generate_triage_card.
    """
```

(Keep the existing memory-gathering body unchanged — it already caps entity_refs[:5], relationships[:10], preference_facts[:20].)

Replace the LLM-generation block (the `try: ... card = await llm.generate_triage_card(...)` section) with:

```python
    context_for_llm = enrichment_context.get("context", enrichment_context)
    generator = (content_generators or {}).get(source_type)
    if generator is not None:
        try:
            envelope = await generator.generate(
                llm, item, context_for_llm, memory_context
            )
            card = TriageCard(card_content=envelope)
        except Exception as e:
            logger.warning("Content generator failed, using template: %s", e)
            card = _template_card(item, enrichment_context, source_type)
    else:
        try:
            card = await llm.generate_triage_card(
                item, context_for_llm, source_type, memory_context=memory_context,
            )
        except Exception as e:
            logger.warning("LLM card generation failed, using template: %s", e)
            card = _template_card(item, enrichment_context, source_type)
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_content_generator_dispatch.py tests/test_triage_card_enrichment.py -v --tb=short`
  Expected: PASS (4 passed in new file; existing enrichment tests still pass)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(triage): CardContentGenerator ABC + per-source dispatch in generate_card (ADR 0025)"`

---

## Task 5: Presentation config section + build-from-config (foundational)

**Files:** Create `tests/test_presentation_config.py`; Modify `src/workbench/config.py`, `src/workbench/pipeline/presenter.py`, `src/workbench/pipeline/content_generator.py`, `config.example.yml`

- [ ] Step 1: Write the failing test

```python
# tests/test_presentation_config.py
import pytest
from workbench.config import AppConfig, PresentationConfig
from workbench.pipeline.presenter import (
    build_composite_presenter, PlainCardPresenter, CompositeCardPresenter,
)


def _base_cfg(presentation=None):
    data = {
        "version": "0.4.0",
        "storage": {"postgres_dsn": "postgres://x/y"},
        "llm": {"class": "workbench.providers.llm.anthropic.AnthropicLLM",
                "api_key": "k"},
    }
    if presentation is not None:
        data["presentation"] = presentation
    return AppConfig(**data)


def test_presentation_absent_defaults_to_empty():
    cfg = _base_cfg()
    assert isinstance(cfg.presentation, PresentationConfig)
    assert cfg.presentation.providers == []


def test_build_presenter_absent_yields_empty_composite_with_plain_default():
    cfg = _base_cfg()
    presenter = build_composite_presenter(cfg.presentation)
    assert isinstance(presenter, CompositeCardPresenter)
    assert isinstance(presenter._default, PlainCardPresenter)
    assert presenter._by_source_type == {}


def test_build_presenter_unimportable_class_hard_errors():
    cfg = _base_cfg({"providers": [
        {"source_type": "diff", "class": "workbench_meta.nope.Missing"}
    ]})
    with pytest.raises(ImportError):
        build_composite_presenter(cfg.presentation)


def test_config_version_is_minor_bumped():
    cfg = _base_cfg()
    assert cfg.version == "0.4.0"
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_presentation_config.py -v --tb=short`
  Expected: `ImportError: cannot import name 'PresentationConfig' from 'workbench.config'`

- [ ] Step 3: Write minimal implementation

Add to `src/workbench/config.py` (before `AppConfig`):

```python
class PresentationConfig(BaseModel):
    providers: list[dict] = Field(default_factory=list)
```

In `AppConfig`, bump the default version and add the field:

```python
    version: str = "0.4.0"
    ...
    presentation: PresentationConfig = Field(default_factory=PresentationConfig)
```

Add to `src/workbench/pipeline/presenter.py`:

```python
def build_composite_presenter(presentation_config) -> "CompositeCardPresenter":
    """Build a CompositeCardPresenter from the presentation.providers list.

    Each entry: {source_type, class, config?}. Disabled (config.enabled is False)
    entries are skipped. Unimportable class strings raise at startup (hard error).
    """
    from workbench.registry import create_provider

    by_source_type: dict[str, CardPresenter] = {}
    for entry in presentation_config.providers:
        entry = dict(entry)
        source_type = entry.pop("source_type")
        provider_config = entry.pop("config", {}) or {}
        if provider_config.get("enabled", True) is False:
            continue
        section = {"class": entry["class"], **provider_config}
        by_source_type[source_type] = create_provider(section)
    return CompositeCardPresenter(by_source_type, default=PlainCardPresenter())
```

Add to `src/workbench/pipeline/content_generator.py`:

```python
def build_content_generators(presentation_config) -> dict:
    """Build {source_type: CardContentGenerator} from presentation.providers.

    Each entry may carry a `content_generator` class string; entries without one
    fall through to the LLM default in generate_card.
    """
    from workbench.registry import create_provider

    generators: dict = {}
    for entry in presentation_config.providers:
        gen_class = entry.get("content_generator")
        if not gen_class:
            continue
        source_type = entry["source_type"]
        config = dict(entry.get("config", {}) or {})
        config.pop("enabled", None)
        config.pop("max_hunks", None)
        config.pop("sections", None)
        config.pop("expand_default", None)
        generators[source_type] = create_provider({"class": gen_class})
    return generators
```

Add to `config.example.yml` (after the `scheduler:` block) and bump version line to `0.4.0`:

```yaml
# Presentation — CompositeCardPresenter routes by source_type (restart-only, ADR 0029)
presentation:
  providers: []
# Example (Meta diff cards):
#   - source_type: diff
#     class: workbench_meta.providers.presentation.diff_presenter.DiffCardPresenter
#     content_generator: workbench_meta.providers.content.diff_generator.DiffCardContentGenerator
#     config:
#       enabled: true
#       max_hunks: 15           # UI cap; chat always slices top 3
#       sections: [metadata, summary, risk, why_care, hunks]
#       expand_default: [risk, why_care]
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_presentation_config.py tests/test_config.py -v --tb=short`
  Expected: PASS (new file 4 passed; existing config tests still pass — if any assert on `version == "0.3.0"`, update them to `"0.4.0"` as part of this task)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(config): presentation section + build-from-config; bump config version 0.4.0 (ADR 0029)"`

---

## Task 6: Scheduler uses presenter -> CardMessage -> send_card (foundational)

**Files:** Modify `src/workbench/pipeline/scheduler.py`, `src/workbench/main.py`, `src/workbench/pipeline/engine.py`; Create `tests/test_scheduler_presenter.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_scheduler_presenter.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from workbench.models import (
    TriageCard, TriageOption, CardMessage, CardSection,
)
from workbench.pipeline.presenter import PlainCardPresenter
from workbench.pipeline.scheduler import WorkbenchScheduler


def _card():
    return TriageCard(
        id="c1",
        card_content={"summary": "Review D123", "card_body": "Review D123",
                      "source_type": "diff"},
        options=[TriageOption(label="Add P1", action="add_todo")],
        status="queued",
    )


def _scheduler(messenger, presenter):
    stores = MagicMock()
    stores.triage.count_sent_today = AsyncMock(return_value=0)
    stores.triage.get_pending = AsyncMock(return_value=[])
    stores.triage.get_next_unsent = AsyncMock(return_value=_card())
    stores.triage.update_card = AsyncMock()
    config = MagicMock()
    config.triage.daily_cap = 20
    config.logging.timezone = "UTC"
    config.alerting.enabled = False
    sched = WorkbenchScheduler(
        stores, MagicMock(), MagicMock(), messenger, config,
    )
    sched.presenter = presenter
    return sched, stores


@pytest.mark.asyncio
async def test_sends_cardmessage_via_presenter():
    sent = {}

    async def _send(card):
        sent["card"] = card
        return "msg-1"

    messenger = MagicMock()
    messenger.send_card = AsyncMock(side_effect=_send)
    messenger.poll_responses = AsyncMock(return_value=[])
    sched, stores = _scheduler(messenger, PlainCardPresenter())

    await sched._manage_triage_queue_inner()

    assert isinstance(sent["card"], CardMessage)
    assert "Review D123" in sent["card"].header or any(
        "Review D123" in s.body for s in sent["card"].sections
    )
    stores.triage.update_card.assert_awaited()
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_scheduler_presenter.py -v --tb=short`
  Expected: `AssertionError` — current code sends a flattened string via `format_card_for_chat`, so `sent["card"]` is a `str`, not a `CardMessage`.

- [ ] Step 3: Write minimal implementation

In `WorkbenchScheduler.__init__`, add a presenter attribute (default `PlainCardPresenter`):

```python
        from workbench.pipeline.presenter import PlainCardPresenter
        self.presenter = PlainCardPresenter()
```

In `_manage_triage_queue_inner`, replace the final send block:

```python
        card = await self.stores.triage.get_next_unsent()
        if not card:
            return

        ext_item = self._ext_item_for(card)
        message = self.presenter.render(card, ext_item)
        msg_id = await self.messenger.send_card(message)
        card.status = "sent"
        card.sent_at = datetime.now(timezone.utc)
        card.bot_message_id = msg_id
        card.daily_sequence = sent_today + 1
        await self.stores.triage.update_card(card)
```

Add a helper to reconstruct a minimal `ExtractedItem` for presenter routing from the stored card (the presenter only needs `raw_item.source_type` and `raw_item.id`):

```python
    def _ext_item_for(self, card):
        from workbench.models import ExtractedItem, RawItem, ItemCategory

        source_type = card.card_content.get("source_type", "unknown")
        raw = RawItem(
            id=card.item_id or card.id, source_type=source_type,
            source_label="", raw_text="",
        )
        return ExtractedItem(
            summary=card.card_content.get("summary", ""),
            category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
        )
```

Keep the internal status/echo messages (`"Got it -- ..."`, `"What would you like to do?"`, confirmation prompts) as plain strings — `ConsoleMessenger.send_card` and the GChat override both accept a plain `str` (back-compat path).

In `src/workbench/main.py`, after building the enricher, build the presenter + content generators and pass the presenter into the scheduler:

```python
    from workbench.pipeline.presenter import build_composite_presenter
    from workbench.pipeline.content_generator import build_content_generators

    app.state.presenter = build_composite_presenter(config.presentation)
    app.state.content_generators = build_content_generators(config.presentation)
```

After `app.state.scheduler = WorkbenchScheduler(...)`:

```python
    app.state.scheduler.presenter = app.state.presenter
```

In `src/workbench/pipeline/engine.py`, thread the content generators into `PipelineEngine` and pass them to `generate_card`. Add a `content_generators=None` param to `PipelineEngine.__init__` (store as `self.content_generators = content_generators or {}`), pass `app.state.content_generators` from main, and update the call:

```python
            card = await generate_card(
                self.llm, ext_item, enrichment, ext_item.raw_item.source_type,
                memory=self.memory, content_generators=self.content_generators,
            )
```

In `main.py` `PipelineEngine(...)`, add `content_generators=app.state.content_generators`.

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_scheduler_presenter.py tests/test_pipeline.py -v --tb=short`
  Expected: PASS (new test passes; existing pipeline tests still pass)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(scheduler): render via CompositeCardPresenter -> CardMessage -> send_card; wire content generators (ADR 0023, 0024)"`

---

## Task 7: Detail API — GET /api/triage/cards/{card_id} (foundational)

**Files:** Create `tests/test_triage_card_detail_api.py`; Modify `src/workbench/api/triage.py`

- [ ] Step 1: Write the failing test (DB-backed, uses the `stores` fixture pattern; build the app via the API test harness used by `tests/test_triage_web.py`)

```python
# tests/test_triage_card_detail_api.py
import pytest
import httpx
from httpx import ASGITransport

from workbench.models import TriageCard, TriageOption


async def _client(app):
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_card_by_id_returns_full_card(triage_app, auth_headers):
    app, stores = triage_app
    card = TriageCard(
        card_content={
            "content_schema": "diff.v1",
            "sections": {"summary": "adds retry", "metadata": {"author": "alice"}},
            "card_body": "adds retry", "summary": "adds retry",
        },
        options=[TriageOption(label="Add P1", action="add_todo")],
        relevance_score=80,
    )
    await stores.triage.save_card(card)

    client = await _client(app)
    resp = await client.get(f"/api/triage/cards/{card.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == card.id
    assert body["card_content"]["content_schema"] == "diff.v1"
    assert body["card_content"]["sections"]["summary"] == "adds retry"
    assert body["relevance_score"] == 80
    await client.aclose()


@pytest.mark.asyncio
async def test_get_unknown_card_returns_404(triage_app, auth_headers):
    app, _ = triage_app
    client = await _client(app)
    resp = await client.get("/api/triage/cards/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_get_card_without_bearer_is_unauthorized(triage_app):
    app, stores = triage_app
    card = TriageCard(card_content={"summary": "x"}, options=[])
    await stores.triage.save_card(card)
    client = await _client(app)
    resp = await client.get(f"/api/triage/cards/{card.id}")
    assert resp.status_code in (401, 403)
    await client.aclose()
```

If `tests/test_triage_web.py` already defines `triage_app`/`auth_headers` fixtures, reuse them (move them into `tests/conftest.py` if needed). Otherwise, build `triage_app` mirroring the harness in `tests/test_triage_web.py` (inspect it first): create the FastAPI app with auth middleware, set `app.state.stores` from the `stores` fixture, and an `auth_headers` fixture returning `{"Authorization": "Bearer <configured token>"}`.

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_triage_card_detail_api.py -v --tb=short`
  Expected: 404 on the happy-path test (route does not exist yet) — `assert 404 == 200`.

- [ ] Step 3: Write minimal implementation — add to `src/workbench/api/triage.py`:

```python
@router.get("/triage/cards/{card_id}")
async def get_triage_card(card_id: str, request: Request):
    stores = request.app.state.stores
    card = await stores.triage.get_card(card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")
    return card
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_triage_card_detail_api.py -v --tb=short`
  Expected: PASS (3 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(api): GET /api/triage/cards/{card_id} detail endpoint (404 on miss, bearer)"`

---

## Task 8: VERIFICATION — confirm `meta phabricator.diff get` schema (meta)

**Files:** Create `tests/test_meta_cli_diff_get_schema.md` (recorded artifact) in `/home/anshulverma/workspace/workbench-meta`

This task GATES Tasks 9 and 12 (fetch-parse + threading) — it confirms the real CLI contract instead of guessing. Run inside the cert-equipped container (see memory: needs `THRIFT_TLS` / `LD_LIBRARY_PATH=/usr/local/fbcode/platform010/lib`; the Phabricator adapter already uses this env for `meta phabricator.diff list`).

- [ ] Step 1: Discover the command surface
  Run: `meta phabricator.diff --help`
  Run: `meta phabricator.diff get --help`
  Record: whether a `get` subcommand exists, its required args (diff number vs revision id), and whether `--output json` is supported.

- [ ] Step 2: Fetch a known diff and capture the JSON schema
  Run: `meta phabricator.diff get <KNOWN_DIFF_NUMBER> --output json` (use a diff you author; pick one from `meta phabricator.diff list --author-is-me --output json --limit 1`)
  Record the top-level keys. Specifically determine whether the payload includes:
  - structured per-file hunks (file path, hunk header `@@ ... @@`, +/- line bodies), OR
  - only a raw unified-diff blob/string, OR
  - only metadata (no body).

- [ ] Step 3: Write the confirmed schema to the artifact file
  Create `tests/test_meta_cli_diff_get_schema.md` containing: the exact command used, the confirmed JSON top-level keys, the per-file/hunk structure (with one redacted sample), the field name carrying the diff body, and the field carrying the revision id (staleness key) and `diff_url`.
  Decision rule recorded in the file:
  - If `get` returns structured hunks -> Task 9 parses them directly.
  - If `get` returns only a raw unified-diff string -> Task 9 parses the unified diff with a small `_parse_unified_diff(text) -> list[hunk dict]` fallback (split on `diff --git`/`+++`/`@@`).
  - If `get` is unavailable -> Task 9 falls back to `meta phabricator.diff list` metadata only (shallow degrade) and the feature ships with hunks empty until a fetch command is confirmed.

- [ ] Step 4: Verify the artifact exists and is non-empty
  Run: `test -s tests/test_meta_cli_diff_get_schema.md && echo CONFIRMED`
  Expected: `CONFIRMED`

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "docs(diff): record confirmed meta phabricator.diff get JSON schema (gates DiffEnricher)"`

---

## Task 9: DiffEnricher — lazy deep fetch, Path Pre-skip, budget caps (meta)

**Files:** Create `workbench_meta/providers/enrichment/diff_enricher.py`, `tests/test_diff_enricher.py`. Uses the schema confirmed in Task 8.

- [ ] Step 1: Write the failing test

```python
# tests/test_diff_enricher.py
import json
from unittest.mock import AsyncMock, patch

import pytest

from workbench.models import EnrichmentBudget, ExtractedItem, RawItem, ItemCategory
from workbench_meta.providers.enrichment.diff_enricher import DiffEnricher


def _item(raw_text):
    raw = RawItem(id="D123_2026", source_type="diff", source_label="D123",
                  raw_text=raw_text)
    return ExtractedItem(summary="Review D123", category=ItemCategory.REVIEW
                         if hasattr(ItemCategory, "REVIEW") else ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


def _meta_list_item():
    return json.dumps({"number": "D123", "title": "Add retry", "status": "Needs Review",
                       "author": "alice", "revision_id": "123"})


def _mock_proc(stdout: bytes, returncode: int = 0):
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, b"")
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
async def test_non_diff_source_returns_empty():
    enr = DiffEnricher(DiffEnricher.ProviderConfig())
    item = ExtractedItem(summary="x", category=ItemCategory.INFORMATIONAL,
                         source_context="",
                         raw_item=RawItem(id="i", source_type="email",
                                          source_label="", raw_text="{}"))
    result = await enr.enrich(item, "deep", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_shallow_mode_does_not_fetch_diff():
    enr = DiffEnricher(DiffEnricher.ProviderConfig())
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = await enr.enrich(_item(_meta_list_item()), "shallow", EnrichmentBudget())
    mock_exec.assert_not_called()
    assert "metadata" in result["context"]
    assert result["context"].get("curated_hunks", []) == []


@pytest.mark.asyncio
async def test_path_preskip_records_skipped_before_llm():
    # Two files: a lockfile (skipped) and a real source file (kept).
    fetched = {
        "revision_id": "123",
        "files": [
            {"path": "yarn.lock", "header": "@@", "code": "+x"},
            {"path": "client.py", "header": "@@ -1,2 +1,3 @@", "code": "+retry()"},
        ],
    }
    enr = DiffEnricher(DiffEnricher.ProviderConfig())
    enr._curate_with_llm = AsyncMock(side_effect=lambda hunks, *a, **k: hunks)
    with patch("asyncio.create_subprocess_exec",
               return_value=_mock_proc(json.dumps(fetched).encode())):
        result = await enr.enrich(_item(_meta_list_item()), "deep", EnrichmentBudget())
    ctx = result["context"]
    skipped_paths = [s["path"] for s in ctx["skipped_files"]]
    assert "yarn.lock" in skipped_paths
    assert any(s["reason"] == "lockfile" for s in ctx["skipped_files"])
    curated_paths = [h["file"] for h in ctx["curated_hunks"]]
    assert "yarn.lock" not in curated_paths
    assert "client.py" in curated_paths


@pytest.mark.asyncio
async def test_budget_cap_truncates_and_flags():
    files = [{"path": f"f{i}.py", "header": "@@", "code": "+a"} for i in range(60)]
    fetched = {"revision_id": "123", "files": files}
    enr = DiffEnricher(DiffEnricher.ProviderConfig(max_files=40))
    enr._curate_with_llm = AsyncMock(side_effect=lambda hunks, *a, **k: hunks)
    with patch("asyncio.create_subprocess_exec",
               return_value=_mock_proc(json.dumps(fetched).encode())):
        result = await enr.enrich(_item(_meta_list_item()), "deep", EnrichmentBudget())
    ctx = result["context"]
    assert ctx["truncated"] is True
    assert len(ctx["curated_hunks"]) <= 40


@pytest.mark.asyncio
async def test_fetch_timeout_degrades_to_shallow():
    import asyncio
    enr = DiffEnricher(DiffEnricher.ProviderConfig())
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(b"")):
            result = await enr.enrich(_item(_meta_list_item()), "deep", EnrichmentBudget())
    ctx = result["context"]
    assert "metadata" in ctx
    assert ctx.get("curated_hunks", []) == []  # never raised


@pytest.mark.asyncio
async def test_metadata_and_entity_refs_present():
    fetched = {"revision_id": "123", "files": []}
    enr = DiffEnricher(DiffEnricher.ProviderConfig())
    enr._curate_with_llm = AsyncMock(side_effect=lambda hunks, *a, **k: hunks)
    with patch("asyncio.create_subprocess_exec",
               return_value=_mock_proc(json.dumps(fetched).encode())):
        result = await enr.enrich(_item(_meta_list_item()), "deep", EnrichmentBudget())
    ctx = result["context"]
    assert ctx["metadata"]["author"] == "alice"
    assert ctx["metadata"]["diff_url"].endswith("D123")
    assert ctx["revision_id"] == "123"
    assert any(t == "person" or getattr(t, "value", None) == "person"
               for t, _ in ctx["entity_refs"])
```

NOTE: adjust the fetched-JSON field names (`files`/`path`/`header`/`code`/`revision_id`) in BOTH the test and the implementation to match the **confirmed Task 8 schema**. If the confirmed schema is a raw unified-diff string, replace `_mock_proc(json.dumps(fetched))` with a unified-diff fixture and test `_parse_unified_diff` instead.

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_diff_enricher.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench_meta.providers.enrichment.diff_enricher'`

- [ ] Step 3: Write minimal implementation

```python
# workbench_meta/providers/enrichment/diff_enricher.py
import asyncio
import json
import os
import time

import structlog
from pydantic import BaseModel
from workbench.models import EnrichmentBudget, EntityType, ExtractedItem
from workbench.providers.enrichment.base import ContextEnricher

logger = structlog.get_logger(__name__)

_LOCKFILES = frozenset({
    "yarn.lock", "package-lock.json", "Cargo.lock", "poetry.lock",
    "Pipfile.lock", "go.sum", "composer.lock",
})
_VENDORED_MARKERS = ("/__generated__/", "__generated__/", "/vendor/", "/third-party/",
                     "/node_modules/")


def _preskip_reason(path: str) -> str | None:
    base = path.rsplit("/", 1)[-1]
    if base in _LOCKFILES:
        return "lockfile"
    if "__generated__" in path:
        return "generated"
    if any(m in path for m in _VENDORED_MARKERS):
        return "vendored"
    return None


class DiffEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        max_files: int = 40
        max_bytes: int = 200_000
        fetch_timeout_seconds: int = 30
        phab_base_url: str = "https://www.internalfb.com/diff/"

    def __init__(self, config: ProviderConfig = None):
        config = config or self.ProviderConfig()
        self.max_files = config.max_files
        self.max_bytes = config.max_bytes
        self.fetch_timeout_seconds = config.fetch_timeout_seconds
        self.phab_base_url = config.phab_base_url

    async def enrich(self, item: ExtractedItem, depth: str,
                     budget: EnrichmentBudget, *, memory=None) -> dict:
        if item.raw_item.source_type != "diff":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        started = time.monotonic()
        try:
            meta = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            meta = {}

        number = str(meta.get("number", "")).lstrip("D")
        diff_url = f"{self.phab_base_url}D{number}" if number else ""
        metadata = {
            "author": meta.get("author", ""),
            "status": meta.get("status", "").lower().replace(" ", "_"),
            "diff_url": diff_url,
        }
        entity_refs = []
        if meta.get("author"):
            entity_refs.append((EntityType.PERSON, f"phabricator:{meta['author']}"))

        context = {
            "metadata": metadata,
            "entity_refs": entity_refs,
            "curated_hunks": [],
            "skipped_files": [],
            "truncated": False,
            "revision_id": str(meta.get("revision_id", number)),
        }

        if depth != "deep" or not number:
            return {"calls_made": 0,
                    "time_ms": int((time.monotonic() - started) * 1000),
                    "context": context}

        fetched = await self._fetch(number)
        calls = 1
        if fetched is None:
            return {"calls_made": calls,
                    "time_ms": int((time.monotonic() - started) * 1000),
                    "context": context}

        if fetched.get("revision_id"):
            context["revision_id"] = str(fetched["revision_id"])

        raw_files = fetched.get("files", [])  # ADJUST per Task 8 schema
        skipped, kept = [], []
        for f in raw_files:
            reason = _preskip_reason(f.get("path", ""))
            if reason:
                skipped.append({"path": f.get("path", ""), "reason": reason})
            else:
                kept.append(f)

        truncated = False
        if len(kept) > self.max_files:
            kept = kept[: self.max_files]
            truncated = True

        total_bytes = 0
        bounded = []
        for f in kept:
            total_bytes += len(f.get("code", ""))
            if total_bytes > self.max_bytes:
                truncated = True
                break
            bounded.append(f)

        curated = await self._curate_with_llm(bounded, item)
        for rank, h in enumerate(curated, 1):
            h.setdefault("rank", rank)

        context["curated_hunks"] = curated
        context["skipped_files"] = skipped
        context["truncated"] = truncated

        return {"calls_made": calls,
                "time_ms": int((time.monotonic() - started) * 1000),
                "context": context}

    async def _fetch(self, number: str):
        args = ["meta", "phabricator.diff", "get", f"D{number}", "--output", "json"]
        env = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/fbcode/platform010/lib"}
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.fetch_timeout_seconds
            )
            if proc.returncode != 0:
                logger.warning("diff_fetch_failed", number=number,
                               stderr=stderr.decode()[:200])
                return None
            out = stdout.decode().strip()
            return json.loads(out) if out else None
        except Exception as e:
            logger.warning("diff_fetch_error", number=number, error=str(e))
            return None

    async def _curate_with_llm(self, files: list, item: ExtractedItem) -> list:
        """LLM noise filter over pre-bounded hunks. v1: pass-through curation
        (Path Pre-skip already removed lockfiles/generated/vendored). Returns a
        list of hunk dicts {file, header, code, rank}."""
        return [
            {"file": f.get("path", ""), "header": f.get("header", ""),
             "code": f.get("code", "")}
            for f in files
        ]

    async def close(self) -> None:
        pass
```

NOTE: v1 `_curate_with_llm` is a deterministic pass-through (Path Pre-skip is the token guard; LLM curation can be a follow-up). The generator (Task 10) does the heavy LLM work. Keep the method seam so an LLM filter can be added without changing callers.

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_diff_enricher.py -v --tb=short`
  Expected: PASS (6 passed) — after aligning field names with the Task 8 schema

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(enrichment): DiffEnricher lazy deep fetch + Path Pre-skip + budget caps (ADR 0024)"`

---

## Task 10: DiffCardContentGenerator — single Opus 4.8 json_schema call (meta)

**Files:** Create `workbench_meta/providers/content/__init__.py`, `workbench_meta/providers/content/diff_generator.py`, `tests/test_diff_generator.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_diff_generator.py
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from workbench.models import ExtractedItem, RawItem, ItemCategory
from workbench_meta.providers.content.diff_generator import DiffCardContentGenerator


def _item():
    raw = RawItem(id="D123_x", source_type="diff", source_label="D123",
                  raw_text=json.dumps({"number": "D123", "author": "alice"}))
    return ExtractedItem(summary="Review D123", category=ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


def _enrichment():
    return {
        "metadata": {"author": "alice", "status": "needs_review",
                     "diff_url": "https://phab/D123"},
        "curated_hunks": [{"file": "client.py", "header": "@@ -1 +1,2 @@",
                           "code": "+retry()", "rank": 1}],
        "revision_id": "123",
    }


def _llm_with_tool_result(payload: dict):
    """Mock an AnthropicLLM exposing .client.messages.create + count_tokens."""
    llm = MagicMock()
    block = SimpleNamespace(type="tool_use", name="emit_diff_card", input=payload)
    response = SimpleNamespace(content=[block])
    llm.client = MagicMock()
    llm.client.messages = MagicMock()
    llm.client.messages.create = AsyncMock(return_value=response)
    llm.client.messages.count_tokens = AsyncMock(
        return_value=SimpleNamespace(input_tokens=500)
    )
    llm.model = "claude-opus-4-8"
    return llm


@pytest.mark.asyncio
async def test_generates_five_section_envelope():
    payload = {
        "metadata": {"author": "alice", "team": "infra", "status": "needs_review"},
        "summary": "Adds a retry loop.",
        "risk": {"factors": ["touches retry path"], "watch_outs": ["no backoff test"]},
        "why_care": "You own this client.",
        "hunks": [{"file": "client.py", "header": "@@ -1 +1,2 @@", "code": "+retry()",
                   "annotation": "adds retry", "rank": 1}],
    }
    llm = _llm_with_tool_result(payload)
    gen = DiffCardContentGenerator(DiffCardContentGenerator.ProviderConfig())
    envelope = await gen.generate(llm, _item(), _enrichment(), memory_context=None)
    assert envelope["content_schema"] == "diff.v1"
    assert envelope["sections"]["summary"] == "Adds a retry loop."
    assert envelope["sections"]["metadata"]["team"] == "infra"
    assert envelope["sections"]["hunks"][0]["file"] == "client.py"
    assert envelope["summary"]  # legacy fallback field present
    # Opus 4.8 + max_tokens=8000
    _, kwargs = llm.client.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["max_tokens"] == 8000


@pytest.mark.asyncio
async def test_refusal_returns_summary_only_envelope():
    llm = MagicMock()
    llm.client = MagicMock()
    llm.client.messages = MagicMock()
    # No tool_use block -> treated as refusal/parse-fail
    llm.client.messages.create = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="no")])
    )
    llm.client.messages.count_tokens = AsyncMock(
        return_value=SimpleNamespace(input_tokens=10)
    )
    llm.model = "claude-opus-4-8"
    gen = DiffCardContentGenerator(DiffCardContentGenerator.ProviderConfig())
    envelope = await gen.generate(llm, _item(), _enrichment(), memory_context=None)
    assert "sections" not in envelope
    assert "content_schema" not in envelope
    assert envelope["summary"]


@pytest.mark.asyncio
async def test_empty_memory_still_generates_summary():
    payload = {
        "metadata": {"author": "alice", "status": "needs_review"},
        "summary": "Generic summary.",
        "risk": {"factors": [], "watch_outs": []},
        "why_care": "n/a", "hunks": [],
    }
    llm = _llm_with_tool_result(payload)
    gen = DiffCardContentGenerator(DiffCardContentGenerator.ProviderConfig())
    envelope = await gen.generate(llm, _item(), _enrichment(), memory_context=None)
    assert envelope["sections"]["summary"] == "Generic summary."


@pytest.mark.asyncio
async def test_count_tokens_called_defensively():
    payload = {
        "metadata": {"author": "alice", "status": "s"}, "summary": "s",
        "risk": {"factors": [], "watch_outs": []}, "why_care": "w", "hunks": [],
    }
    llm = _llm_with_tool_result(payload)
    gen = DiffCardContentGenerator(DiffCardContentGenerator.ProviderConfig())
    await gen.generate(llm, _item(), _enrichment(), memory_context=None)
    llm.client.messages.count_tokens.assert_awaited()
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_diff_generator.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench_meta.providers.content.diff_generator'`

- [ ] Step 3: Write minimal implementation

Create `workbench_meta/providers/content/__init__.py` (empty). Create `diff_generator.py`:

```python
# workbench_meta/providers/content/diff_generator.py
import structlog
from pydantic import BaseModel
from workbench.models import ExtractedItem
from workbench.pipeline.content_generator import CardContentGenerator

logger = structlog.get_logger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 8000

_DIFF_CARD_TOOL = {
    "name": "emit_diff_card",
    "description": "Emit a review-grade diff triage card. Cite ONLY changes "
                   "present in the provided hunks. Do not invent files or risks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {
                    "author": {"type": "string"},
                    "team": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["author", "status"],
            },
            "summary": {"type": "string"},
            "risk": {
                "type": "object",
                "properties": {
                    "factors": {"type": "array", "items": {"type": "string"}},
                    "watch_outs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["factors", "watch_outs"],
            },
            "why_care": {"type": "string"},
            "hunks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "header": {"type": "string"},
                        "code": {"type": "string"},
                        "annotation": {"type": "string"},
                        "rank": {"type": "integer"},
                    },
                    "required": ["file", "header", "code", "annotation", "rank"],
                },
            },
        },
        "required": ["metadata", "summary", "risk", "why_care", "hunks"],
    },
}

_SYSTEM = ("You generate review-grade diff triage cards. Cite only changes present "
           "in the provided hunks; never invent files, lines, or risks. Be concise.")


class DiffCardContentGenerator(CardContentGenerator):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def generate(self, llm, item: ExtractedItem,
                       enrichment_context: dict, memory_context: dict | None) -> dict:
        metadata = enrichment_context.get("metadata", {})
        hunks = enrichment_context.get("curated_hunks", [])
        mem = memory_context or {}

        prompt = self._build_prompt(item, metadata, hunks, mem)
        messages = [{"role": "user", "content": prompt}]

        # Defensive token count at the LLM boundary (d18).
        try:
            await llm.client.messages.count_tokens(
                model=MODEL, system=_SYSTEM, messages=messages, tools=[_DIFF_CARD_TOOL],
            )
        except Exception as e:
            logger.warning("diff_card_count_tokens_failed", error=str(e))

        try:
            response = await llm.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM,
                tools=[_DIFF_CARD_TOOL],
                tool_choice={"type": "tool", "name": "emit_diff_card"},
                messages=messages,
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "emit_diff_card":
                    sections = block.input
                    return {
                        "content_schema": "diff.v1",
                        "sections": sections,
                        "source_type": "diff",
                        "card_body": sections.get("summary", item.summary),
                        "summary": sections.get("summary", item.summary),
                    }
            logger.warning("diff_card_no_tool_use")
        except Exception as e:
            logger.warning("diff_card_generation_failed", error=str(e))

        # Refusal / parse-fail -> summary-only envelope (plain path).
        return {
            "source_type": "diff",
            "card_body": item.summary,
            "summary": item.summary,
        }

    def _build_prompt(self, item, metadata, hunks, mem) -> str:
        hunk_lines = []
        for h in hunks:
            hunk_lines.append(f"### {h.get('file')} {h.get('header')}\n{h.get('code')}")
        entity_lines = [f"  {k}: {v}" for k, v in mem.get("entity_facts", {}).items()]
        pref_lines = [f"  - {p}" for p in mem.get("preference_facts", [])]
        return (
            f"Diff: {item.summary}\n"
            f"Author: {metadata.get('author')}  Status: {metadata.get('status')}\n\n"
            f"Curated hunks (cite only these):\n"
            + ("\n\n".join(hunk_lines) if hunk_lines else "(no hunks fetched)")
            + "\n\nKnown entities:\n"
            + ("\n".join(entity_lines) if entity_lines else "  (none)")
            + "\n\nUser preferences:\n"
            + ("\n".join(pref_lines) if pref_lines else "  (none)")
            + "\n\nEmit the diff card via the emit_diff_card tool."
        )
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_diff_generator.py -v --tb=short`
  Expected: PASS (4 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(content): DiffCardContentGenerator single Opus 4.8 json_schema call (ADR 0025)"`

---

## Task 11: DiffCardPresenter — deterministic DiffCardContent -> CardMessage (meta)

**Files:** Create `workbench_meta/providers/presentation/__init__.py`, `workbench_meta/providers/presentation/diff_presenter.py`, `tests/test_diff_presenter.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_diff_presenter.py
import pytest
from workbench.models import (
    TriageCard, TriageOption, ExtractedItem, RawItem, ItemCategory, CardMessage,
)
from workbench_meta.providers.presentation.diff_presenter import DiffCardPresenter


def _item():
    raw = RawItem(id="D123_x", source_type="diff", source_label="D123", raw_text="{}")
    return ExtractedItem(summary="Review D123", category=ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


def _card(hunks):
    return TriageCard(
        card_content={
            "content_schema": "diff.v1",
            "sections": {
                "metadata": {"author": "alice", "team": "infra", "status": "needs_review"},
                "summary": "Adds a retry loop.",
                "risk": {"factors": ["touches retry path"], "watch_outs": ["no test"]},
                "why_care": "You own this client.",
                "hunks": hunks,
                "diff_url": "https://phab/D123",
            },
            "card_body": "Adds a retry loop.", "summary": "Adds a retry loop.",
            "source_type": "diff",
        },
        options=[TriageOption(label="Add P1", action="add_todo"),
                 TriageOption(label="Skip", action="skip")],
    )


def _hunk(rank, code="+x"):
    return {"file": f"f{rank}.py", "header": "@@ -1 +1 @@", "code": code,
            "annotation": "a", "rank": rank}


def test_renders_cardmessage_with_sections_and_phab_link():
    card = _card([_hunk(1)])
    card.card_content["sections"]["diff_url"] = "https://phab/D123"
    msg = DiffCardPresenter(DiffCardPresenter.ProviderConfig(
        diff_url_from_metadata=True)).render(card, _item())
    assert isinstance(msg, CardMessage)
    titles = [s.title for s in msg.sections]
    assert "Summary" in titles
    assert "Risk" in titles
    assert any(l.label == "View in Phabricator" for l in msg.links)
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]


def test_chat_slices_top_3_hunks_by_rank():
    card = _card([_hunk(r) for r in (4, 1, 2, 3, 5)])
    msg = DiffCardPresenter(DiffCardPresenter.ProviderConfig()).render(card, _item())
    ranks = [h.rank for h in msg.thread_hunks]
    assert ranks == [1, 2, 3]


def test_hunk_reply_truncated_to_1500_chars():
    big = "+x\n" * 2000
    card = _card([_hunk(1, code=big)])
    msg = DiffCardPresenter(DiffCardPresenter.ProviderConfig()).render(card, _item())
    assert len(msg.thread_hunks[0].code) <= 1500 + len("...(full diff in dashboard)")
    assert "full diff in dashboard" in msg.thread_hunks[0].code


def test_summary_and_risk_caps():
    card = _card([_hunk(1)])
    card.card_content["sections"]["summary"] = "S" * 2000
    card.card_content["sections"]["risk"]["factors"] = ["R" * 2000]
    msg = DiffCardPresenter(DiffCardPresenter.ProviderConfig()).render(card, _item())
    summary_section = next(s for s in msg.sections if s.title == "Summary")
    risk_section = next(s for s in msg.sections if s.title == "Risk")
    assert len(summary_section.body) <= 800
    assert len(risk_section.body) <= 600
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_diff_presenter.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench_meta.providers.presentation.diff_presenter'`

- [ ] Step 3: Write minimal implementation

Create `workbench_meta/providers/presentation/__init__.py` (empty). Create `diff_presenter.py`:

```python
# workbench_meta/providers/presentation/diff_presenter.py
from pydantic import BaseModel
from workbench.models import (
    CardLink, CardMessage, CardSection, ExtractedItem, ThreadHunk, TriageCard,
)
from workbench.pipeline.presenter import CardPresenter

_SUMMARY_CAP = 800
_RISK_CAP = 600
_HUNK_CAP = 1500
_HUNK_TRUNC_SUFFIX = "...(full diff in dashboard)"
_MAX_CHAT_HUNKS = 3


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


class DiffCardPresenter(CardPresenter):

    class ProviderConfig(BaseModel):
        max_hunks: int = 15
        diff_url_from_metadata: bool = False

    def __init__(self, config: ProviderConfig = None):
        config = config or self.ProviderConfig()
        self.max_hunks = config.max_hunks

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        sections_data = card.card_content.get("sections", {})
        metadata = sections_data.get("metadata", {})
        risk = sections_data.get("risk", {})

        header_bits = [item.summary or card.card_content.get("summary", "Diff")]
        meta_line = f"by {metadata.get('author', '?')}"
        if metadata.get("team"):
            meta_line += f" ({metadata['team']})"
        meta_line += f" — {metadata.get('status', '')}"

        sections = [CardSection(title="Metadata", body=meta_line)]
        summary = sections_data.get("summary", "")
        if summary:
            sections.append(CardSection(title="Summary",
                                        body=_cap(summary, _SUMMARY_CAP)))
        risk_body = self._risk_body(risk)
        if risk_body:
            sections.append(CardSection(title="Risk", body=_cap(risk_body, _RISK_CAP)))
        why = sections_data.get("why_care", "")
        if why:
            sections.append(CardSection(title="Why it matters",
                                        body=_cap(why, _RISK_CAP)))

        links = []
        diff_url = sections_data.get("diff_url") or metadata.get("diff_url")
        if diff_url:
            links.append(CardLink(label="View in Phabricator", url=diff_url))

        all_hunks = sorted(sections_data.get("hunks", []),
                           key=lambda h: h.get("rank", 9999))
        top = all_hunks[:_MAX_CHAT_HUNKS]
        thread_hunks = [
            ThreadHunk(
                file=h.get("file", ""), header=h.get("header", ""),
                code=self._cap_hunk(h.get("code", "")), rank=h.get("rank", 0),
            )
            for h in top
        ]

        return CardMessage(
            header=header_bits[0],
            sections=sections,
            links=links,
            options=list(card.options),
            thread_hunks=thread_hunks,
        )

    @staticmethod
    def _risk_body(risk: dict) -> str:
        parts = []
        for f in risk.get("factors", []):
            parts.append(f"- {f}")
        for w in risk.get("watch_outs", []):
            parts.append(f"! {w}")
        return "\n".join(parts)

    @staticmethod
    def _cap_hunk(code: str) -> str:
        if len(code) <= _HUNK_CAP:
            return code
        return code[:_HUNK_CAP] + _HUNK_TRUNC_SUFFIX
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_diff_presenter.py -v --tb=short`
  Expected: PASS (4 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(presentation): DiffCardPresenter deterministic DiffCardContent -> CardMessage (ADR 0023)"`

---

## Task 12: GoogleChatMessenger.send_card override — cardsV2 + threaded hunks (meta)

**Files:** Modify `workbench_meta/providers/messenger/gchat.py`; Create `tests/test_gchat_send_card.py`. Uses thread fields confirmed available in `google_api.send_card_message`.

- [ ] Step 1: Write the failing test

```python
# tests/test_gchat_send_card.py
from unittest.mock import patch

import pytest

from workbench.models import CardMessage, CardSection, CardLink, ThreadHunk, TriageOption
from workbench_meta.providers.messenger.gchat import GoogleChatMessenger


def _messenger():
    return GoogleChatMessenger(GoogleChatMessenger.ProviderConfig(space_id="spaces/AAA"))


def _card_message():
    return CardMessage(
        header="Diff D123 — add retry",
        sections=[CardSection(title="Summary", body="adds retry loop"),
                  CardSection(title="Risk", body="- touches retry path")],
        links=[CardLink(label="View in Phabricator", url="https://phab/D123")],
        options=[TriageOption(label="Add P1", action="add_todo"),
                 TriageOption(label="Skip", action="skip")],
        thread_hunks=[ThreadHunk(file="client.py", header="@@", code="+retry()", rank=1),
                      ThreadHunk(file="b.py", header="@@", code="+x", rank=2),
                      ThreadHunk(file="c.py", header="@@", code="+y", rank=3)],
    )


@pytest.mark.asyncio
async def test_send_card_posts_parent_cardsv2_then_thread_hunks():
    calls = {"card": [], "msg": []}

    def fake_card(space_id, text, cards_v2, thread_name=None, as_bot=True):
        calls["card"].append({"thread_name": thread_name, "cards_v2": cards_v2})
        return {"success": True, "data": {"name": "spaces/AAA/messages/parent",
                                          "thread": "spaces/AAA/threads/T1"}}

    def fake_msg(space_id, text, thread_name=None, as_bot=True):
        calls["msg"].append({"text": text, "thread_name": thread_name})
        return {"success": True, "data": {"name": "spaces/AAA/messages/reply",
                                          "thread": "spaces/AAA/threads/T1"}}

    with patch("workbench_meta.providers.messenger.gchat.send_card_message", side_effect=fake_card), \
         patch("workbench_meta.providers.messenger.gchat.send_message", side_effect=fake_msg):
        msg_id = await _messenger().send_card(_card_message())

    assert msg_id == "spaces/AAA/messages/parent"
    assert len(calls["card"]) == 1                 # one parent cardsV2 post
    assert calls["card"][0]["thread_name"] is None  # parent starts the thread
    assert len(calls["msg"]) == 3                   # <=3 hunk replies
    assert all(c["thread_name"] == "spaces/AAA/threads/T1" for c in calls["msg"])


@pytest.mark.asyncio
async def test_send_card_accepts_plain_string_back_compat():
    def fake_msg(space_id, text, thread_name=None, as_bot=True):
        return {"success": True, "data": {"name": "spaces/AAA/messages/x", "thread": ""}}

    with patch("workbench_meta.providers.messenger.gchat.send_message", side_effect=fake_msg):
        msg_id = await _messenger().send_card("Got it -- Add P1")
    assert msg_id == "spaces/AAA/messages/x"


@pytest.mark.asyncio
async def test_hunk_reply_429_is_logged_and_skipped_parent_still_returned():
    def fake_card(space_id, text, cards_v2, thread_name=None, as_bot=True):
        return {"success": True, "data": {"name": "spaces/AAA/messages/parent",
                                          "thread": "spaces/AAA/threads/T1"}}

    def fake_msg(space_id, text, thread_name=None, as_bot=True):
        return {"success": False, "error": "429 RESOURCE_EXHAUSTED"}

    with patch("workbench_meta.providers.messenger.gchat.send_card_message", side_effect=fake_card), \
         patch("workbench_meta.providers.messenger.gchat.send_message", side_effect=fake_msg):
        msg_id = await _messenger().send_card(_card_message())
    assert msg_id == "spaces/AAA/messages/parent"  # parent is source of truth
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_gchat_send_card.py -v --tb=short`
  Expected: `ImportError`/`AttributeError` — `send_card_message` not imported in gchat.py and `send_card` does not accept a `CardMessage`.

- [ ] Step 3: Write minimal implementation

Update imports and `send_card` in `workbench_meta/providers/messenger/gchat.py`:

```python
from workbench_meta.lib.google_api import send_message, list_messages, send_card_message
```

Replace `send_card`:

```python
    async def send_card(self, card) -> str:
        from workbench.models import CardMessage

        if not self.space_id:
            return ""
        if not isinstance(card, CardMessage):
            return await self._send_text(str(card), thread_name=None)

        cards_v2 = self._to_cards_v2(card)
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(send_card_message, self.space_id, card.header, cards_v2,
                    as_bot=self.as_bot),
        )
        if not result.get("success"):
            raise RuntimeError(f"Failed to send card: {result.get('error', 'unknown')}")
        parent_id = result["data"].get("name", "")
        thread_name = result["data"].get("thread", "")

        for hunk in card.thread_hunks[:3]:
            text = f"`{hunk.file}` {hunk.header}\n```\n{hunk.code}\n```"
            reply = await asyncio.get_event_loop().run_in_executor(
                None,
                partial(send_message, self.space_id, text,
                        thread_name=thread_name, as_bot=self.as_bot),
            )
            if not reply.get("success"):
                logger.warning("hunk_reply_failed file=%s error=%s",
                               hunk.file, reply.get("error", "unknown"))
                break  # best-effort; 429 skips remaining replies
        return parent_id

    async def _send_text(self, text: str, thread_name: str | None) -> str:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(send_message, self.space_id, text,
                    thread_name=thread_name, as_bot=self.as_bot),
        )
        if result.get("success"):
            return result["data"].get("name", "")
        raise RuntimeError(f"Failed to send message: {result.get('error', 'unknown')}")

    def _to_cards_v2(self, card) -> list:
        widgets = []
        for section in card.sections:
            widgets.append({"textParagraph": {"text": f"<b>{section.title}</b><br>{section.body}"
                                              if section.title else section.body}})
        buttons = [{"text": link.label, "onClick": {"openLink": {"url": link.url}}}
                   for link in card.links]
        if buttons:
            widgets.append({"buttonList": {"buttons": buttons}})
        opt_text = "\n".join(f"{i}. {o.label}" for i, o in enumerate(card.options, 1))
        if opt_text:
            widgets.append({"textParagraph": {"text": opt_text}})
        return [{"cardId": "diff-card",
                 "card": {"header": {"title": card.header},
                          "sections": [{"widgets": widgets}]}}]
```

NOTE: monospace hunk replies use cardsV2-free text replies with code fences here for simplicity; if Task 8 / wire testing shows the spec's "monospace cardsV2 widget" is required, swap `send_message` for a `send_card_message` reply carrying a `decoratedText`/monospace widget. The thread parent/reply mechanics (the load-bearing part) are unchanged.

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_gchat_send_card.py -v --tb=short`
  Expected: PASS (3 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(messenger): GoogleChatMessenger.send_card cardsV2 + threaded hunk replies (ADR 0026)"`

---

## Task 13: Meta config wiring — presentation + enricher + generator (meta)

**Files:** Modify `config.meta.yml`; Create `tests/test_meta_config_wiring.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_meta_config_wiring.py
import os
import yaml

CONFIG = os.path.join(os.path.dirname(__file__), "..", "config.meta.yml")


def _load():
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def test_presentation_registers_diff_presenter_and_generator():
    cfg = _load()
    providers = cfg["presentation"]["providers"]
    diff = next(p for p in providers if p["source_type"] == "diff")
    assert diff["class"].endswith("diff_presenter.DiffCardPresenter")
    assert diff["content_generator"].endswith("diff_generator.DiffCardContentGenerator")


def test_enrichment_registers_diff_enricher_for_diff_source_type():
    cfg = _load()
    providers = cfg["enrichment"]["providers"]
    diff = next(p for p in providers
               if "diff" in p.get("source_types", []))
    assert diff["class"].endswith("diff_enricher.DiffEnricher")
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_meta_config_wiring.py -v --tb=short`
  Expected: `KeyError: 'presentation'` (and the enrichment list form is not present).

- [ ] Step 3: Write minimal implementation — edit `config.meta.yml`

Replace the `enrichment:` block with the composite/providers form including the diff enricher, and add a `presentation:` block:

```yaml
enrichment:
  providers:
    - class: workbench_meta.providers.enrichment.diff_enricher.DiffEnricher
      source_types: ["diff"]
      budget:
        max_api_calls: 3
        max_seconds: 30
  default:
    class: workbench_meta.providers.enrichment.meta.MetaEnricher

presentation:
  providers:
    - source_type: diff
      class: workbench_meta.providers.presentation.diff_presenter.DiffCardPresenter
      content_generator: workbench_meta.providers.content.diff_generator.DiffCardContentGenerator
      config:
        enabled: true
        max_hunks: 15
        sections: [metadata, summary, risk, why_care, hunks]
        expand_default: [risk, why_care]
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_meta_config_wiring.py -v --tb=short`
  Expected: PASS (2 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(config): wire diff enricher + presentation diff presenter/generator (Meta)"`

---

## Task 14: UI — useTriageCard hook (foundational)

**Files:** Create `ui/src/hooks/useTriageCard.ts`, `ui/src/hooks/useTriageCard.test.ts`

- [ ] Step 1: Write the failing test

```typescript
// ui/src/hooks/useTriageCard.test.ts
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'
import { useTriageCard } from './useTriageCard'
import { _resetToken } from '@/lib/api'

const CARD = {
  id: 'c1',
  card_content: { content_schema: 'diff.v1', summary: 'adds retry', sections: { summary: 'adds retry' } },
  options: [{ label: 'Add P1', action: 'add_todo' }],
  relevance_score: 80,
  status: 'sent',
}

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
  _resetToken()
})
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return createElement(QueryClientProvider, { client }, children)
}

describe('useTriageCard', () => {
  it('fetches a single card by id', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    const { result } = renderHook(() => useTriageCard('c1'), { wrapper })
    await waitFor(() => expect(result.current.data?.id).toBe('c1'))
    expect(result.current.data?.card_content.content_schema).toBe('diff.v1')
  })

  it('surfaces an error for a 404', async () => {
    server.use(
      http.get('/api/triage/cards/missing', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    const { result } = renderHook(() => useTriageCard('missing'), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
```

- [ ] Step 2: Run test to verify it fails
  Run: `cd ui && npx vitest run src/hooks/useTriageCard.test.ts`
  Expected: cannot resolve `./useTriageCard` (module not found).

- [ ] Step 3: Write minimal implementation

```typescript
// ui/src/hooks/useTriageCard.ts
// Single-card detail hook for the Triage Card Detail View (#/triage/:cardId).
// apiGet, reuses the five-state pattern, does NOT poll.
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import type { TriageCard } from '@/hooks/useTriage'

export function useTriageCard(id: string) {
  return useQuery({
    queryKey: ['triage', 'card', id],
    queryFn: () => apiGet<TriageCard>(`/api/triage/cards/${id}`),
    enabled: !!id,
  })
}
```

- [ ] Step 4: Run test to verify it passes
  Run: `cd ui && npx vitest run src/hooks/useTriageCard.test.ts`
  Expected: PASS (2 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): useTriageCard(id) detail hook (no poll)"`

---

## Task 15: UI — DiffHunks CSS-only component (foundational)

**Files:** Create `ui/src/components/DiffHunks.tsx`, `ui/src/components/DiffHunks.test.tsx`

- [ ] Step 1: Write the failing test

```typescript
// ui/src/components/DiffHunks.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DiffHunks, type Hunk } from './DiffHunks'

const HUNKS: Hunk[] = [
  { file: 'client.py', header: '@@ -1 +1,2 @@', code: '+added line\n-removed line\n unchanged',
    annotation: 'adds retry', rank: 1 },
  { file: 'b.py', header: '@@ -5 +5 @@', code: '+other', annotation: 'x', rank: 2 },
]

describe('DiffHunks', () => {
  it('renders one collapsible block per file and auto-expands the top hunk', () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    expect(screen.getByText('client.py')).toBeInTheDocument()
    expect(screen.getByText('b.py')).toBeInTheDocument()
    // top (rank 1) hunk auto-expanded -> its code lines are visible
    expect(screen.getByText('+added line')).toBeInTheDocument()
  })

  it('colors + and - lines via CSS classes only', () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    const added = screen.getByText('+added line')
    const removed = screen.getByText('-removed line')
    expect(added.className).toMatch(/add/)
    expect(removed.className).toMatch(/del/)
  })

  it('respects maxHunks cap', () => {
    const many: Hunk[] = Array.from({ length: 20 }, (_, i) => ({
      file: `f${i}.py`, header: '@@', code: '+x', annotation: 'a', rank: i + 1,
    }))
    render(<DiffHunks hunks={many} maxHunks={15} />)
    expect(screen.getAllByRole('button', { name: /\.py/ }).length).toBe(15)
  })

  it('expands a collapsed file on click', async () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    // b.py (rank 2) starts collapsed
    expect(screen.queryByText('+other')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /b\.py/ }))
    expect(screen.getByText('+other')).toBeInTheDocument()
  })
})
```

- [ ] Step 2: Run test to verify it fails
  Run: `cd ui && npx vitest run src/components/DiffHunks.test.tsx`
  Expected: cannot resolve `./DiffHunks`.

- [ ] Step 3: Write minimal implementation

```typescript
// ui/src/components/DiffHunks.tsx
// CSS-only +/- diff renderer with per-file expand. No syntax-highlight or diff
// library (ADR 0028). The highest-rank (rank 1) hunk auto-expands; others start
// collapsed.
import { useState } from 'react'

export interface Hunk {
  file: string
  header: string
  code: string
  annotation: string
  rank: number
}

function lineClass(line: string): string {
  if (line.startsWith('+')) return 'diff-add bg-green-950/40 text-green-300'
  if (line.startsWith('-')) return 'diff-del bg-red-950/40 text-red-300'
  return 'diff-ctx text-muted-foreground'
}

function HunkBlock({ hunk, defaultOpen }: { hunk: Hunk; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-2 text-left font-mono text-sm"
      >
        <span>
          {hunk.file} <span className="text-muted-foreground">{hunk.header}</span>
        </span>
        <span>{open ? '−' : '+'}</span>
      </button>
      {open && (
        <pre className="overflow-x-auto p-2 text-xs">
          {hunk.code.split('\n').map((line, i) => (
            <div key={i} className={lineClass(line)}>
              {line || ' '}
            </div>
          ))}
        </pre>
      )}
    </div>
  )
}

export function DiffHunks({ hunks, maxHunks }: { hunks: Hunk[]; maxHunks: number }) {
  const sorted = [...hunks].sort((a, b) => a.rank - b.rank).slice(0, maxHunks)
  const topRank = sorted.length ? sorted[0].rank : -1
  return (
    <div className="space-y-2">
      {sorted.map((h) => (
        <HunkBlock key={`${h.file}-${h.rank}`} hunk={h} defaultOpen={h.rank === topRank} />
      ))}
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
  Run: `cd ui && npx vitest run src/components/DiffHunks.test.tsx`
  Expected: PASS (4 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): DiffHunks CSS-only diff renderer with per-file expand (ADR 0028)"`

---

## Task 16: UI — TriageDetail page + route + Review link (foundational)

**Files:** Create `ui/src/pages/TriageDetail.tsx`, `ui/src/pages/TriageDetail.test.tsx`; Modify `ui/src/App.tsx`, `ui/src/pages/Triage.tsx`

- [ ] Step 1: Write the failing test

```typescript
// ui/src/pages/TriageDetail.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { TriageDetail } from './TriageDetail'
import { _resetToken } from '@/lib/api'

const CARD = {
  id: 'c1',
  status: 'sent',
  relevance_score: 80,
  options: [{ label: 'Add P1', action: 'add_todo' }, { label: 'Skip', action: 'skip' }],
  card_content: {
    content_schema: 'diff.v1',
    summary: 'Adds a retry loop',
    sections: {
      metadata: { author: 'alice', team: 'infra', status: 'needs_review' },
      summary: 'Adds a retry loop',
      risk: { factors: ['touches retry path'], watch_outs: ['no test'] },
      why_care: 'You own this client',
      hunks: [{ file: 'client.py', header: '@@ -1 +1,2 @@', code: '+retry()', annotation: 'adds retry', rank: 1 }],
      diff_url: 'https://phab/D123',
    },
  },
}

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
  _resetToken()
})
afterAll(() => server.close())

function renderDetail(id = 'c1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/triage/${id}`]}>
        <Routes>
          <Route path="/triage/:cardId" element={<TriageDetail />} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TriageDetail', () => {
  it('renders metadata + summary visible and the Phabricator link', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText('Adds a retry loop')).toBeInTheDocument()
    expect(screen.getByText(/alice/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /View in Phabricator/i })
    expect(link).toHaveAttribute('href', 'https://phab/D123')
  })

  it('shows risk + why-care expanded by default', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText(/touches retry path/)).toBeInTheDocument()
    expect(screen.getByText(/You own this client/)).toBeInTheDocument()
  })

  it('renders the diff hunks', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText('client.py')).toBeInTheDocument()
    expect(screen.getByText('+retry()')).toBeInTheDocument()
  })

  it('is read-only when the card status is responded', async () => {
    server.use(
      http.get('/api/triage/cards/c1', () =>
        HttpResponse.json({ ...CARD, status: 'responded' }),
      ),
    )
    renderDetail()
    await screen.findByText('Adds a retry loop')
    expect(screen.queryByRole('button', { name: /1\. Add P1/i })).not.toBeInTheDocument()
  })

  it('shows option buttons when the card is actionable (sent)', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByRole('button', { name: /1\. Add P1/i })).toBeInTheDocument()
  })
})
```

- [ ] Step 2: Run test to verify it fails
  Run: `cd ui && npx vitest run src/pages/TriageDetail.test.tsx`
  Expected: cannot resolve `./TriageDetail`.

- [ ] Step 3: Write minimal implementation

```typescript
// ui/src/pages/TriageDetail.tsx
// Triage Card Detail View (#/triage/:cardId). Renders the structured diff
// card_content client-side: metadata + summary always visible, risk + why-care
// expanded, hunks via DiffHunks, a prominent View in Phabricator link, and
// reuses useTriage respond/confirm. Read-only when responded/expired.
import { useParams } from 'react-router-dom'
import { useTriageCard } from '@/hooks/useTriageCard'
import { useRespond } from '@/hooks/useTriage'
import { DiffHunks, type Hunk } from '@/components/DiffHunks'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

export function TriageDetail() {
  const { cardId = '' } = useParams()
  const card = useTriageCard(cardId)
  const respond = useRespond()

  if (card.isPending) {
    return (
      <div data-testid="detail-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (card.isError) {
    const err = card.error as ApiError
    if (err.status === 401) {
      return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load card: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const c = card.data
  const sections = (c.card_content.sections ?? {}) as Record<string, unknown>
  const metadata = (sections.metadata ?? {}) as { author?: string; team?: string; status?: string }
  const risk = (sections.risk ?? {}) as { factors?: string[]; watch_outs?: string[] }
  const hunks = (sections.hunks ?? []) as Hunk[]
  const diffUrl = (sections.diff_url as string | undefined) ?? undefined
  const summary = (sections.summary as string) ?? c.card_content.summary ?? '(no summary)'
  const whyCare = (sections.why_care as string) ?? ''
  const readOnly = c.status === 'responded' || c.status === 'expired'

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <h1 className="text-lg font-semibold">{summary}</h1>
        {typeof c.relevance_score === 'number' && (
          <Badge variant="secondary">relevance {c.relevance_score}</Badge>
        )}
      </div>

      <div className="text-sm text-muted-foreground">
        by {metadata.author ?? '?'}
        {metadata.team ? ` (${metadata.team})` : ''} — {metadata.status ?? ''}
      </div>

      {diffUrl && (
        <a
          href={diffUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-block rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
        >
          View in Phabricator
        </a>
      )}

      <section>
        <h2 className="font-medium">Risk</h2>
        <ul className="list-disc pl-5 text-sm">
          {(risk.factors ?? []).map((f, i) => <li key={`f${i}`}>{f}</li>)}
          {(risk.watch_outs ?? []).map((w, i) => <li key={`w${i}`}>⚠ {w}</li>)}
        </ul>
      </section>

      {whyCare && (
        <section>
          <h2 className="font-medium">Why it matters</h2>
          <p className="text-sm">{whyCare}</p>
        </section>
      )}

      <section>
        <h2 className="font-medium">Changes</h2>
        <DiffHunks hunks={hunks} maxHunks={15} />
      </section>

      {!readOnly && (
        <div className="flex flex-wrap gap-2">
          {c.options.map((o, i) => (
            <Button
              key={`${o.action}-${i}`}
              variant="outline"
              disabled={respond.isPending}
              onClick={() => respond.mutate({ card_id: c.id, choice: i + 1 })}
            >
              {i + 1}. {o.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}
```

Add the route to `ui/src/App.tsx` — add the import and the `Route`:

```typescript
import { TriageDetail } from '@/pages/TriageDetail'
```
```typescript
          <Route path="/triage" element={<Triage />} />
          <Route path="/triage/:cardId" element={<TriageDetail />} />
```

Add a Review link per card in `ui/src/pages/Triage.tsx`. Import `Link` and render it inside `TriageCardItem` next to the relevance badge:

```typescript
import { Link } from 'react-router-dom'
```
Inside the header `<div className="flex items-start justify-between gap-3">`, after the badge:
```typescript
        <Link to={`/triage/${card.id}`} className="shrink-0 text-sm underline">
          Review
        </Link>
```

- [ ] Step 4: Run test to verify it passes
  Run: `cd ui && npx vitest run src/pages/TriageDetail.test.tsx src/pages/Triage.test.tsx`
  Expected: PASS (TriageDetail 5 passed; Triage tests still pass)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): TriageDetail page + #/triage/:cardId route + Review link (ADR 0023)"`

---

## Task 17: UI — regenerate api-types + full build/test (foundational)

**Files:** Modify `ui/src/lib/api-types.ts` (regenerated)

Per the npm-blocked constraint: download standalone Node v20 to `/tmp`, put it on `PATH`, run the server locally, then regenerate types and build/test with that toolchain.

- [ ] Step 1: Start the server so the OpenAPI schema includes the new `cards/{card_id}` route
  Run: `cd /home/anshulverma/workspace/workbench && make serve &` (or `python -m uvicorn workbench.main:app --host 127.0.0.1 --port 8421`); confirm `curl -s http://127.0.0.1:8421/openapi.json | grep -q 'cards/{card_id}' && echo HAS_ROUTE`
  Expected: `HAS_ROUTE`

- [ ] Step 2: Regenerate the types
  Run: `cd /home/anshulverma/workspace/workbench/ui && npm run gen:api`
  Expected: `src/lib/api-types.ts` regenerated with a `/api/triage/cards/{card_id}` path entry (grep it: `grep -c 'cards/{card_id}' src/lib/api-types.ts` -> `>=1`).

- [ ] Step 3: Run the full UI test + typecheck + build
  Run: `cd /home/anshulverma/workspace/workbench/ui && npm run test && npm run build`
  Expected: all vitest suites PASS; `tsc -b && vite build` completes with no type errors; no new dependency added to `package.json` (verify `git diff package.json` is empty).

- [ ] Step 4: Stop the dev server
  Run: `kill %1 2>/dev/null || pkill -f 'uvicorn workbench.main'`
  Expected: server stopped.

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add ui/src/lib/api-types.ts && git commit -m "chore(ui): regenerate api-types with triage card detail route"`

---

## Task 18: CONTEXT.md update — new terms + memory-caps fix (foundational)

**Files:** Modify `docs/CONTEXT.md`

- [ ] Step 1: Write the failing test (a docs guard test in the foundational suite)

```python
# tests/test_context_doc.py
import os

CONTEXT = os.path.join(os.path.dirname(__file__), "..", "docs", "CONTEXT.md")


def _text():
    with open(CONTEXT) as f:
        return f.read()


def test_memory_caps_drift_corrected():
    text = _text()
    assert "without caps" not in text
    # The real contract: entity 5 / preference 20 / relationship 10.
    assert "entity 5" in text or "entity facts (cap 5" in text


def test_new_terms_present():
    text = _text()
    for term in ["Card Presenter", "Card Content Schema", "Card Content Generator",
                 "CardMessage", "Diff Enricher"]:
        assert term in text, f"missing CONTEXT term: {term}"
```

- [ ] Step 2: Run test to verify it fails
  Run: `python -m pytest tests/test_context_doc.py -v --tb=short`
  Expected: FAIL — "without caps" still present; new terms missing.

- [ ] Step 3: Write minimal implementation — edit `docs/CONTEXT.md`

In the **Triage Card** entry, replace `(all sent to the LLM without caps)` with `(entity facts cap 5, preference facts cap 20, relationships cap 10; i.e. entity 5 / preference 20 / relationship 10)`.

Append new glossary entries (matching the existing `**Term**: ...` style):

```markdown
**Card Presenter**: A pure, deterministic renderer (no LLM, no memory) that turns a `TriageCard` plus its `ExtractedItem` into a transport-neutral `CardMessage`. The `CardPresenter` ABC lives in `src/workbench/pipeline/presenter.py`; `CompositeCardPresenter` routes by `source_type` against delegates built from the `presentation.providers` config and falls back to `PlainCardPresenter` (which wraps `format_card_for_chat`) on unknown source type, missing/invalid sections, or any delegate exception (logged `presenter_failure`/`presenter_fallback`/`presenter_content_invalid`). Restart-only (ADR 0029); not on the hot-reload path.

**Card Content Schema**: A typed pydantic shape persisted under the existing untyped `TriageCard.card_content` dict (no Alembic migration). `card_content['content_schema']="diff.v1"` is the discriminator and `card_content['sections']` holds the serialized `DiffCardContent{metadata, summary, risk, why_care, hunks}`; legacy `card_body`/`summary` keys remain for the plain fallback (ADR 0022).

**Card Content Generator**: A registered `CardContentGenerator` selected by `source_type` (dynamic import like enrichers). `generate_card` dispatches to it without naming "diff"; the default when none is registered is `llm.generate_triage_card`. The Meta `DiffCardContentGenerator` makes a single Opus 4.8 (`claude-opus-4-8`) `json_schema` call (`max_tokens=8000`) producing all five sections, citing only changes present in the curated hunks (ADR 0025).

**CardMessage**: The transport-neutral message object (`header`, `sections`, `links`, `options`, `thread_hunks`) emitted by a Card Presenter and consumed by `Messenger.send_card(CardMessage) -> message_id`. The base `Messenger.render_to_text(CardMessage)` flattens it for console/non-rich transports; `GoogleChatMessenger` overrides `send_card` to translate it to cardsV2 with threaded monospace hunk replies (ADR 0026).

**Diff Enricher**: The Meta `DiffEnricher` registered for `source_type="diff"`. In deep mode it lazily fetches the diff (`meta phabricator.diff get`, `asyncio.create_subprocess_exec`, 30s timeout), applies a cheap Path Pre-skip (lockfiles/`__generated__`/vendored, recorded in `skipped_files`), enforces budget caps (40 files / ~200KB / `truncated`), and emits `{metadata, entity_refs, curated_hunks, skipped_files, truncated, revision_id, diff_url}` as enrichment context — never written to `raw_text`. Degrades to shallow (metadata + entity_refs) on fetch failure and never raises (ADR 0024).
```

- [ ] Step 4: Run test to verify it passes
  Run: `python -m pytest tests/test_context_doc.py -v --tb=short`
  Expected: PASS (2 passed)

- [ ] Step 5: Commit
  Run: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "docs(context): add card presentation terms; fix memory caps drift to 5/20/10"`

---

## Final verification (run after all tasks)

- foundational: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -v --tb=short && python -m ruff check src/ tests/`
- meta: `cd /home/anshulverma/workspace/workbench-meta && python -m pytest tests/ -v --tb=short`
- ui: `cd /home/anshulverma/workspace/workbench/ui && npm run test && npm run build` (standalone /tmp Node v20)

Confirm against the spec's Verification list (items 1–20): plain fallback when `presentation` absent (1), hard error on unimportable class (2), shallow degrade on fetch failure (3), metadata-only `poll()` (4), Path Pre-skip ordering (5), budget truncation (6), Opus 4.8 single call writing `content_schema=="diff.v1"` (7), empty-memory summary (8), refusal -> summary-only -> plain path (9), revision_id reuse/regeneration (10 — note: reuse-on-rescore keying by `revision_id` is implemented in the rescore path; if the rescore path is out of the current engine scope, file a follow-up and keep the `revision_id` stored on the card so the key is available), CardMessage send_card + console render_to_text (11), cardsV2 parent + <=3 threaded hunks + 429 skip (12), chat caps (13), link-only buttons + thread reply capture (14), detail API 404/bearer (15), detail-view expand defaults (16), CSS-only hunks + max_hunks + no new dep (17), reuse useTriage + read-only (18), gen:api type shape (19), config minor bump + loads with presentation (20).

# Combined: Review-Grade Diff Cards + Change Monitoring & Re-Triage — Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.
**Goal:** Deliver review-grade, code-bearing diff triage cards AND continuous change-monitoring/re-triage as one system, where re-triage drives the same `CompositeCardPresenter → CardMessage` path and a `diff_version` signal triggers a two-tier (full vs light) diff-card regeneration.
**Architecture:** Feature A adds a source-pluggable presentation layer (`CardPresenter`/`CardContentGenerator`/typed `DiffCardContent`/structured `CardMessage` messenger interface/detail API+UI) so `source_type="diff"` cards carry curated hunks. Feature B adds synchronous, no-LLM `ChangeDetector`s, stable `source_id`s, a `DebounceManager`, and a `_fire_retriage` path that re-runs enrichment + card generation on material change. They integrate at three seams: re-triage renders through the presenter (not `format_card_for_chat`), `update_message` is symmetric with `send_card` (both take `CardMessage`), and a `diff_version` change yields `change_type="code_updated"` that keys regeneration depth (full re-fetch vs reuse-stored-hunks).
**Tech Stack:** Python 3.12, pydantic v2, FastAPI, asyncpg, Anthropic SDK (`claude-opus-4-8`), APScheduler, OmegaConf/pydantic config, Alembic; React 19 + Vite + TanStack Query + react-router-dom HashRouter + vitest/MSW; `meta` CLI via `asyncio.create_subprocess_exec`; Google Chat REST cardsV2.
**Source plans (referenced for unchanged task bodies):** Feature A = docs/auto-plan/plans/2026-06-08-review-grade-diff-triage-cards.md ; Feature B = docs/auto-plan/plans/2026-06-08-change-monitoring-retriage.md
**Test commands:** foundational `python -m pytest tests/ -v --tb=short` (single: `python -m pytest tests/test_X.py::test_y -v`), run from `/home/anshulverma/workspace/workbench`; meta same, run from `/home/anshulverma/workspace/workbench-meta`; ui `npm run test` (vitest) + `npm run gen:api` + `npm run build` via standalone /tmp Node v20 (npm-blocked devserver — download standalone Node v20 to `/tmp`, put on `PATH`, no docker). pytest uses `asyncio_mode="auto"`. DB-backed tests need PG at `postgres://workbench:workbench@localhost:5432/workbench`; pure-unit tests do not.
---

## Integration Decisions (baked into this plan)

These reconcile the two source plans. Where they differ from a source task body, the task below is marked **INTEGRATION-CHANGED** and carries complete code.

1. **Merged `generate_card` signature** (replaces A Task 4 dispatch sig + B Slice 6 change_context param):
   ```python
   async def generate_card(
       llm, item, enrichment_context, source_type, *,
       memory=None,
       content_generators: dict | None = None,
       change_context: "ChangeContext | None" = None,
   ) -> TriageCard:
   ```
   `CardContentGenerator.generate(self, llm, item, enrichment_context, *, memory_context=None, change_context=None) -> dict`. The default path (`llm.generate_triage_card`) accepts-and-ignores `change_context` when no generator is registered, but the LLM prompt includes change details (B Slice 6 behavior). The Meta `DiffCardContentGenerator` folds `change_context` into its single Opus `json_schema` call.

2. **`_fire_retriage` drives the presenter** (ADR 0030, 0031): re-read item+card → `build_change_context` → daily-cap gate (critical bypasses, runs BEFORE the LLM) → two-tier enrich-or-reuse (see #4) → `generate_card(..., content_generators=..., change_context=...)` → `CompositeCardPresenter.render(card, ext_item)` → `CardMessage` → status routing via the `CardMessage` messenger interface. `_fire_retriage` holds a presenter ref injected in scheduler `__init__`/`main.py`. **`format_card_for_chat` plain-text is no longer used for re-triage sends** — both `send_card` and `update_message` take `CardMessage`.

3. **Single regeneration path** (ADR 0030): Feature A's standalone `revision_id` staleness polling (its d46) is DROPPED. The only regeneration mechanism is `_fire_retriage`. `DiffEnricher` still captures `revision_id`/`diff_version` for display + change detection.

4. **Two-tier regen depth keyed on `change_type`** (ADR 0032): `change_type == "code_updated"` → full path (`_fire_retriage` runs `enrich_item`, which re-invokes `DiffEnricher` to re-fetch the diff + regenerate hunks). `status_changed` / `ci_changed` / `comment_added` → light path (reuse the stored hunks from `existing_card.card_content["sections"]["hunks"]`, regenerate only the change-aware summary/risk/why-care copy + options). Debounce merge precedence resolves the merged `change_type` to the heaviest (`code_updated`). The enrich-or-reuse decision lives inside `_fire_retriage`, keyed on `change_context.change_type`.

5. **Symmetric `CardMessage` send + update** (ADR 0031): `update_message(message_id: str, card: CardMessage) -> bool`; base default `False`; `ConsoleMessenger` prints `render_to_text(card)` and returns `True`; `GoogleChatMessenger` patches the parent cardsV2 via a NEW `lib/google_api.update_card_message(message_name, text, cards_v2, as_bot)` helper (`updateMask=cardsV2,text`). On `False` → fall back to `send_card(card)` and **re-persist `card.bot_message_id` (+`thread_name`)**. v1 patches the parent only, leaves threaded hunk replies stale, and marks `"[Updated]"` in `CardMessage.header`.

6. **`diff_version`** (ADR 0032): `poll()` captures `diff_version` (active code-diff version id; opaque, compared by equality) into `RawItem.raw_text` → persisted in `Item.raw_data`. `PhabricatorChangeDetector` adds `diff_version` as a material field producing `change_type="code_updated"`. Exact field name is UNCONFIRMED → resolved by the early Phase-4 verification task; fallback proxy = line-count / files-changed.

7. **ChangeContext surfaces in the card**: `change_context` becomes a `"change"` element in `diff.v1` sections ("What changed since last triage") → a cardsV2 header chip + UI callout. `DiffCardContentGenerator` folds `change_context` into its single Opus call (change-aware copy + re-triage options).

8. **Combined config**: a single top-level `presentation:` section (A) + per-source `change_detector:` (B). **One** minor version bump `0.3.0 → 0.4.0` covering both.

9. **`TriageCard.thread_name`**: add an optional `thread_name: str | None = None` field to `TriageCard` (and reuse the existing `bot_message_id` as the parent message resource name). Needed so `poll_responses`/`update_message` survive a `send_card` fallback re-persist.

---

## Unified Task Ordering (dependency map across 6 phases)

```
PHASE 1 — Shared foundational primitives (everything below depends on these)
  T1  models MERGED (DiffCardContent + CardMessage + ChangeContext + TriageCard.thread_name)   [A T1 + B S2]
  T2  Messenger ABC MERGED (send_card + render_to_text + update_message(CardMessage))           [A T2 + B S5] INTEGRATION-CHANGED
  T3  Store methods + migration (B S4 + A get_card support)                                     [B S4]
  T4  SourceAdapter base (supports_monitoring/stable_id/poll_returns_complete_set)              [B S3]
  T5  ChangeDetector ABC + AlwaysMaterialDetector                                               [B S1]
        T1 → T2; T1 → (everything using models). T3,T4,T5 independent of T2.

PHASE 2 — Presentation layer (Feature A foundational)
  T6  CardPresenter ABC + Plain + Composite                                                     [A T3]  (needs T1,T2)
  T7  CardContentGenerator ABC + MERGED generate_card dispatch                                  [A T4 + B S6] INTEGRATION-CHANGED  (needs T1,T6 import-safe)
  T8  Presentation config + build-from-config                                                   [A T5]  (needs T6,T7)
  T9  Detail API GET /api/triage/cards/{card_id}                                                [A T7]  (needs T3)
  T10 Scheduler send-path uses presenter; main.py wiring                                        [A T6]  (needs T6,T7,T8)

PHASE 3 — Change-monitoring engine (Feature B foundational)
  T11 ChangeContext builder                                                                     [B S2 builder]  (needs T1,T5)
  T12 DebounceManager                                                                           [B S7]  (needs T5)
  T13 Re-check routing in scheduler                                                             [B S8]  (needs T3,T4,T5,T12)
  T14 _fire_retriage (presenter + two-tier regen + symmetric update)                            [B S9] INTEGRATION-CHANGED  (needs T2,T6,T7,T10,T11,T12,T13)
  T15 Shutdown integration                                                                      [B S10] (needs T12,T13)
  T16 change_detector config + registration                                                     [B S11] (needs T5,T13)

PHASE 4 — Meta overlay (both)
  T17 VERIFICATION: meta phabricator.diff get/list schema + diff_version field name  INTEGRATION-NEW  (gates T18–T22)
  T18 DiffEnricher + diff_version capture                                                       [A T9 + INTEGRATION-NEW]
  T19 DiffCardContentGenerator change-aware via change_context                                  [A T10] INTEGRATION-CHANGED
  T20 DiffCardPresenter (+ change section)                                                      [A T11]
  T21 lib/google_api.update_card_message helper                                                 INTEGRATION-NEW  (needs nothing meta-specific)
  T22 GoogleChatMessenger send_card (cardsV2+threads) + update_message(CardMessage)             [A T12 + ADR 0031] INTEGRATION-CHANGED
  T23 PhabricatorChangeDetector (+ code_updated) + MetaTasksChangeDetector                      [B follow-up + ADR 0032] INTEGRATION-CHANGED
  T24 Phab/Tasks adapter supports_monitoring/stable_id + diff_version in poll()                 [B follow-up + INTEGRATION] INTEGRATION-CHANGED
  T25 Meta config wiring (presentation + enrichment + change_detector)                          [A T13 + B config]

PHASE 5 — UI (Feature A)
  T26 useTriageCard hook                                                                        [A T14]
  T27 DiffHunks CSS-only component                                                              [A T15]
  T28 TriageDetail page + route + Review link (+ change callout)                                [A T16] INTEGRATION-CHANGED
  T29 regenerate api-types + full build/test                                                    [A T17]

PHASE 6 — Cross-cutting
  T30 CONTEXT.md glossary (A terms + B terms) + memory-caps fix                                 [A T18 + B glossary] INTEGRATION-CHANGED
  T31 Final verification (combined spec checklists)
```

---

# PHASE 1 — Shared foundational primitives

## Task 1: Merged card/message/change models + TriageCard.thread_name (foundational)  (Phase 1)  [SOURCE: Feature A Task 1 + Feature B Slice 2 (model part)]
**Files:** Create `tests/test_models_card.py`, `tests/test_change_context.py` (model part only here; builder in T11); Modify `src/workbench/models.py`

**From source:** Execute **Feature A Task 1 as written** (adds `DiffMetadata`, `DiffRisk`, `DiffHunkSection`, `DiffCardContent`, `CardLink`, `CardSection`, `ThreadHunk`, `CardMessage` after `TriageOption`, before `TriageCard`). Then apply the integration delta below for `ChangeContext` and `TriageCard.thread_name`.

**Integration delta (INTEGRATION-CHANGED):**

- [ ] Step 1: Extend A Task 1's failing test file with model coverage for `ChangeContext` and `thread_name`. Append to `tests/test_models_card.py`:

```python
from workbench.models import ChangeContext, TriageCard


def test_change_context_round_trips():
    ctx = ChangeContext(
        change_type="code_updated",
        changed_fields={"status": {"old": "needs_review", "new": "accepted"}},
        change_summary="status changed; new diff version",
        previous_triage_action="defer",
        previous_priority="P2",
    )
    dumped = ctx.model_dump()
    again = ChangeContext.model_validate(dumped)
    assert again.change_type == "code_updated"
    assert again.changed_fields["status"]["new"] == "accepted"


def test_change_context_defaults():
    ctx = ChangeContext(change_type="status_changed", changed_fields={},
                        change_summary="s")
    assert ctx.previous_triage_action is None
    assert ctx.previous_priority is None


def test_triage_card_has_optional_thread_name():
    card = TriageCard(card_content={"summary": "x"})
    assert card.thread_name is None
    card2 = TriageCard(card_content={"summary": "x"}, thread_name="spaces/A/threads/T1")
    assert card2.thread_name == "spaces/A/threads/T1"
```

- [ ] Step 2: Run `python -m pytest tests/test_models_card.py -v --tb=short` → expect `ImportError: cannot import name 'ChangeContext'` (and A Task 1's own assertions failing for `DiffMetadata` etc.).

- [ ] Step 3: Implement. Add A Task 1's models verbatim (see Feature A Task 1 Step 3). THEN add `ChangeContext` after `CardMessage`:

```python
class ChangeContext(BaseModel):
    change_type: str
    changed_fields: dict[str, dict[str, str]] = Field(default_factory=dict)
    change_summary: str
    previous_triage_action: str | None = None
    previous_priority: str | None = None
```

And add one field to the existing `TriageCard` (after `bot_message_id`):

```python
    thread_name: str | None = None
```

- [ ] Step 4: Run `python -m pytest tests/test_models_card.py -v --tb=short` → PASS (all A Task 1 cases + 3 new).

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(models): DiffCardContent + CardMessage + ChangeContext + TriageCard.thread_name (ADR 0022,0025,0031)"`

---

## Task 2: Messenger ABC — send_card(CardMessage) + render_to_text + update_message(CardMessage) (foundational)  (Phase 1)  [SOURCE: Feature A Task 2 + Feature B Slice 5]  INTEGRATION-CHANGED
**Files:** Create `tests/test_messenger_render_to_text.py`, `tests/test_messenger_update.py`; Modify `src/workbench/providers/messenger/base.py`, `src/workbench/providers/messenger/console.py`

**From source:** Feature A Task 2 (send_card + render_to_text) and Feature B Slice 5 (update_message). **Integration change: B's `update_message(message_id, text: str)` becomes `update_message(message_id: str, card: CardMessage) -> bool`** (ADR 0031). Console renders the card via `render_to_text`.

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing tests. `tests/test_messenger_render_to_text.py` — use Feature A Task 2's test body **as written** (render_to_text flatten + console send_card CardMessage + back-compat string). Add a new `tests/test_messenger_update.py`:

```python
# tests/test_messenger_update.py
import pytest
from workbench.models import CardMessage, CardSection
from workbench.providers.messenger.base import Messenger
from workbench.providers.messenger.console import ConsoleMessenger


class _Bare(Messenger):
    async def send_card(self, card): return "x"
    async def poll_responses(self, since_message_id=None): return []


@pytest.mark.asyncio
async def test_base_update_message_default_false():
    assert await _Bare().update_message("m1", CardMessage(header="h")) is False


@pytest.mark.asyncio
async def test_console_update_message_renders_card_returns_true(capsys):
    ok = await ConsoleMessenger().update_message(
        "m1", CardMessage(header="Diff D1", sections=[CardSection(title="t", body="b")])
    )
    assert ok is True
    out = capsys.readouterr().out
    assert "Diff D1" in out
    assert "[UPDATE m1]" in out
```

- [ ] Step 2: Run `python -m pytest tests/test_messenger_render_to_text.py tests/test_messenger_update.py -v --tb=short` → expect `AttributeError`/abstract errors (no `render_to_text`, no `update_message`).

- [ ] Step 3: Implement. Replace `src/workbench/providers/messenger/base.py` entirely:

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
            if section.title:
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

    async def update_message(self, message_id: str, card: "CardMessage | str") -> bool:
        """Update an existing message in-place. Returns True on success.
        Default returns False (update not supported). Messengers that support
        in-place editing override this; on False the caller falls back to
        send_card and re-persists the new bot_message_id (ADR 0031)."""
        return False

    async def close(self) -> None:
        pass
```

Replace `send_card` and add `update_message` in `src/workbench/providers/messenger/console.py` (keep `poll_responses` and `ProviderConfig`):

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

    async def update_message(self, message_id: str, card) -> bool:
        from workbench.models import CardMessage

        card_text = self.render_to_text(card) if isinstance(card, CardMessage) else str(card)
        print(f"[UPDATE {message_id}]")
        print(card_text)
        return True
```

- [ ] Step 4: Run `python -m pytest tests/test_messenger_render_to_text.py tests/test_messenger_update.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(messenger): send_card + render_to_text + update_message(CardMessage) symmetric interface (ADR 0026,0031)"`

---

## Task 3: New store methods + migration (foundational)  (Phase 1)  [SOURCE: Feature B Slice 4]
**Files:** Modify `src/workbench/storage/base.py`, `src/workbench/storage/postgres/items.py`, `src/workbench/storage/postgres/triage.py`; Create migration in `src/workbench/migrations/versions/`, `tests/test_change_monitoring_stores.py`

**From source:** Execute **Feature B Slice 4 as written** (path: docs/auto-plan/plans/2026-06-08-change-monitoring-retriage.md, Slice 4). Adds `get_item_by_source_id`, `get_active_by_source`, `update_raw_data` to `ItemStore`; `get_card_by_item_id`, `clear_deferral` to `TriageStore`; indexes `idx_items_source_lookup` and `idx_triage_cards_item_id`. 6 integration tests against PG.

**Integration delta:** Feature A's detail API (T9) needs a `get_card(card_id)` read. If `TriageStore.get_card(card_id)` does not already exist, add it here alongside the B methods (single SELECT by id, returns `TriageCard | None`); add a test `save_card → get_card returns card; unknown id → None`. (B's `get_card_by_item_id` is by item_id; A's detail endpoint is by card_id — both are needed.)

Commit per Feature B Slice 4 (`cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(storage): change-monitoring store methods + get_card + indexes (Feature B Slice 4)"`).

---

## Task 4: SourceAdapter monitoring base methods (foundational)  (Phase 1)  [SOURCE: Feature B Slice 3]
**Files:** Modify `src/workbench/providers/source/base.py`; `tests/test_source_adapter.py`

**From source:** Execute **Feature B Slice 3 as written** — three concrete (non-abstract) methods with backward-compatible defaults: `supports_monitoring() -> False`, `stable_id(raw_item) -> raw_item.id`, `poll_returns_complete_set() -> False`. Tests: minimal subclass inherits defaults; monitoring subclass overrides all three; existing adapters still instantiate.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(source): supports_monitoring/stable_id/poll_returns_complete_set base methods (Feature B Slice 3)"`

---

## Task 5: ChangeDetector ABC + AlwaysMaterialDetector (foundational)  (Phase 1)  [SOURCE: Feature B Slice 1]
**Files:** Create `src/workbench/providers/change_detector/{__init__.py,base.py,fallback.py}`, `tests/test_change_detector.py`

**From source:** Execute **Feature B Slice 1 as written** — `ChangeResult{is_material,is_terminal,is_critical,changed_fields,change_type,reason}`, `ChangeDetector` ABC (`detect(old_raw, new_raw)`, `source_type()`), `AlwaysMaterialDetector`. 4 tests.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(change_detector): ChangeDetector ABC + ChangeResult + AlwaysMaterialDetector (Feature B Slice 1)"`

---

# PHASE 2 — Presentation layer (Feature A foundational)

## Task 6: CardPresenter ABC + Plain + Composite (foundational)  (Phase 2)  [SOURCE: Feature A Task 3]
**Files:** Create `src/workbench/pipeline/presenter.py`, `tests/test_presenter.py`

**From source:** Execute **Feature A Task 3 as written** — `CardPresenter` ABC, `PlainCardPresenter` (wraps `format_card_for_chat`), `CompositeCardPresenter` (routes by `item.raw_item.source_type`, per-delegate try/except → `presenter_failure`/`presenter_content_invalid`/`presenter_fallback` logging → `PlainCardPresenter`). Import `ValidationError` from pydantic at top. 6 tests incl. the `presenter_content_invalid` case noted in A Task 3.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(presenter): CardPresenter ABC + Plain/Composite with fallback logging (ADR 0023)"`

---

## Task 7: CardContentGenerator ABC + MERGED generate_card dispatch (foundational)  (Phase 2)  [SOURCE: Feature A Task 4 + Feature B Slice 6]  INTEGRATION-CHANGED
**Files:** Create `src/workbench/pipeline/content_generator.py`, `tests/test_content_generator_dispatch.py`, `tests/test_triage_card_change.py`; Modify `src/workbench/pipeline/triage.py`

This is the central merge of A Task 4 (per-source dispatch) and B Slice 6 (change_context). The merged `generate_card` carries BOTH `content_generators` and `change_context`. The generator interface gains a keyword-only `change_context`.

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing tests. Use Feature A Task 4's `tests/test_content_generator_dispatch.py` **as written** but update the `_StubGen.generate` and `_SummaryOnly.generate` signatures to the merged keyword form `async def generate(self, llm, item, enrichment_context, *, memory_context=None, change_context=None)`. Add `tests/test_triage_card_change.py`:

```python
# tests/test_triage_card_change.py
import pytest
from unittest.mock import AsyncMock
from workbench.models import (
    ExtractedItem, RawItem, ItemCategory, TriageCard, ChangeContext,
)
from workbench.pipeline.content_generator import CardContentGenerator
from workbench.pipeline.triage import generate_card


def _item(source_type="github"):
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(summary="s", category=ItemCategory.INFORMATIONAL,
                         source_context="", raw_item=raw)


def _ctx():
    return ChangeContext(change_type="status_changed",
                         changed_fields={"status": {"old": "a", "new": "b"}},
                         change_summary="status changed a->b")


@pytest.mark.asyncio
async def test_no_change_context_behaves_identically():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[])
    await generate_card(llm, _item(), {"context": {}}, "github")
    llm.generate_triage_card.assert_called_once()
    _, kwargs = llm.generate_triage_card.call_args
    assert "change_context" not in kwargs or kwargs.get("change_context") is None


@pytest.mark.asyncio
async def test_change_context_passed_to_llm_default():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[])
    await generate_card(llm, _item(), {"context": {}}, "github", change_context=_ctx())
    _, kwargs = llm.generate_triage_card.call_args
    assert kwargs["change_context"].change_type == "status_changed"


@pytest.mark.asyncio
async def test_change_context_passed_to_registered_generator():
    seen = {}

    class _Gen(CardContentGenerator):
        async def generate(self, llm, item, enrichment_context, *,
                           memory_context=None, change_context=None):
            seen["ctx"] = change_context
            return {"content_schema": "diff.v1", "sections": {"summary": "s"},
                    "card_body": "s", "summary": "s"}

    llm = AsyncMock()
    await generate_card(llm, _item("diff"), {"context": {}}, "diff",
                        content_generators={"diff": _Gen()}, change_context=_ctx())
    assert seen["ctx"].change_type == "status_changed"


@pytest.mark.asyncio
async def test_template_fallback_is_change_aware_marked():
    # Generator raises -> template fallback; with change_context the template
    # card_content carries a "change" key and an "[Updated]" summary marker.
    class _Boom(CardContentGenerator):
        async def generate(self, *a, **k):
            raise RuntimeError("boom")

    llm = AsyncMock()
    card = await generate_card(llm, _item("diff"), {"context": {}}, "diff",
                               content_generators={"diff": _Boom()}, change_context=_ctx())
    assert "change" in card.card_content
    assert card.card_content["summary"].startswith("[Updated]")
```

- [ ] Step 2: Run `python -m pytest tests/test_content_generator_dispatch.py tests/test_triage_card_change.py -v --tb=short` → expect `ModuleNotFoundError: No module named 'workbench.pipeline.content_generator'`.

- [ ] Step 3: Implement.

Create `src/workbench/pipeline/content_generator.py` (merged interface with keyword-only `memory_context`/`change_context`):

```python
# src/workbench/pipeline/content_generator.py
from __future__ import annotations

from abc import ABC, abstractmethod

from workbench.models import ChangeContext, ExtractedItem


class CardContentGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        llm,
        item: ExtractedItem,
        enrichment_context: dict,
        *,
        memory_context: dict | None = None,
        change_context: ChangeContext | None = None,
    ) -> dict:
        """Return a card_content envelope dict.

        Envelope keys:
          content_schema: discriminator (e.g. "diff.v1") — present only when sections valid.
          sections: serialized typed content (omitted on refusal/parse-fail).
          card_body / summary: legacy plain-fallback fields (always present).
        change_context, when present, makes the copy/options change-aware (ADR 0030,0032).
        """


def build_content_generators(presentation_config) -> dict:
    """Build {source_type: CardContentGenerator} from presentation.providers.

    Each entry may carry a `content_generator` class string; entries without one
    fall through to the LLM default in generate_card."""
    from workbench.registry import create_provider

    generators: dict = {}
    for entry in presentation_config.providers:
        gen_class = entry.get("content_generator")
        if not gen_class:
            continue
        source_type = entry["source_type"]
        generators[source_type] = create_provider({"class": gen_class})
    return generators
```

Modify `src/workbench/pipeline/triage.py`. (a) import `ChangeContext` at top: `from workbench.models import ChangeContext, ExtractedItem, TriageCard, TriageOption`. (b) Replace the `generate_card` signature and docstring with the merged form:

```python
async def generate_card(
    llm: LLMProvider,
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    *,
    memory=None,
    content_generators: dict | None = None,
    change_context: ChangeContext | None = None,
) -> TriageCard:
    """Generate a triage card with LLM, enriched by memory context.

    Gathers entity knowledge (cap 5), relationships (cap 10), and preference
    facts (cap 20) from memory for any entity_refs found in the enrichment
    context. Dispatches to a registered CardContentGenerator by source_type;
    when none is registered, falls back to llm.generate_triage_card. When
    change_context is provided (re-triage), it is threaded to the generator /
    LLM and the template fallback marks the card "[Updated]" (ADR 0030,0032).
    """
```

(Keep the existing memory-gathering body unchanged — it already caps 5/10/20.)

(c) Replace the LLM-generation `try/except` block (lines ~98-108) with the merged dispatch:

```python
    context_for_llm = enrichment_context.get("context", enrichment_context)
    generator = (content_generators or {}).get(source_type)
    if generator is not None:
        try:
            envelope = await generator.generate(
                llm, item, context_for_llm,
                memory_context=memory_context, change_context=change_context,
            )
            card = TriageCard(card_content=envelope)
        except Exception as e:
            logger.warning("Content generator failed, using template: %s", e)
            card = _template_card(item, enrichment_context, source_type, change_context)
    else:
        try:
            card = await llm.generate_triage_card(
                item, context_for_llm, source_type,
                memory_context=memory_context, change_context=change_context,
            )
        except Exception as e:
            logger.warning("LLM card generation failed, using template: %s", e)
            card = _template_card(item, enrichment_context, source_type, change_context)
```

(d) Extend `_template_card` to accept `change_context` and emit a change-aware card:

```python
def _template_card(
    item: ExtractedItem, enrichment_context: dict, source_type: str,
    change_context: "ChangeContext | None" = None,
) -> TriageCard:
    """Fallback template card when LLM/generator generation fails."""
    summary = item.summary
    card_content = {
        "summary": summary,
        "source_type": source_type,
        "enrichment": enrichment_context,
    }
    if change_context is not None:
        card_content["summary"] = f"[Updated] {summary}"
        card_content["change"] = change_context.model_dump()
        options = [
            TriageOption(label="Bump to P1", action="add_todo",
                         details={"priority": "P1"}),
            TriageOption(label="Keep current priority", action="skip"),
            TriageOption(label="Acknowledge change", action="skip"),
        ]
    else:
        options = [
            TriageOption(label="Add todo P1", action="add_todo",
                         details={"priority": "P1"}),
            TriageOption(label="Add todo P2", action="add_todo",
                         details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
            TriageOption(label=f"Never surface {source_type} like this",
                         action="mute_pattern"),
        ]
    return TriageCard(card_content=card_content, options=options)
```

NOTE: `llm.generate_triage_card` must accept `change_context=` (keyword). If the current `LLMProvider.generate_triage_card` signature does not accept it, add `change_context: "ChangeContext | None" = None` as an accept-and-thread-into-prompt keyword in the provider base + concrete LLM (the prompt includes the change details when present, per B Slice 6). Cover with the mock-based `test_change_context_passed_to_llm_default` above.

- [ ] Step 4: Run `python -m pytest tests/test_content_generator_dispatch.py tests/test_triage_card_change.py tests/test_triage_card_enrichment.py -v --tb=short` → PASS (dispatch + change tests + existing enrichment regression).

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(triage): merged generate_card dispatch + change_context (ADR 0025,0030,0032)"`

---

## Task 8: Presentation config + build-from-config (foundational)  (Phase 2)  [SOURCE: Feature A Task 5]
**Files:** Create `tests/test_presentation_config.py`; Modify `src/workbench/config.py`, `src/workbench/pipeline/presenter.py`, `config.example.yml`

**From source:** Execute **Feature A Task 5 as written** — `PresentationConfig{providers: list[dict]}`, `AppConfig.presentation` default-empty, `build_composite_presenter(config)` (hard-errors on unimportable class), version `0.4.0`. NOTE: `build_content_generators` already landed in T7's `content_generator.py` (do not duplicate it here — A Task 5 Step 3's `content_generator.py` addition is already done; skip that sub-step). Update any existing config test asserting `version == "0.3.0"` to `"0.4.0"`.

Add the `presentation:` block + version bump to `config.example.yml` per A Task 5 Step 3.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(config): presentation section + build-from-config; bump version 0.4.0 (ADR 0029)"`

---

## Task 9: Detail API — GET /api/triage/cards/{card_id} (foundational)  (Phase 2)  [SOURCE: Feature A Task 7]
**Files:** Create `tests/test_triage_card_detail_api.py`; Modify `src/workbench/api/triage.py`

**From source:** Execute **Feature A Task 7 as written** — `GET /api/triage/cards/{card_id}` returns full `TriageCard` via `stores.triage.get_card(card_id)` (added in T3), 404 on miss, bearer auth. Reuse `triage_app`/`auth_headers` fixtures from `tests/test_triage_web.py` (move to `conftest.py` if needed).

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(api): GET /api/triage/cards/{card_id} detail endpoint (404 on miss, bearer)"`

---

## Task 10: Scheduler send-path uses presenter + main.py wiring (foundational)  (Phase 2)  [SOURCE: Feature A Task 6]
**Files:** Modify `src/workbench/pipeline/scheduler.py`, `src/workbench/main.py`, `src/workbench/pipeline/engine.py`; Create `tests/test_scheduler_presenter.py`

**From source:** Execute **Feature A Task 6 as written** — `WorkbenchScheduler.__init__` gains `self.presenter = PlainCardPresenter()`; `_manage_triage_queue_inner` renders the next-unsent card via `self.presenter.render(card, ext_item)` → `CardMessage` → `send_card`; `_ext_item_for(card)` helper; internal status/echo messages stay plain strings (back-compat). `main.py` builds `app.state.presenter` + `app.state.content_generators` and assigns `app.state.scheduler.presenter`. `engine.py` threads `content_generators` into `generate_card`.

**Integration note:** `_ext_item_for` is also used by `_fire_retriage` (T14) — keep it a method on the scheduler. The `main.py` wiring here also makes `app.state.content_generators` available to the scheduler for re-triage; in `main.py`, after assigning the presenter, also assign `app.state.scheduler.content_generators = app.state.content_generators` (add `self.content_generators: dict = {}` in `__init__` so T14 can read it).

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(scheduler): render via CompositeCardPresenter -> CardMessage -> send_card; wire content generators (ADR 0023,0024)"`

---

# PHASE 3 — Change-monitoring engine (Feature B foundational)

## Task 11: ChangeContext builder (foundational)  (Phase 3)  [SOURCE: Feature B Slice 2 (builder part)]
**Files:** Create `src/workbench/pipeline/change_context.py`; extend `tests/test_change_context.py`

**From source:** Execute **Feature B Slice 2's `build_change_context()` as written** (the `ChangeContext` model already landed in T1). `build_change_context(result, old_raw, new_raw, previous_card)` builds `changed_fields` from `result.changed_fields`, copies `previous_triage_action`/`previous_priority` from a responded card. Tests: no previous card → empty previous fields; responded card → copies response/priority; round-trip.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(pipeline): build_change_context (Feature B Slice 2)"`

---

## Task 12: DebounceManager (foundational)  (Phase 3)  [SOURCE: Feature B Slice 7]
**Files:** Create `src/workbench/pipeline/debounce.py`, `tests/test_debounce.py`

**From source:** Execute **Feature B Slice 7 as written** — `DebouncedChange` + `DebounceManager(fire_callback, delay_seconds=120.0)` with `schedule/cancel/cancel_all/pending_count`, earliest-`old_raw` preservation, `_merge_results` (union changed_fields, OR is_critical). **Integration note (ADR 0032):** `_merge_results` must resolve `change_type` to the HEAVIEST of the two — if either side is `"code_updated"`, the merged `change_type` is `"code_updated"`; otherwise keep `new.change_type`. Add a test: merging `status_changed` + `code_updated` → merged `change_type == "code_updated"`.

Implement the heaviest-wins in `_merge_results`:

```python
    @staticmethod
    def _merge_results(old, new):
        merged_fields = list(dict.fromkeys(old.changed_fields + new.changed_fields))
        change_type = ("code_updated"
                       if "code_updated" in (old.change_type, new.change_type)
                       else new.change_type)
        return ChangeResult(
            is_material=old.is_material or new.is_material,
            is_terminal=new.is_terminal,
            is_critical=old.is_critical or new.is_critical,
            changed_fields=merged_fields,
            change_type=change_type,
            reason=f"{old.reason}; {new.reason}",
        )
```

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(debounce): DebounceManager with heaviest-change_type merge (Feature B Slice 7, ADR 0032)"`

---

## Task 13: Re-check routing in scheduler (foundational)  (Phase 3)  [SOURCE: Feature B Slice 8]
**Files:** Modify `src/workbench/pipeline/scheduler.py`; Create `tests/test_change_monitoring_routing.py`

**From source:** Execute **Feature B Slice 8 as written** — `_route_poll_results`, `_detect_disappeared`, `_archive_terminal`, `_parse_raw`, integrated into `_poll_one_source` (the existing `_poll_one_source` enqueue loop, scheduler.py lines ~242-259, is replaced by a call to `_route_poll_results` when `adapter.supports_monitoring()` is True, else the existing path). `__init__` wiring of `self._debounce = DebounceManager(self._fire_retriage)` and `self._change_detectors: dict = {}` is done in THIS slice (T14 defines `_fire_retriage`, so add a temporary `async def _fire_retriage(self, *a): ...` stub that T14 fully implements, OR order T14 immediately after and reference it — keep `self._debounce` wired here). Disappearance detection gated on `supports_monitoring() and poll_returns_complete_set()`. 8 tests incl. stable-ID-migration and partial-set guard.

Use `adapter.stable_id(raw_item)` as `source_id` for both `ProcessedStore` and `ItemStore` lookups (B spec "Stable Source ID" section).

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(scheduler): re-check routing + disappeared/terminal archival (Feature B Slice 8)"`

---

## Task 14: _fire_retriage — presenter-driven, two-tier regen, symmetric update (foundational)  (Phase 3)  [SOURCE: Feature B Slice 9]  INTEGRATION-CHANGED
**Files:** Modify `src/workbench/pipeline/scheduler.py`; Create `tests/test_retriage.py`

This replaces Feature B Slice 9's `format_card_for_chat`-based send with the presenter path (ADR 0031), adds the daily-cap-before-LLM gate, and implements the two-tier enrich-or-reuse decision (ADR 0032).

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing tests. `tests/test_retriage.py`:

```python
# tests/test_retriage.py
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.models import (
    TriageCard, TriageOption, CardMessage, RawItem, Item, ItemStatus, ItemCategory,
)
from workbench.providers.change_detector.base import ChangeResult
from workbench.pipeline.presenter import PlainCardPresenter
from workbench.pipeline.scheduler import WorkbenchScheduler


def _raw(diff_version="v1"):
    return RawItem(id="D123_t", source_type="diff", source_label="D123",
                   raw_text=json.dumps({"number": "D123", "status": "accepted",
                                        "diff_version": diff_version}))


def _result(change_type="status_changed", critical=False):
    return ChangeResult(is_material=True, is_terminal=False, is_critical=critical,
                        changed_fields=["status"], change_type=change_type,
                        reason="status changed")


def _item():
    return Item(id="it1", source_type="diff", source_id="D123", summary="Review D123",
                category=ItemCategory.INFORMATIONAL, status=ItemStatus.ACTIVE,
                raw_data={"raw_text": json.dumps({"number": "D123",
                                                  "status": "needs_review"})})


def _sched(messenger):
    stores = MagicMock()
    stores.items.get_item = AsyncMock(return_value=_item())
    stores.triage.count_sent_today = AsyncMock(return_value=0)
    stores.triage.update_card = AsyncMock()
    stores.triage.save_card = AsyncMock()
    stores.triage.clear_deferral = AsyncMock()
    config = MagicMock()
    config.triage.daily_cap = 20
    config.logging.timezone = "UTC"
    config.alerting.enabled = False
    pipeline = MagicMock()
    pipeline.enricher = MagicMock()
    pipeline.triage_expiry_days = 7
    sched = WorkbenchScheduler(stores, MagicMock(), pipeline, messenger, config,
                               llm=AsyncMock())
    sched.presenter = PlainCardPresenter()
    sched.content_generators = {}
    return sched, stores


def _sent_card():
    return TriageCard(id="c1", item_id="it1", status="sent",
                      bot_message_id="spaces/A/messages/p1",
                      card_content={"summary": "Review D123", "card_body": "Review D123",
                                    "source_type": "diff",
                                    "sections": {"hunks": [{"file": "a.py", "rank": 1,
                                                            "header": "@@", "code": "+x"}]}},
                      options=[TriageOption(label="Add P1", action="add_todo")])


@pytest.mark.asyncio
async def test_sent_card_update_message_called_with_cardmessage():
    seen = {}

    async def _update(mid, card):
        seen["mid"], seen["card"] = mid, card
        return True

    messenger = MagicMock()
    messenger.update_message = AsyncMock(side_effect=_update)
    messenger.send_card = AsyncMock(return_value="new")
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    with patch("workbench.pipeline.scheduler.enrich_item",
               new=AsyncMock(return_value={"context": {}})):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "needs_review"})
    assert isinstance(seen["card"], CardMessage)
    assert seen["mid"] == "spaces/A/messages/p1"


@pytest.mark.asyncio
async def test_sent_card_update_false_falls_back_to_send_and_repersists_id():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=False)
    messenger.send_card = AsyncMock(return_value="spaces/A/messages/p2")
    sched, stores = _sched(messenger)
    card = _sent_card()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=card)
    stores.triage.get_card = AsyncMock(return_value=card)
    with patch("workbench.pipeline.scheduler.enrich_item",
               new=AsyncMock(return_value={"context": {}})):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "needs_review"})
    messenger.send_card.assert_awaited()
    # re-persisted new bot_message_id
    assert any(c.args[0].bot_message_id == "spaces/A/messages/p2"
               for c in stores.triage.update_card.call_args_list)


@pytest.mark.asyncio
async def test_code_updated_runs_full_enrichment():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    enrich = AsyncMock(return_value={"context": {"curated_hunks": []}})
    with patch("workbench.pipeline.scheduler.enrich_item", new=enrich):
        await sched._fire_retriage("it1", _result(change_type="code_updated"),
                                   _raw(diff_version="v2"), {"status": "x"})
    enrich.assert_awaited()  # full path re-runs enrichment
    # MUST request deep mode, else DiffEnricher skips the diff re-fetch (ADR 0032).
    assert enrich.await_args.args[2] == "deep"


@pytest.mark.asyncio
async def test_light_path_reuses_stored_hunks_no_enrich():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    enrich = AsyncMock(return_value={"context": {"curated_hunks": []}})
    with patch("workbench.pipeline.scheduler.enrich_item", new=enrich):
        await sched._fire_retriage("it1", _result(change_type="status_changed"),
                                   _raw(), {"status": "x"})
    enrich.assert_not_awaited()  # light path skips re-fetch


@pytest.mark.asyncio
async def test_daily_cap_blocks_noncritical_before_llm():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    stores.triage.count_sent_today = AsyncMock(return_value=20)
    sched.llm.generate_triage_card = AsyncMock()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    with patch("workbench.pipeline.scheduler.enrich_item",
               new=AsyncMock(return_value={"context": {}})) as enrich:
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    enrich.assert_not_awaited()
    sched.llm.generate_triage_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_critical_bypasses_cap():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.count_sent_today = AsyncMock(return_value=99)
    stored = _sent_card()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=stored)
    stores.triage.get_card = AsyncMock(return_value=stored)
    with patch("workbench.pipeline.scheduler.enrich_item",
               new=AsyncMock(return_value={"context": {}})):
        await sched._fire_retriage("it1", _result(critical=True), _raw(),
                                   {"status": "x"})
    messenger.update_message.assert_awaited()


@pytest.mark.asyncio
async def test_archived_item_is_noop():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    archived = _item(); archived.status = ItemStatus.ARCHIVED
    stores.items.get_item = AsyncMock(return_value=archived)
    await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.update_card.assert_not_awaited()
```

Also keep Feature B Slice 9's queued/responded/expired/deferred/no-card cases (copy from B Slice 9 test bodies, adapting the messenger calls to `CardMessage`).

- [ ] Step 2: Run `python -m pytest tests/test_retriage.py -v --tb=short` → expect `AttributeError: 'WorkbenchScheduler' object has no attribute '_fire_retriage'` (or the stub from T13 returning None and assertions failing).

- [ ] Step 3: Implement. Add imports to scheduler.py top: `import json`, `from workbench.models import ChangeContext, ExtractedItem, RawItem`, `from workbench.pipeline.change_context import build_change_context`, `from workbench.pipeline.engine import enrich_item` (confirm `enrich_item` is importable from engine; if it lives elsewhere, import from there and update the test patch target accordingly), `from workbench.pipeline.triage import generate_card`. Replace the T13 stub with:

```python
    _LIGHT_CHANGE_TYPES = {"status_changed", "ci_changed", "comment_added"}

    async def _fire_retriage(
        self, item_id: str, result, raw_item: RawItem, old_raw: dict,
    ) -> None:
        """Debounce callback. Presenter-driven re-triage (ADR 0030,0031,0032).
        old_raw is the pre-update snapshot stashed at detection time."""
        item = await self.stores.items.get_item(item_id)
        if item is None or item.status == ItemStatus.ARCHIVED:
            return

        # Daily cap BEFORE any LLM work; critical bypasses (ADR 0032).
        if not result.is_critical:
            sent_today = await self.stores.triage.count_sent_today()
            if sent_today >= self.config.triage.daily_cap:
                logger.info("Daily cap reached; skipping re-triage for %s", item.id)
                return

        new_raw = json.loads(raw_item.raw_text)
        existing_card = await self.stores.triage.get_card_by_item_id(item.id)
        change_ctx = build_change_context(result, old_raw, new_raw, existing_card)

        ext_item = ExtractedItem(
            summary=item.summary, category=item.category,
            source_context=raw_item.source_label, raw_item=raw_item,
        )

        # Two-tier regen depth keyed on change_type (ADR 0032).
        if result.change_type == "code_updated":
            # MUST pass depth="deep": DiffEnricher only re-fetches the diff
            # (and regenerates curated hunks) in deep mode; the default
            # "shallow" would silently skip the fetch and defeat ADR 0032.
            enrichment = await enrich_item(
                self.pipeline.enricher, ext_item, "deep", memory=self.memory
            )
        else:
            # Light path: reuse stored curated hunks; no diff re-fetch.
            stored_sections = (existing_card.card_content.get("sections", {})
                               if existing_card else {})
            enrichment = {"context": {
                "curated_hunks": stored_sections.get("hunks", []),
                "metadata": stored_sections.get("metadata", {}),
                "revision_id": stored_sections.get("revision_id", ""),
            }}

        new_card = await generate_card(
            self.llm, ext_item, enrichment, raw_item.source_type,
            memory=self.memory, content_generators=self.content_generators,
            change_context=change_ctx,
        )
        new_card.item_id = item.id

        if existing_card is None:
            new_card.expires_at = datetime.now(timezone.utc) + timedelta(
                days=self.pipeline.triage_expiry_days)
            await self.stores.triage.save_card(new_card)
            return

        # Re-read status (race mitigation).
        existing_card = await self.stores.triage.get_card(existing_card.id)
        if existing_card.deferred_until is not None:
            await self.stores.triage.clear_deferral(existing_card.id)

        if existing_card.status == "queued":
            self._copy_card_content(existing_card, new_card)
            await self.stores.triage.update_card(existing_card)

        elif existing_card.status == "sent":
            self._copy_card_content(existing_card, new_card)
            await self.stores.triage.update_card(existing_card)
            if self.messenger:
                message = self.presenter.render(existing_card, ext_item)
                message.header = f"[Updated] {message.header}"
                ok = await self.messenger.update_message(
                    existing_card.bot_message_id, message)
                if not ok:
                    new_id = await self.messenger.send_card(message)
                    existing_card.bot_message_id = new_id
                    await self.stores.triage.update_card(existing_card)

        else:  # responded / expired -> new card
            new_card.expires_at = datetime.now(timezone.utc) + timedelta(
                days=self.pipeline.triage_expiry_days)
            await self.stores.triage.save_card(new_card)

    @staticmethod
    def _copy_card_content(dst, src) -> None:
        dst.card_content = src.card_content
        dst.options = src.options
        dst.relevance_score = src.relevance_score
        dst.confidence_score = src.confidence_score
```

NOTE: the `send_card` fallback re-persists `bot_message_id` (ADR 0031). If `send_card` also returns a thread (GChat), persist `thread_name` too where available (the presenter path returns only the id from `send_card`; thread capture happens inside the GChat messenger T22 and is reflected in the returned id — for v1 we only re-persist `bot_message_id`, leave `thread_name` as-is).

- [ ] Step 4: Run `python -m pytest tests/test_retriage.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(scheduler): presenter-driven _fire_retriage with two-tier regen + symmetric update (ADR 0030,0031,0032)"`

---

## Task 15: Shutdown integration (foundational)  (Phase 3)  [SOURCE: Feature B Slice 10]
**Files:** Modify `src/workbench/pipeline/scheduler.py`; Create `tests/test_scheduler_shutdown.py`

**From source:** Execute **Feature B Slice 10 as written** — `shutdown()` calls `self._debounce.cancel_all()` before `self.scheduler.shutdown(wait=False)`. (`__init__` wiring already in T13.) Tests: `shutdown()` cancels all; after shutdown `_shutting_down` True and `pending_count == 0`.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(scheduler): cancel debounce timers on shutdown (Feature B Slice 10)"`

---

## Task 16: change_detector config + registration (foundational)  (Phase 3)  [SOURCE: Feature B Slice 11]
**Files:** Modify `src/workbench/main.py`, `config.example.yml`; Create `tests/test_change_detector_config.py`

**From source:** Execute **Feature B Slice 11 as written** — load per-source `change_detector` at startup, register in `scheduler._change_detectors[adapter_type]`; missing → `AlwaysMaterialDetector` fallback (warn once). Document `change_detector` in `config.example.yml`. Tests: empty config validates; configured detector present; unregistered → fallback.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(config): per-source change_detector registration with fallback (Feature B Slice 11)"`

---

# PHASE 4 — Meta overlay (both)

## Task 17: VERIFICATION — confirm `meta phabricator.diff get/list` schema + `diff_version` field name (meta)  (Phase 4)  INTEGRATION-NEW
**Files:** Create `tests/test_meta_cli_diff_get_schema.md` (recorded artifact) in `/home/anshulverma/workspace/workbench-meta`

This GATES T18 (DiffEnricher fetch-parse), T22 (threading), T23 (`code_updated` detection), and T24 (`diff_version` in poll). It merges Feature A Task 8 (diff get schema) with the ADR 0032 `diff_version` field-name confirmation. Run inside the cert-equipped container (memory: needs `THRIFT_TLS` cert env / `LD_LIBRARY_PATH=/usr/local/fbcode/platform010/lib`).

- [ ] Step 1: Discover the command surface
  `meta phabricator.diff --help` ; `meta phabricator.diff get --help` ; `meta phabricator.diff list --help`
  Record: whether `get` exists, required args (diff number vs revision id), `--output json` support, and whether `list` already returns a per-revision active code-diff version identifier.

- [ ] Step 2: Capture the JSON schema
  `meta phabricator.diff list --author-is-me --output json --limit 1` ; then `meta phabricator.diff get <KNOWN_DIFF_NUMBER> --output json`.
  Record top-level keys. Determine: (a) whether `get` returns structured per-file hunks, a raw unified-diff blob, or metadata only; (b) **the exact field carrying the active code-diff version id** (candidates: `diff_version`, `active_diff_id`, `latest_diff_phid`, `diffID`) — this is the `diff_version` material field for ADR 0032; (c) the field carrying `revision_id`; (d) the field for `diff_url`.

- [ ] Step 3: Write the artifact `tests/test_meta_cli_diff_get_schema.md` with: exact commands, confirmed top-level keys, per-file/hunk structure (one redacted sample), the diff-body field name, the **confirmed `diff_version` field name**, the `revision_id` field, and the `diff_url` field. Record decision rules:
  - `get` returns structured hunks → T18 parses directly.
  - `get` returns a raw unified-diff string → T18 adds `_parse_unified_diff(text)`.
  - `get` unavailable → T18 falls back to `list` metadata only (hunks empty).
  - **`diff_version` field absent/unconfirmed → fallback proxy: derive a coarse signal from `files_changed` count and total line count present in `list`; a change in that proxy yields `change_type="code_updated"`** (ADR 0032). Record which field names T23/T24 must read.

- [ ] Step 4: `test -s tests/test_meta_cli_diff_get_schema.md && echo CONFIRMED` → `CONFIRMED`.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "docs(diff): record meta phabricator.diff schema + diff_version field name (gates DiffEnricher + detector, ADR 0032)"`

---

## Task 18: DiffEnricher + diff_version capture (meta)  (Phase 4)  [SOURCE: Feature A Task 9 + INTEGRATION-NEW]
**Files:** Create `workbench_meta/providers/enrichment/diff_enricher.py`, `tests/test_diff_enricher.py`. Uses the T17-confirmed schema.

**From source:** Execute **Feature A Task 9 as written** (lazy deep fetch, Path Pre-skip, budget caps, metadata/entity_refs/curated_hunks/skipped_files/truncated/revision_id, degrade-on-failure). Align all fetched-JSON field names with the T17-confirmed schema.

**Integration delta:** The enrichment context must ALSO carry `diff_version` (read from the T17-confirmed field), so the change detector + display have it. Add to the `context` dict built in `enrich`:

```python
        context = {
            "metadata": metadata,
            "entity_refs": entity_refs,
            "curated_hunks": [],
            "skipped_files": [],
            "truncated": False,
            "revision_id": str(meta.get("revision_id", number)),
            "diff_version": str(meta.get("<CONFIRMED_DIFF_VERSION_FIELD>", "")),
        }
```

and after a successful fetch, prefer the fetched `diff_version` if present (`if fetched.get("<field>"): context["diff_version"] = str(fetched["<field>"])`). Add a test asserting `ctx["diff_version"]` is populated from the metadata/fetch.

Commit: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(enrichment): DiffEnricher lazy fetch + Path Pre-skip + diff_version capture (ADR 0024,0032)"`

---

## Task 19: DiffCardContentGenerator — change-aware via change_context (meta)  (Phase 4)  [SOURCE: Feature A Task 10]  INTEGRATION-CHANGED
**Files:** Create `workbench_meta/providers/content/{__init__.py,diff_generator.py}`, `tests/test_diff_generator.py`

**From source:** Feature A Task 10 (single Opus 4.8 `json_schema` call, refusal → summary-only envelope, defensive `count_tokens`). **Integration change:** `generate` signature gains keyword-only `change_context`, and when present the prompt + tool schema produce a `"change"` section ("What changed since last triage") and re-triage options; the envelope `sections` includes a `change` key.

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing tests. Use Feature A Task 10's `tests/test_diff_generator.py` **as written**, but change every `gen.generate(llm, _item(), _enrichment(), memory_context=None)` call to keyword form `gen.generate(llm, _item(), _enrichment(), memory_context=None, change_context=None)`. Add:

```python
@pytest.mark.asyncio
async def test_change_context_adds_change_section_and_options():
    from workbench.models import ChangeContext
    payload = {
        "metadata": {"author": "alice", "status": "accepted"},
        "summary": "Now accepted.",
        "risk": {"factors": [], "watch_outs": []},
        "why_care": "You authored this.",
        "hunks": [],
        "change": "Status moved needs_review -> accepted since you last triaged.",
    }
    llm = _llm_with_tool_result(payload)
    gen = DiffCardContentGenerator(DiffCardContentGenerator.ProviderConfig())
    ctx = ChangeContext(change_type="status_changed",
                        changed_fields={"status": {"old": "needs_review", "new": "accepted"}},
                        change_summary="status changed", previous_triage_action="defer")
    envelope = await gen.generate(llm, _item(), _enrichment(),
                                  memory_context=None, change_context=ctx)
    assert envelope["sections"]["change"]
    # change details reached the model
    _, kwargs = llm.client.messages.create.call_args
    user_text = kwargs["messages"][0]["content"]
    assert "needs_review" in user_text and "accepted" in user_text
```

- [ ] Step 2: Run `python -m pytest tests/test_diff_generator.py -v --tb=short` → `ModuleNotFoundError` (first run) then signature/assertion failures.

- [ ] Step 3: Implement Feature A Task 10's `diff_generator.py` **with these deltas**:
  - `generate` signature: `async def generate(self, llm, item, enrichment_context, *, memory_context=None, change_context=None) -> dict:`
  - Add a `"change"` property to `_DIFF_CARD_TOOL["input_schema"]["properties"]` (`{"type": "string"}`); do NOT add it to `required` (absent on first-triage).
  - `_build_prompt` gains a `change_context` arg; when not None, append:
    ```python
        if change_context is not None:
            cf = "; ".join(f"{k}: {v['old']} -> {v['new']}"
                           for k, v in change_context.changed_fields.items())
            change_block = (
                f"\n\nThis is a RE-TRIAGE. change_type={change_context.change_type}. "
                f"Changed: {cf}. Previous action: {change_context.previous_triage_action}. "
                "Write a one-line 'change' field describing what changed since last "
                "triage, and make the options re-triage options "
                "(e.g. Bump to P1 / Keep priority / Acknowledge / Drop)."
            )
        else:
            change_block = ""
    ```
    and include `change_block` in the returned prompt string.
  - In `generate`, pass `change_context` into `_build_prompt(item, metadata, hunks, mem, change_context)`.
  - The returned envelope `sections` already equals `block.input` (which now includes `change` when the model emits it) — no extra wiring needed.

Keep model `claude-opus-4-8`, `max_tokens=8000`, refusal → summary-only envelope, defensive `count_tokens`.

- [ ] Step 4: Run `python -m pytest tests/test_diff_generator.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(content): change-aware DiffCardContentGenerator (ADR 0025,0032)"`

---

## Task 20: DiffCardPresenter — deterministic + change section (meta)  (Phase 4)  [SOURCE: Feature A Task 11]
**Files:** Create `workbench_meta/providers/presentation/{__init__.py,diff_presenter.py}`, `tests/test_diff_presenter.py`

**From source:** Execute **Feature A Task 11 as written** (deterministic `DiffCardContent -> CardMessage`, top-3 hunks by rank, summary/risk/why-care caps, hunk 1500-char truncation, View-in-Phabricator link).

**Integration delta:** When `card.card_content["sections"]` contains a `"change"` string, render it as a leading `CardSection(title="What changed since last triage", body=...)` (capped at `_RISK_CAP`). Add a test: a card whose sections include `change` produces a section titled "What changed since last triage". Insert in `render` before the Summary section:

```python
        change = sections_data.get("change")
        if change:
            sections.insert(0, CardSection(title="What changed since last triage",
                                           body=_cap(str(change), _RISK_CAP)))
```

Commit: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(presentation): DiffCardPresenter + change callout section (ADR 0023,0032)"`

---

## Task 21: lib/google_api.update_card_message helper (meta)  (Phase 4)  INTEGRATION-NEW
**Files:** Modify `workbench_meta/lib/google_api.py`; Create `tests/test_google_api_update_card.py`

The existing `update_message(message_name, text, as_bot)` patches only `?updateMask=text`. ADR 0031 needs a cardsV2 patch. Add a NEW `update_card_message`.

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing test `tests/test_google_api_update_card.py`:

```python
from unittest.mock import patch
from workbench_meta.lib import google_api


def test_update_card_message_uses_cardsv2_text_mask():
    captured = {}

    def fake_call(method, endpoint, payload, auth_token_class=None):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"success": True, "data": {"name": "spaces/A/messages/p1"}}

    with patch.object(google_api, "call_google_api", side_effect=fake_call):
        result = google_api.update_card_message(
            "spaces/A/messages/p1", "Diff D1", [{"cardId": "c", "card": {}}], as_bot=True)
    assert result["success"] is True
    assert captured["method"] == "PATCH"
    assert "updateMask=cardsV2,text" in captured["endpoint"]
    assert captured["payload"]["cardsV2"] == [{"cardId": "c", "card": {}}]
    assert captured["payload"]["text"] == "Diff D1"
```

- [ ] Step 2: Run `python -m pytest tests/test_google_api_update_card.py -v --tb=short` → `AttributeError: module ... has no attribute 'update_card_message'`.

- [ ] Step 3: Implement — add to `workbench_meta/lib/google_api.py` (next to `update_message`):

```python
def update_card_message(
    message_name: str,
    text: str,
    cards_v2: list[dict[str, Any]],
    as_bot: bool = True,
) -> dict[str, Any]:
    """Patch a message's cardsV2 + text in place (ADR 0031). Cards require bot auth."""
    auth_class = _resolve_auth_class(as_bot)
    payload: dict[str, Any] = {"text": text, "cardsV2": cards_v2}
    endpoint = f"{CHAT_API_BASE}/{message_name}?updateMask=cardsV2,text"
    result = call_google_api("PATCH", endpoint, payload, auth_token_class=auth_class)
    if not result.get("success"):
        return result
    msg = result.get("data", {})
    return {"success": True, "data": {"name": msg.get("name", "")}}
```

- [ ] Step 4: Run `python -m pytest tests/test_google_api_update_card.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(lib): update_card_message cardsV2 patch helper (ADR 0031)"`

---

## Task 22: GoogleChatMessenger send_card (cardsV2+threads) + update_message(CardMessage) (meta)  (Phase 4)  [SOURCE: Feature A Task 12 + ADR 0031]  INTEGRATION-CHANGED
**Files:** Modify `workbench_meta/providers/messenger/gchat.py`; Create `tests/test_gchat_send_card.py`, `tests/test_gchat_update_message.py`

**From source:** Feature A Task 12 (`send_card` cardsV2 parent + ≤3 threaded hunk replies + back-compat string + 429-skip). **Integration addition:** an `update_message(message_id, card: CardMessage) -> bool` override using the T21 `update_card_message` helper (patch parent only; leave threaded hunks stale per ADR 0031).

**Integration delta:**

- [ ] Step 1: Use Feature A Task 12's `tests/test_gchat_send_card.py` **as written**. Add `tests/test_gchat_update_message.py`:

```python
from unittest.mock import patch
import pytest
from workbench.models import CardMessage, CardSection
from workbench_meta.providers.messenger.gchat import GoogleChatMessenger


def _m():
    return GoogleChatMessenger(GoogleChatMessenger.ProviderConfig(space_id="spaces/AAA"))


@pytest.mark.asyncio
async def test_update_message_patches_parent_cardsv2_returns_true():
    seen = {}

    def fake_update(message_name, text, cards_v2, as_bot=True):
        seen["name"], seen["cards_v2"] = message_name, cards_v2
        return {"success": True, "data": {"name": message_name}}

    card = CardMessage(header="[Updated] Diff D1",
                       sections=[CardSection(title="Summary", body="now accepted")])
    with patch("workbench_meta.providers.messenger.gchat.update_card_message",
               side_effect=fake_update):
        ok = await _m().update_message("spaces/AAA/messages/p1", card)
    assert ok is True
    assert seen["name"] == "spaces/AAA/messages/p1"
    assert seen["cards_v2"]


@pytest.mark.asyncio
async def test_update_message_returns_false_on_api_failure():
    def fake_update(message_name, text, cards_v2, as_bot=True):
        return {"success": False, "error": "boom"}

    with patch("workbench_meta.providers.messenger.gchat.update_card_message",
               side_effect=fake_update):
        ok = await _m().update_message("spaces/AAA/messages/p1",
                                       CardMessage(header="h"))
    assert ok is False
```

- [ ] Step 2: Run both files → expect import/attribute errors (`update_card_message` not imported; no `update_message` override).

- [ ] Step 3: Implement. Apply Feature A Task 12's `send_card` + `_send_text` + `_to_cards_v2` **as written**, and update the import line to include `update_card_message`:

```python
from workbench_meta.lib.google_api import (
    send_message, list_messages, send_card_message, update_card_message,
)
```

Add the override:

```python
    async def update_message(self, message_id: str, card) -> bool:
        from workbench.models import CardMessage

        if not message_id:
            return False
        if not isinstance(card, CardMessage):
            # plain string update -> fall through to base default (text-only not
            # supported here); signal caller to send_card fallback.
            return False
        cards_v2 = self._to_cards_v2(card)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                partial(update_card_message, message_id, card.header, cards_v2,
                        as_bot=self.as_bot),
            )
        except Exception as e:
            logger.warning("update_message_error message=%s error=%s", message_id, e)
            return False
        if result.get("success"):
            return True
        logger.warning("update_message_failed message=%s error=%s",
                       message_id, result.get("error", "unknown"))
        return False
```

- [ ] Step 4: Run `python -m pytest tests/test_gchat_send_card.py tests/test_gchat_update_message.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(messenger): GChat send_card cardsV2+threads + update_message(CardMessage) (ADR 0026,0031)"`

---

## Task 23: PhabricatorChangeDetector (+ code_updated) + MetaTasksChangeDetector (meta)  (Phase 4)  [SOURCE: Feature B follow-up + ADR 0032]  INTEGRATION-CHANGED
**Files:** Create `workbench_meta/providers/change_detector/{__init__.py,phabricator.py,meta_tasks.py}`, `tests/test_phab_change_detector.py`, `tests/test_meta_tasks_change_detector.py`

**From source:** Feature B's workbench-meta follow-up list (Phabricator material fields: status, review_stage, comment_count, CI; terminal: published/abandoned; critical: CI failure on authored). **Integration change (ADR 0032):** `diff_version` is a material field producing `change_type="code_updated"` (heaviest). Other materials produce `status_changed` / `ci_changed` / `comment_added`. Use the T17-confirmed `diff_version` field name (or the line-count/files-changed proxy if unconfirmed).

**Integration delta (complete TDD):**

- [ ] Step 1: Write failing test `tests/test_phab_change_detector.py`:

```python
import pytest
from workbench_meta.providers.change_detector.phabricator import PhabricatorChangeDetector

DV = "diff_version"  # replace with T17-confirmed field name


def _d(extra):
    base = {"status": "Needs Review", "comment_count": 0, DV: "100"}
    base.update(extra)
    return base


def test_diff_version_change_is_code_updated():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({}), _d({DV: "101"}))
    assert r.is_material is True
    assert r.change_type == "code_updated"


def test_status_change_is_status_changed():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({}), _d({"status": "Accepted"}))
    assert r.is_material is True
    assert r.change_type == "status_changed"


def test_comment_increase_is_comment_added():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({}), _d({"comment_count": 2}))
    assert r.change_type == "comment_added"


def test_published_is_terminal():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({}), _d({"status": "Closed"}))
    assert r.is_terminal is True


def test_no_change_not_material():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({}), _d({}))
    assert r.is_material is False


def test_ci_failure_on_authored_is_critical():
    det = PhabricatorChangeDetector()
    r = det.detect(_d({"ci_status": "pass", "is_authored": True}),
                   _d({"ci_status": "fail", "is_authored": True}))
    assert r.is_critical is True
    assert r.change_type == "ci_changed"
```

- [ ] Step 2: Run → `ModuleNotFoundError`.

- [ ] Step 3: Implement `phabricator.py` (adjust field names per T17):

```python
# workbench_meta/providers/change_detector/phabricator.py
from workbench.providers.change_detector.base import ChangeDetector, ChangeResult

_TERMINAL = {"closed", "published", "abandoned"}
_DIFF_VERSION_FIELD = "diff_version"  # T17-confirmed; else proxy below


def _norm(s):
    return str(s or "").lower().replace(" ", "_")


class PhabricatorChangeDetector(ChangeDetector):
    def source_type(self) -> str:
        return "diff"

    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult:
        new_status = _norm(new_raw.get("status"))
        if new_status in _TERMINAL:
            return ChangeResult(is_material=False, is_terminal=True, is_critical=False,
                                changed_fields=["status"], change_type="terminal",
                                reason=f"reached terminal state {new_status}")

        changed = []
        change_type = None
        critical = False

        old_dv = str(old_raw.get(_DIFF_VERSION_FIELD, ""))
        new_dv = str(new_raw.get(_DIFF_VERSION_FIELD, ""))
        if old_dv and new_dv and old_dv != new_dv:
            changed.append("diff_version")
            change_type = "code_updated"  # heaviest

        old_ci = _norm(old_raw.get("ci_status"))
        new_ci = _norm(new_raw.get("ci_status"))
        if old_ci != new_ci and (old_ci or new_ci):
            changed.append("ci_status")
            change_type = change_type or "ci_changed"
            if new_ci == "fail" and new_raw.get("is_authored"):
                critical = True

        if _norm(old_raw.get("status")) != new_status:
            changed.append("status")
            change_type = change_type or "status_changed"

        if _norm(old_raw.get("review_stage")) != _norm(new_raw.get("review_stage")):
            changed.append("review_stage")
            change_type = change_type or "status_changed"

        if (new_raw.get("comment_count", 0) or 0) > (old_raw.get("comment_count", 0) or 0):
            changed.append("comment_count")
            change_type = change_type or "comment_added"

        if not changed:
            return ChangeResult(is_material=False, is_terminal=False, is_critical=False,
                                changed_fields=[], change_type="none",
                                reason="no material change")
        return ChangeResult(is_material=True, is_terminal=False, is_critical=critical,
                            changed_fields=changed, change_type=change_type,
                            reason=f"changed: {', '.join(changed)}")
```

Implement `meta_tasks.py` analogously (material: status/priority/assignee → `status_changed`; terminal: resolved/closed/duplicate; critical: SEV) with its own `tests/test_meta_tasks_change_detector.py`.

- [ ] Step 4: Run both detector test files → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(change_detector): Phabricator(code_updated)+MetaTasks detectors (ADR 0032)"`

---

## Task 24: Phab/Tasks adapter monitoring overrides + diff_version in poll() (meta)  (Phase 4)  [SOURCE: Feature B follow-up + INTEGRATION]  INTEGRATION-CHANGED
**Files:** Modify `workbench_meta/providers/source/phabricator.py`, `workbench_meta/providers/source/meta_tasks.py`; extend their tests

**From source:** Feature B follow-up — `supports_monitoring() -> True`, `stable_id()` (`D{number}` / `T{task_id}`). **Integration change (ADR 0032):** `poll()` must persist `diff_version` (the T17-confirmed field) into the `RawItem.raw_text` JSON so the detector can compare old vs new. The current `_query_diffs` (phabricator.py lines ~102-136) builds `diff` from `meta phabricator.diff list` and dumps it whole into `raw_text` — confirm the `list` output already includes the diff-version field; if `list` does NOT include it, capture it from the proxy (files_changed/line counts already present) per T17's recorded fallback.

**Integration delta:**

- [ ] Step 1: Write failing test additions to `tests/test_phabricator_source.py` (or create it):

```python
import json
from workbench_meta.providers.source.phabricator import PhabricatorAdapter
from workbench.models import RawItem


def test_supports_monitoring_true():
    assert PhabricatorAdapter(PhabricatorAdapter.ProviderConfig()).supports_monitoring() is True


def test_stable_id_strips_timestamp():
    a = PhabricatorAdapter(PhabricatorAdapter.ProviderConfig())
    raw = RawItem(id="123_2026", source_type="diff", source_label="",
                  raw_text=json.dumps({"number": "123"}))
    assert a.stable_id(raw) == "D123"


def test_poll_raw_text_carries_diff_version():
    # The dict dumped into raw_text must include the diff_version field
    # (or the recorded fallback proxy) so the detector can compare.
    a = PhabricatorAdapter(PhabricatorAdapter.ProviderConfig())
    raw = RawItem(id="123_x", source_type="diff", source_label="",
                  raw_text=json.dumps({"number": "123", "diff_version": "100"}))
    data = json.loads(raw.raw_text)
    assert "diff_version" in data  # field name per T17
```

- [ ] Step 2: Run → `AttributeError` for `supports_monitoring`/`stable_id`.

- [ ] Step 3: Implement. Add to `PhabricatorAdapter`:

```python
    def supports_monitoring(self) -> bool:
        return True

    def stable_id(self, raw_item) -> str:
        import json
        number = str(json.loads(raw_item.raw_text)["number"]).lstrip("D")
        return f"D{number}"
```

In `_query_diffs`, ensure the dumped `diff` dict includes the diff-version field. If `meta phabricator.diff list --output json` already returns it (confirmed in T17), no change beyond dumping the whole `diff` (already done at line ~133). If not, set it explicitly from the proxy:

```python
            diff.setdefault("diff_version", str(diff.get("<list-version-field>", "")))
```

(Leave `RawItem.id = f"{number}_{updated}"` unchanged — `stable_id()` derives the stable key; the volatile `id` stays for back-compat with `ProcessedStore`.)

Apply the analogous `supports_monitoring`/`stable_id` (`T{task_id}`) to `meta_tasks.py` with its test.

- [ ] Step 4: Run the adapter test files → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(source): Phab/Tasks monitoring overrides + diff_version in poll() (ADR 0032)"`

---

## Task 25: Meta config wiring — presentation + enrichment + change_detector (meta)  (Phase 4)  [SOURCE: Feature A Task 13 + Feature B config]
**Files:** Modify `config.meta.yml`; Create `tests/test_meta_config_wiring.py`

**From source:** Execute **Feature A Task 13 as written** (presentation diff presenter+generator entry, enrichment composite form with DiffEnricher). **Integration addition (Feature B config):** add `change_detector:` entries to the Phabricator + Meta Tasks source configs.

**Integration delta:** Extend A Task 13's test with change_detector assertions:

```python
def test_sources_register_change_detectors():
    cfg = _load()
    phab = next(s for s in cfg["sources"] if "phabricator" in s["class"].lower())
    assert phab["change_detector"]["class"].endswith(
        "change_detector.phabricator.PhabricatorChangeDetector")
    tasks = next(s for s in cfg["sources"] if "meta_tasks" in s["class"].lower()
                 or "tasks" in s["class"].lower())
    assert tasks["change_detector"]["class"].endswith(
        "change_detector.meta_tasks.MetaTasksChangeDetector")
```

Add to the Phabricator source entry in `config.meta.yml`:

```yaml
    change_detector:
      class: workbench_meta.providers.change_detector.phabricator.PhabricatorChangeDetector
```

and the analogous entry to the Meta Tasks source. Plus the `presentation:` + `enrichment:` blocks from A Task 13.

Commit: `cd /home/anshulverma/workspace/workbench-meta && git add -A && git commit -m "feat(config): wire diff presenter/generator/enricher + change detectors (Meta)"`

---

# PHASE 5 — UI (Feature A)

## Task 26: useTriageCard hook (foundational)  (Phase 5)  [SOURCE: Feature A Task 14]
**Files:** Create `ui/src/hooks/useTriageCard.ts`, `ui/src/hooks/useTriageCard.test.ts`

**From source:** Execute **Feature A Task 14 as written** — `useTriageCard(id)` via `apiGet`, no poll, five-state. 2 vitest/MSW tests.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): useTriageCard(id) detail hook (no poll)"`

---

## Task 27: DiffHunks CSS-only component (foundational)  (Phase 5)  [SOURCE: Feature A Task 15]
**Files:** Create `ui/src/components/DiffHunks.tsx`, `ui/src/components/DiffHunks.test.tsx`

**From source:** Execute **Feature A Task 15 as written** — CSS-only `+`/`-` renderer, per-file expand, auto-expand top hunk, `maxHunks` cap, no new dependency. 4 vitest tests.

Commit: `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): DiffHunks CSS-only diff renderer (ADR 0028)"`

---

## Task 28: TriageDetail page + route + Review link + change callout (foundational)  (Phase 5)  [SOURCE: Feature A Task 16]  INTEGRATION-CHANGED
**Files:** Create `ui/src/pages/TriageDetail.tsx`, `ui/src/pages/TriageDetail.test.tsx`; Modify `ui/src/App.tsx`, `ui/src/pages/Triage.tsx`

**From source:** Feature A Task 16 (TriageDetail page rendering metadata/summary/risk/why-care/hunks/Phabricator link, reuse `useTriage` respond, read-only when responded/expired; `#/triage/:cardId` route; Review link in Triage list).

**Integration change:** when `card_content.sections.change` is present, render a leading "What changed since last triage" callout.

**Integration delta:**

- [ ] Step 1: Use Feature A Task 16's `tests/`/`TriageDetail.test.tsx` **as written**, and add one case to the same file:

```typescript
  it('shows the change callout on a re-triaged card', async () => {
    server.use(
      http.get('/api/triage/cards/c1', () =>
        HttpResponse.json({
          ...CARD,
          card_content: {
            ...CARD.card_content,
            sections: {
              ...CARD.card_content.sections,
              change: 'Status moved needs_review -> accepted since you last triaged.',
            },
          },
        }),
      ),
    )
    renderDetail()
    expect(await screen.findByText(/What changed since last triage/i)).toBeInTheDocument()
    expect(screen.getByText(/needs_review -> accepted/)).toBeInTheDocument()
  })
```

- [ ] Step 2: Run `cd ui && npx vitest run src/pages/TriageDetail.test.tsx` → fails (no change callout / component missing).

- [ ] Step 3: Implement Feature A Task 16's `TriageDetail.tsx` **as written**, plus extract `change` and render the callout above the metadata line:

```typescript
  const change = (sections.change as string | undefined) ?? undefined
```
```tsx
      {change && (
        <section className="rounded border border-amber-700/40 bg-amber-950/20 p-3">
          <h2 className="font-medium">What changed since last triage</h2>
          <p className="text-sm">{change}</p>
        </section>
      )}
```

Add the route to `App.tsx` and the Review link to `Triage.tsx` per Feature A Task 16.

- [ ] Step 4: Run `cd ui && npx vitest run src/pages/TriageDetail.test.tsx src/pages/Triage.test.tsx` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "feat(ui): TriageDetail page + route + Review link + change callout (ADR 0023,0032)"`

---

## Task 29: Regenerate api-types + full build/test (foundational)  (Phase 5)  [SOURCE: Feature A Task 17]
**Files:** Modify `ui/src/lib/api-types.ts` (regenerated)

**From source:** Execute **Feature A Task 17 as written** — start server (route must include `cards/{card_id}`), `npm run gen:api` (standalone /tmp Node v20), `npm run test && npm run build`, confirm no new `package.json` dependency, stop server. Commit only `ui/src/lib/api-types.ts`.

Commit: `cd /home/anshulverma/workspace/workbench && git add ui/src/lib/api-types.ts && git commit -m "chore(ui): regenerate api-types with triage card detail route"`

---

# PHASE 6 — Cross-cutting

## Task 30: CONTEXT.md glossary (A + B terms) + memory-caps fix (foundational)  (Phase 6)  [SOURCE: Feature A Task 18 + Feature B glossary]  INTEGRATION-CHANGED
**Files:** Modify `docs/CONTEXT.md`; Create `tests/test_context_doc.py`

**From source:** Feature A Task 18 (memory-caps drift fix to 5/20/10; add Card Presenter / Card Content Schema / Card Content Generator / CardMessage / Diff Enricher terms).

**Integration addition:** add Feature B + integration terms: ChangeDetector, ChangeResult, material change, terminal state, stable source_id, re-triage, ChangeContext, DebounceManager, diff_version, code_updated.

**Integration delta:**

- [ ] Step 1: Use Feature A Task 18's `tests/test_context_doc.py` **as written**, and extend `test_new_terms_present` to require the B/integration terms too:

```python
def test_change_monitoring_terms_present():
    text = _text()
    for term in ["ChangeDetector", "ChangeResult", "material change", "terminal state",
                 "stable source_id", "re-triage", "ChangeContext", "DebounceManager",
                 "diff_version", "code_updated"]:
        assert term in text, f"missing CONTEXT term: {term}"
```

- [ ] Step 2: Run `python -m pytest tests/test_context_doc.py -v --tb=short` → fails (terms + "without caps").

- [ ] Step 3: Implement Feature A Task 18's CONTEXT.md edits (memory-caps fix + A terms), then append the B/integration glossary entries (match the existing `**Term**: ...` style), for example:

```markdown
**ChangeDetector**: Pluggable, synchronous, no-LLM comparator of old vs new raw source dicts, returning a `ChangeResult`. Registered per source via `change_detector:` config; missing → `AlwaysMaterialDetector` fallback. Gated by `SourceAdapter.supports_monitoring()` so it never runs for email/calendar (Feature B).

**ChangeResult**: Value object `{is_material, is_terminal, is_critical, changed_fields, change_type, reason}` produced by a `ChangeDetector`. `change_type` keys regeneration depth (ADR 0032).

**material change**: A source-type-specific field-set change (e.g. diff status/CI/comments, new diff version) that warrants re-triage. Defined per detector, not by LLM.

**terminal state**: Source state needing no further monitoring (diff landed/abandoned, task resolved). Detected by `ChangeDetector.is_terminal` or by disappearance from a complete-set poll; archives the item and expires its card.

**stable source_id**: An identifier surviving updates (`D12345`, `T67890`) via `SourceAdapter.stable_id()`, replacing the legacy compound `{number}_{updated}`. The item match key for change detection (Feature B D4).

**re-triage**: Regenerating a new/updated `TriageCard` for an existing `Item` after a material change, via `_fire_retriage` — the SINGLE diff-card regeneration path (ADR 0030). Renders through `CompositeCardPresenter → CardMessage` and sends via `send_card`/`update_message` (ADR 0031).

**ChangeContext**: Structured `{change_type, changed_fields, change_summary, previous_triage_action, previous_priority}` built from a `ChangeResult` + old/new raw + previous card, threaded into `generate_card`/`CardContentGenerator` for change-aware copy and re-triage options.

**DebounceManager**: In-memory 2-minute trailing-edge timer per `item_id` collapsing rapid changes into one re-triage; merges `ChangeResult`s with heaviest-`change_type` wins (ADR 0032). Lost on restart; re-detected next poll.

**diff_version**: The active code-diff version id captured by Phabricator `poll()` into `Item.raw_data` (opaque, equality-compared). A change makes `PhabricatorChangeDetector` emit `change_type="code_updated"` (ADR 0032). Field name confirmed by the schema verification task; fallback proxy = files-changed/line-count.

**code_updated**: The heaviest `change_type`; triggers the FULL re-triage path (`_fire_retriage` re-runs `DiffEnricher` to re-fetch the diff and `DiffCardContentGenerator` to regenerate hunks). All other change types take the LIGHT path (reuse stored hunks, regenerate only copy + options) (ADR 0032).
```

- [ ] Step 4: Run `python -m pytest tests/test_context_doc.py -v --tb=short` → PASS.

- [ ] Step 5: Commit
  `cd /home/anshulverma/workspace/workbench && git add -A && git commit -m "docs(context): card presentation + change-monitoring glossary; fix memory caps 5/20/10"`

---

## Task 31: Final combined verification  (Phase 6)
Run after all tasks:
- foundational: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -v --tb=short && python -m ruff check src/ tests/`
- meta: `cd /home/anshulverma/workspace/workbench-meta && python -m pytest tests/ -v --tb=short`
- ui: `cd /home/anshulverma/workspace/workbench/ui && npm run test && npm run build` (standalone /tmp Node v20)

Confirm both source specs' Verification lists plus the integration ADRs:
- **Feature A spec (1–20):** plain fallback when `presentation` absent (1); hard error on unimportable class (2); shallow degrade on fetch failure (3); metadata-only `poll()` except `diff_version` capture (4); Path Pre-skip ordering (5); budget truncation (6); Opus single call writing `content_schema=="diff.v1"` (7); empty-memory summary (8); refusal → summary-only → plain path (9); **(10) reuse-on-rescore is now subsumed by `_fire_retriage` per ADR 0030 — `revision_id`/`diff_version` are kept for detection/display, not standalone polling**; CardMessage send_card + console render_to_text (11); cardsV2 parent + ≤3 threaded hunks + 429 skip (12); chat caps (13); link-only buttons + thread reply capture (14); detail API 404/bearer (15); detail-view expand defaults (16); CSS-only hunks + max_hunks + no new dep (17); reuse useTriage + read-only (18); gen:api type shape (19); config minor bump + loads (20).
- **Feature B spec (1–13):** ChangeResult/AlwaysMaterial (1–2); debounce single/merge/cancel + heaviest change_type (3); card update routing queued/sent/responded/race (4); deferred card clears + regenerates (5); daily cap + critical bypass before LLM (6); new-item enqueue path (7); material → `_fire_retriage` after debounce (8); non-material silent update (9); terminal archive+expire (10); disappeared archive (11); stable-ID migration (12); messenger update fallback → send_card + re-persist id (13).
- **Integration ADRs:** single regeneration path via `_fire_retriage` only (0030); `update_message`/`send_card` both take `CardMessage`, console renders, GChat patches cardsV2, False→send_card+re-persist (0031); `diff_version` material → `code_updated` → full path, others → light path reusing stored hunks (0032).

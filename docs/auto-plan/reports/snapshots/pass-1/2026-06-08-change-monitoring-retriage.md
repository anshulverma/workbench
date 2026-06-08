# Change Monitoring & Re-Triage: Implementation Plan

## Slice Dependency Graph

```
Slice 1 (ChangeDetector ABC)    Slice 3 (stable_id)    Slice 4 (Store methods)    Slice 5 (update_message)    Slice 7 (DebounceManager)
      |                               |                       |                        |                           |
      v                               |                       |                        |                           |
Slice 2 (ChangeContext)               |                       |                        |                           |
      |                               |                       |                        |                           |
      v                               |                       |                        |                           |
Slice 6 (generate_card)               |                       |                        |                           |
      |                               |                       |                        |                           |
      +-------------------------------+-----------+------------+------------------------+---------------------------+
                                                  |
                                                  v
                                        Slice 8 (Re-check routing)
                                                  |
                                                  v
                                        Slice 9 (Card re-triage)
                                                  |
                                        +---------+---------+
                                        |                   |
                                        v                   v
                              Slice 10 (Shutdown)   Slice 11 (Config)
```

**Parallelizable**: Slices 1, 3, 4, 5, 7 can all be built concurrently.

---

## Slice 1: ChangeDetector Interface + AlwaysMaterialDetector

**Done when**: `AlwaysMaterialDetector().detect(old, new)` returns a `ChangeResult` with `is_material=True` and all unit tests pass.

### Files to create

| File | Description |
|---|---|
| `src/workbench/providers/change_detector/__init__.py` | Package init |
| `src/workbench/providers/change_detector/base.py` | `ChangeDetector` ABC, `ChangeResult` model |
| `src/workbench/providers/change_detector/fallback.py` | `AlwaysMaterialDetector` |
| `tests/test_change_detector.py` | Unit tests |

### Interface

```python
class ChangeResult(BaseModel):
    is_material: bool
    is_terminal: bool
    is_critical: bool
    changed_fields: list[str]
    change_type: str
    reason: str

class ChangeDetector(ABC):
    @abstractmethod
    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult: ...
    @abstractmethod
    def source_type(self) -> str: ...
```

### Tests

1. `AlwaysMaterialDetector.detect(a, b)` where `a != b` → `is_material=True`.
2. `AlwaysMaterialDetector.detect(a, a)` → `is_material=True` (fallback treats all as material).
3. `ChangeResult.is_critical` defaults to `False`.
4. `ChangeResult.is_terminal` defaults to `False`.

### Dependencies

None.

---

## Slice 2: ChangeContext Model + Builder

**Done when**: `build_change_context()` returns a correctly populated `ChangeContext` and tests cover with/without previous card.

### Files to modify/create

| File | Description |
|---|---|
| `src/workbench/models.py` | Add `ChangeContext` model |
| `src/workbench/pipeline/change_context.py` | `build_change_context()` function |
| `tests/test_change_context.py` | Unit tests |

### Model

```python
class ChangeContext(BaseModel):
    change_type: str
    changed_fields: dict[str, dict[str, str]]
    change_summary: str
    previous_triage_action: str | None = None
    previous_priority: str | None = None
```

### Tests

1. `build_change_context` with `previous_card=None` → empty previous fields.
2. `build_change_context` with a responded card → copies response and priority.
3. `ChangeContext` round-trips via `model_dump()`/`model_validate()`.

### Dependencies

Slice 1 (`ChangeResult`).

---

## Slice 3: Stable source_id on SourceAdapter

**Done when**: Existing adapters work without modification, and a test subclass can override `supports_monitoring()` and `stable_id()`.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/providers/source/base.py` | Add two concrete methods |
| `tests/test_source_adapter.py` | Unit tests |

### Interface additions

```python
def supports_monitoring(self) -> bool:
    return False

def stable_id(self, raw_item: RawItem) -> str:
    return raw_item.id
```

Both concrete with backward-compatible defaults. Not abstract.

### Tests

1. Minimal subclass inherits `supports_monitoring() == False` and `stable_id()` returns `raw_item.id`.
2. Monitoring-enabled subclass overrides both.
3. Existing adapters (Gmail, GCalendar, GChat, GitHub) still instantiate.

### Dependencies

None.

---

## Slice 4: New Store Methods + Database Migration

**Done when**: Integration tests against PostgreSQL exercise all new store methods and the indexes exist.

### Files to modify/create

| File | Description |
|---|---|
| `src/workbench/storage/base.py` | Add abstract methods to `ItemStore` and `TriageStore` |
| `src/workbench/storage/postgres/items.py` | Implement `get_item_by_source_id`, `get_active_by_source`, `update_raw_data` |
| `src/workbench/storage/postgres/triage.py` | Implement `get_card_by_item_id`, `clear_deferral` |
| `src/workbench/migrations/versions/` | New migration for indexes |
| `tests/test_change_monitoring_stores.py` | Integration tests |

### New ItemStore methods

```python
async def get_item_by_source_id(self, source_type: str, source_id: str) -> Item | None: ...
async def get_active_by_source(self, source_type: str) -> list[Item]: ...
async def update_raw_data(self, item_id: str, raw_text: str) -> None: ...
```

### New TriageStore methods

```python
async def get_card_by_item_id(self, item_id: str) -> TriageCard | None: ...
async def clear_deferral(self, card_id: str) -> None: ...
```

### Migration

```sql
CREATE INDEX idx_items_source_lookup ON items (source_type, source_id);
CREATE INDEX idx_triage_cards_item_id ON triage_cards (item_id);
```

### Tests

1. `save_item` then `get_item_by_source_id` returns the item; wrong source_type returns None.
2. `get_active_by_source` excludes archived items.
3. `update_raw_data` updates the JSONB and bumps `updated_at`.
4. `save_card` then `get_card_by_item_id` returns the card; unknown item_id returns None.
5. `defer_card` then `clear_deferral` sets `deferred_until` to NULL.
6. Archived items excluded from `get_item_by_source_id`.

### Dependencies

None.

---

## Slice 5: Messenger.update_message

**Done when**: `ConsoleMessenger.update_message()` prints updated text and returns `True`. Base default returns `False`.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/providers/messenger/base.py` | Add `update_message` with default `return False` |
| `src/workbench/providers/messenger/console.py` | Override with print implementation |
| `tests/test_messenger_update.py` | Unit tests |

### Tests

1. Base `Messenger` minimal subclass `update_message` returns `False`.
2. `ConsoleMessenger.update_message` returns `True` and writes to stdout.

### Dependencies

None.

---

## Slice 6: generate_card Accepts ChangeContext

**Done when**: `generate_card(..., change_context=ctx)` produces a card whose `card_content` includes change metadata. Without `change_context`, behavior is identical to current.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/pipeline/triage.py` | Add `change_context` parameter to `generate_card`, adjust LLM prompt |
| `tests/test_triage_card_change.py` | Unit tests |

### Changes

- `generate_card()` gains `change_context: ChangeContext | None = None` keyword.
- When `change_context` is provided, the LLM prompt includes change details.
- Template fallback produces change-aware card with "[Updated]" prefix and re-triage options.

### Tests

1. `generate_card` without `change_context` behaves identically (regression guard).
2. `generate_card` with `change_context` includes `"change"` key in `card_content`.
3. Template fallback re-triage card has "[Updated]" prefix.
4. LLM-generated card receives change_context in prompt (mock LLM, verify call args).

### Dependencies

Slice 2 (`ChangeContext`).

---

## Slice 7: DebounceManager

**Done when**: Unit tests verify debounce merging, timer expiry fires callback, and `cancel_all()` prevents pending callbacks.

### Files to create

| File | Description |
|---|---|
| `src/workbench/pipeline/debounce.py` | `DebounceManager` class |
| `tests/test_debounce.py` | Unit tests |

### Interface

```python
class DebounceManager:
    def __init__(self, fire_callback, delay_seconds: float = 120.0): ...
    def schedule(self, item_id: str, result: ChangeResult, raw_item: RawItem) -> None: ...
    def cancel(self, item_id: str) -> None: ...
    def cancel_all(self) -> None: ...
    @property
    def pending_count(self) -> int: ...
```

The callback is passed at construction (not per-schedule call). `schedule()` accepts a `ChangeResult` and `RawItem` — consecutive calls for the same `item_id` merge `ChangeResult` fields (union of `changed_fields`, OR of `is_critical`).

### Tests

1. Single fire: schedule, advance time past delay, callback called with correct item_id.
2. Merge: schedule same item_id twice within delay, only one callback fires (the latest).
3. `cancel(item_id)` prevents callback from firing.
4. `cancel_all()` clears everything.
5. Different item_ids fire independently.

### Dependencies

None.

---

## Slice 8: Re-check Routing in Scheduler

**Done when**: Monitoring-enabled adapter's poll results route existing items through change detection, and disappeared items are archived.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/pipeline/scheduler.py` | Add `_route_poll_results()`, `_detect_disappeared()`, `_archive_terminal()`, integrate into `_poll_one_source()` |
| `tests/test_change_monitoring_routing.py` | Integration tests |

### Key methods

- `_route_poll_results(source_id, adapter, detector, raw_items, trigger)` — splits items: new → enqueue, existing → detect
- `_detect_disappeared(source_type, seen_ids)` — archives absent items
- `_archive_terminal(item)` — archives item + expires pending card

### Tests

1. Monitoring-disabled adapter: all items enqueued (existing behavior preserved).
2. Monitoring-enabled, new item: enqueued normally.
3. Monitoring-enabled, existing item with material change: `update_raw_data` called, debounce scheduled.
4. Monitoring-enabled, existing item with non-material change: `update_raw_data` IS called, but debounce NOT scheduled.
5. Item disappeared from poll: archived, queued/sent card expired.
6. Item disappeared, card already responded: card not touched, only item archived.
7. Stable ID migration: item with old compound source_id in DB, poll returns same entity with new stable ID → treated as new item (enqueued), not matched to old item. Subsequent polls match correctly.

### Dependencies

Slices 1, 3, 4, 7. Note: `__init__` wiring of `self._debounce` and `self._change_detectors` is included in this slice (not deferred to Slice 10) since `_route_poll_results` references them.

---

## Slice 9: Card Re-Triage (`_fire_retriage`)

**Done when**: All card-status branches tested with mocked stores and messenger.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/pipeline/scheduler.py` | Add `_fire_retriage()` method |
| `tests/test_retriage.py` | Unit tests |

### Card routing logic

| Card status | Action |
|---|---|
| `queued` | Update `card_content`, `options`, `relevance_score` in-place; clear `deferred_until` |
| `sent` | Update in-place + call `messenger.update_message()`; fallback to `send_card` on failure |
| `responded` / `expired` | Create new `TriageCard` linked to same `Item` |
| None (no card exists) | Create new card |

Additional: daily cap check before LLM call; `is_critical` bypasses cap; re-read card status before update (race mitigation).

### Tests

1. Queued card: content updated in-place, no messenger call.
2. Sent card, messenger supports update: `update_message` called.
3. Sent card, messenger does NOT support update: fallback `send_card` called.
4. Responded card: new card created, old card untouched.
5. Expired card: new card created.
6. Deferred card: `clear_deferral` called before card update.
7. Daily cap reached, non-critical: re-triage skipped.
8. Daily cap reached, critical: re-triage proceeds.
9. Item archived between debounce and fire: no-op.
10. No existing card: new card created.

### Dependencies

Slices 1, 2, 4, 5, 6, 7, 8.

---

## Slice 10: Shutdown Integration

**Done when**: `scheduler.shutdown()` cancels all debounce timers and stops cleanly.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/pipeline/scheduler.py` | Wire `DebounceManager` into `__init__` and `shutdown()` |
| `tests/test_scheduler_shutdown.py` | Unit tests |

### Changes

- `__init__` wiring of `self._debounce` and `self._change_detectors` is done in Slice 8.
- `shutdown()`: add `self._debounce.cancel_all()` before `self.scheduler.shutdown(wait=False)`

### Tests

1. `shutdown()` calls `debounce.cancel_all()`.
2. After `shutdown()`, `_shutting_down` is True and `pending_count` is 0.

### Dependencies

Slices 7, 8.

---

## Slice 11: Change Detector Config + Registration

**Done when**: YAML config with `change_detector` on a source entry populates `_change_detectors`, and missing entries fall back to `AlwaysMaterialDetector`.

### Files to modify

| File | Description |
|---|---|
| `src/workbench/main.py` | Load detectors at startup, pass to scheduler |
| `config.example.yml` | Document `change_detector` option |
| `tests/test_change_detector_config.py` | Unit tests |

### Config shape

```yaml
sources:
  - class: workbench.providers.source.github.GitHubSourceAdapter
    change_detector:
      class: some.module.GitHubChangeDetector
    repos: ["owner/repo"]
```

The `change_detector` dict is optional per source. If present, instantiate the class and register in `scheduler._change_detectors[adapter_type]`.

### Tests

1. Empty config (no change_detectors): validates without error.
2. Config with detector: scheduler has detector for that source_type.
3. Unregistered source_type: fallback `AlwaysMaterialDetector` used.

### Dependencies

Slices 1, 8.

---

## workbench-meta Follow-up (out of scope for this plan)

After all slices above land in workbench:

1. `PhabricatorChangeDetector` — material fields: status, review_stage, comment_count, CI status. Terminal: published, abandoned. Critical: CI failure on authored diff.
2. `MetaTasksChangeDetector` — material fields: status, priority, assignee. Terminal: resolved, closed. Critical: SEV status.
3. Adapter `stable_id()` overrides — Phabricator: `D{number}`, Tasks: `T{task_id}`.
4. Adapter `supports_monitoring()` overrides — both return `True`.
5. `GoogleChatMessenger.update_message` — uses Google Chat REST API `spaces.messages.patch`.
6. `config.meta.yml` — add `change_detector` entries to source configs.

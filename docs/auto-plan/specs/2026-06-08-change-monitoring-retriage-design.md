# Change Monitoring & Re-Triage — Design Spec

## Context

Workbench ingests items from external sources (Phabricator diffs, Meta Tasks, GitHub PRs), scores them, and delivers triage cards via messenger. Today, each item is a one-shot: ingested, triaged, delivered, done. If a diff's CI fails after triage, or a task changes priority, the user never hears about it.

Change monitoring closes this gap. After initial triage, Workbench continues tracking items from monitoring-capable sources. When a material change is detected, the item is re-triaged and the user receives an updated or new card reflecting what changed. No new cron jobs, no separate snapshot tables, no LLM calls in the detection path.

### Glossary

- **ChangeDetector**: Pluggable interface comparing old/new raw source data. Synchronous, no LLM. Returns `ChangeResult`.
- **ChangeResult**: Value object with `is_material`, `is_terminal`, `is_critical`, `changed_fields`, `change_type`, `reason`.
- **material change**: A source-type-specific set of field changes (e.g., diff status change, new comments) that warrant re-triage. Defined by each `ChangeDetector` implementation, not by LLM judgment.
- **terminal state**: Source state indicating no further monitoring is needed (e.g., diff landed/abandoned, task resolved). Detected by `ChangeDetector`, causes item archival and triage card expiration.
- **stable source_id**: A source identifier that does not change across updates (e.g., `D12345` for a diff, `T67890` for a task). Replaces the previous compound `{number}_{updated}` format.
- **re-check routing**: The post-poll step in `_poll_one_source` that splits raw items into new-ingestion vs change-detection paths based on `ItemStore` lookup.
- **ChangeContext**: Structured description of what changed on a monitored item, produced from `ChangeResult` + old/new raw data, consumed by `generate_card()`.
- **critical change**: A change requiring immediate user attention regardless of daily cap. Deterministically classified by `change_type`, not LLM-judged.
- **re-triage**: Generating a new or updated `TriageCard` for an existing `Item` after a material change, using the same pipeline stages (enrichment, LLM card generation) as initial triage but with `ChangeContext` injected.
- **AlwaysMaterialDetector**: Fallback `ChangeDetector` used when no detector is configured for a source. Returns `is_material=True, is_terminal=False` for any diff.
- **DebounceManager**: In-memory trailing-edge timer (2-minute default, per `item_id`) that collapses rapid re-triage requests into a single card regeneration.

## Goals

1. **Detect** material changes to previously-triaged items without LLM calls in the detection path.
2. **Re-triage** changed items with change-aware card copy ("Your diff D12345 now has CI failures").
3. **Cease monitoring** items that reach terminal state (landed, abandoned, resolved) immediately.
4. **Debounce** rapid-fire changes into a single re-triage event.
5. **Bypass daily cap** for critical changes (CI failure on authored diff, blocking review, SEV).
6. **Zero new cron jobs** — reuse existing per-source poll schedule.
7. **Single-user scale** — bounded at ~50 monitored items per source.

## Architecture

```
Existing poll job fires
  │
  ├─ adapter.poll(since=watermark) → list[RawItem]
  │
  ├─ For each raw_item:
  │    │
  │    ├─ sid = adapter.stable_id(raw_item)
  │    │
  │    ├─ existing = ItemStore.get_item_by_source_id(source_type, sid)
  │    │
  │    ├─ No existing item ──→ pipeline.enqueue()  [new ingestion, unchanged]
  │    │
  │    └─ Existing item found:
  │         │
  │         ├─ ChangeDetector.detect(old_raw, new_raw) → ChangeResult
  │         │
  │         ├─ is_terminal ──→ archive item, expire triage card
  │         │
  │         ├─ is_material ──→ DebounceManager.schedule()
  │         │                   └─ (after 2 min) → update Item.raw_data,
  │         │                                       re-triage card
  │         │
  │         └─ not material ──→ update Item.raw_data silently
  │
  └─ Detect disappeared items (in DB but absent from poll) → archive
```

| Component | Location | What it does |
|---|---|---|
| ChangeDetector ABC + ChangeResult | `providers/change_detector/base.py` | Compare old/new raw dicts, return `ChangeResult` with `is_material`, `is_critical`, `is_terminal`, `changed_fields` |
| AlwaysMaterialDetector | `providers/change_detector/fallback.py` | Fallback: returns `is_material=True, is_terminal=False` for any diff |
| PhabricatorChangeDetector | `workbench-meta` | Phabricator-specific material field set |
| MetaTasksChangeDetector | `workbench-meta` | Meta Tasks-specific material field set |
| Re-check routing | `pipeline/scheduler.py` | Post-poll split: new items → enqueue, existing items → change detection |
| DebounceManager | `pipeline/debounce.py` | 2-minute trailing-edge timer per `item_id`, merges rapid changes |
| ChangeContext | `models.py` | Structured change description for LLM card generation |
| Messenger.update_message | `providers/messenger/base.py` | In-place messenger message update, returns `False` on failure |
| Stable source_id | Each SourceAdapter | Identifier that survives updates (e.g., `D12345`) |

## ChangeDetector Interface

```python
# src/workbench/providers/change_detector/base.py

from abc import ABC, abstractmethod
from pydantic import BaseModel


class ChangeResult(BaseModel):
    is_material: bool
    is_terminal: bool
    is_critical: bool
    changed_fields: list[str]
    change_type: str
    reason: str


class ChangeDetector(ABC):
    @abstractmethod
    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult:
        ...

    @abstractmethod
    def source_type(self) -> str:
        ...
```

Synchronous. Receives two plain dicts (old and new raw source JSON), returns a `ChangeResult`. No async, no LLM, no network calls. Each detector hard-codes its material field set.

### AlwaysMaterialDetector

```python
# src/workbench/providers/change_detector/fallback.py

class AlwaysMaterialDetector(ChangeDetector):
    def __init__(self, source_type_name: str):
        self._source_type = source_type_name

    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult:
        return ChangeResult(
            is_material=True,
            is_terminal=False,
            is_critical=False,
            changed_fields=[],
            change_type="unknown",
            reason="No change detector registered; treating all changes as material",
        )

    def source_type(self) -> str:
        return self._source_type
```

A warning is logged once per source type at startup when this fallback is used. Combined with `supports_monitoring() == False` on non-monitoring adapters, the fallback is never actually invoked for sources that don't support monitoring — the routing step is gated on `supports_monitoring()` first.

### Material Field Sets (implemented in workbench-meta)

**PhabricatorChangeDetector** — material fields:

| Field | Material when |
|---|---|
| `status` | Any transition (needs_review → accepted, changes_planned, closed, etc.) |
| `review_stage` | Any transition |
| `comment_count` | Increase |
| CI status | pass → fail, fail → pass |

Terminal states: `published` (landed), `abandoned`.

Critical conditions: CI failure on a diff the user authored; blocking review requested.

**MetaTasksChangeDetector** — material fields:

| Field | Material when |
|---|---|
| `status` | Any transition (open → resolved, etc.) |
| `priority` | Any change |
| `assignee` | Any change |

Terminal states: `resolved`, `closed`, `duplicate`.

Critical conditions: SEV status change.

## Stable Source ID

### SourceAdapter Extension

```python
# src/workbench/providers/source/base.py  (additions to existing ABC)

class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        ...

    @abstractmethod
    def adapter_type(self) -> str:
        ...

    def supports_monitoring(self) -> bool:
        """Concrete method, not abstract. Default False.
        Override to True in adapters for mutable entities (diffs, tasks, PRs).
        Sources like email/calendar/chat inherit the default."""
        return False

    def stable_id(self, raw_item: RawItem) -> str:
        """Concrete method, not abstract. Default returns raw_item.id unchanged.
        Override in monitoring-capable adapters to strip volatile components
        (e.g., timestamps) from the source ID."""
        return raw_item.id

    def poll_returns_complete_set(self) -> bool:
        """Whether poll() returns ALL active entities regardless of the
        `since` parameter. When True, items absent from poll results are
        treated as terminal (disappeared). Default False — watermark-
        filtered adapters should NOT override this."""
        return False

    async def close(self) -> None:
        pass
```

Both `supports_monitoring()` and `stable_id()` are concrete methods with backward-compatible defaults. Existing adapters (Gmail, GCalendar, GChat) are unaffected.

### ID Migration

| Source | Current `RawItem.id` | Stable `source_id` via `stable_id()` |
|---|---|---|
| Phabricator | `{number}_{updated}` | `D{number}` |
| Meta Tasks | `{task_id}_{updated}` | `T{task_id}` |
| GitHub PRs | `gh-pr-{repo}-{number}` | `gh-pr-{repo}-{number}` (already stable) |
| GitHub Issues | `gh-issue-{repo}-{number}` | `gh-issue-{repo}-{number}` (already stable) |

Adapter implementations:

```python
# workbench-meta: PhabricatorAdapter
def supports_monitoring(self) -> bool:
    return True

def stable_id(self, raw_item: RawItem) -> str:
    number = json.loads(raw_item.raw_text)["number"]
    return f"D{number}"
```

```python
# workbench-meta: MetaTasksAdapter
def supports_monitoring(self) -> bool:
    return True

def stable_id(self, raw_item: RawItem) -> str:
    task_id = json.loads(raw_item.raw_text)["task_id"]
    return f"T{task_id}"
```

```python
# workbench: GitHubSourceAdapter
def supports_monitoring(self) -> bool:
    return True

# stable_id() not overridden — default returns raw_item.id which is already stable
```

On the first poll after this change, existing `processed` table rows with old compound keys will not match the new stable IDs. Those items get re-ingested once. This is a one-time cost with no data loss.

The scheduler uses `adapter.stable_id(raw_item)` as the `source_id` when calling both `ProcessedStore` and `ItemStore`.

## Re-Check Routing

The existing `WorkbenchScheduler._poll_one_source()` gains a post-poll routing step. No new cron job. The same per-source poll job runs both new ingestion and re-check within the same per-source `asyncio.Lock`.

```python
# src/workbench/pipeline/scheduler.py  (inside _poll_one_source, after getting raw_items)

async def _route_poll_results(
    self,
    source_id: str,
    adapter: SourceAdapter,
    detector: ChangeDetector,
    raw_items: list[RawItem],
    trigger: JobTrigger,
) -> int:
    """Route poll results: new items → enqueue, existing items → change detection.
    Returns count of items enqueued (new ingestion only)."""
    enqueued = 0
    seen_ids: set[str] = set()

    for raw_item in raw_items:
        sid = adapter.stable_id(raw_item)
        seen_ids.add(sid)

        existing = await self.stores.items.get_item_by_source_id(
            adapter.adapter_type(), sid
        )

        if existing is None:
            # New item — normal ingestion path
            try:
                await self.pipeline.enqueue(
                    raw_item.raw_text,
                    raw_item.source_type,
                    source_id=sid,
                    urgency_signals=raw_item.urgency_signals,
                    trigger=trigger,
                )
                enqueued += 1
            except Exception as e:
                logger.error("Failed to enqueue %s: %s", sid, e)
            continue

        # Existing item — change detection
        old_raw = _parse_raw(existing.raw_data)
        new_raw = json.loads(raw_item.raw_text)

        result = detector.detect(old_raw, new_raw)

        if result.is_terminal:
            await self._archive_terminal(existing)
            continue

        # Always update raw_data to latest snapshot
        await self.stores.items.update_raw_data(existing.id, raw_item)

        if result.is_material:
            self._debounce_mgr.schedule(existing.id, result, raw_item, old_raw)

    # Detect disappeared items only when poll returns a complete snapshot.
    # Watermark-filtered adapters return partial results — running
    # disappearance detection on a partial set would falsely archive
    # items that simply haven't changed since the watermark.
    if adapter.supports_monitoring() and adapter.poll_returns_complete_set():
        await self._detect_disappeared(adapter.adapter_type(), seen_ids)

    return enqueued


def _parse_raw(raw_data: dict) -> dict:
    """Extract the source JSON from Item.raw_data for comparison."""
    raw_text = raw_data.get("raw_text", "{}")
    return json.loads(raw_text) if isinstance(raw_text, str) else raw_text
```

### Disappeared Item Detection

Items present in the database but absent from the latest poll results are marked terminal. This covers the case where the source removes items (e.g., Phabricator's `--include-only-open` excludes landed diffs).

```python
async def _detect_disappeared(
    self,
    source_type: str,
    seen_ids: set[str],
) -> None:
    """Items in DB but not in latest poll → mark terminal."""
    active_items = await self.stores.items.get_active_by_source(source_type)
    for item in active_items:
        if item.source_id not in seen_ids:
            logger.info(
                "Item %s disappeared from %s; archiving",
                item.source_id, source_type,
            )
            await self._archive_terminal(item)
```

### Terminal Archival

```python
async def _archive_terminal(self, item: Item) -> None:
    """Archive an item and expire its pending triage card. No cooldown."""
    await self.stores.items.update_item(
        item.id, ItemUpdate(status=ItemStatus.ARCHIVED)
    )
    card = await self.stores.triage.get_card_by_item_id(item.id)
    if card and card.status in ("queued", "sent"):
        card.status = "expired"
        await self.stores.triage.update_card(card)
```

## Debounce

A 2-minute trailing-edge timer prevents rapid-fire re-triage when a source produces multiple updates in quick succession (e.g., CI status updates arriving seconds apart).

```python
# src/workbench/pipeline/debounce.py

class DebouncedChange(BaseModel):
    item_id: str
    merged_result: ChangeResult
    raw_item: RawItem
    old_raw: dict
    timer_handle: asyncio.TimerHandle | None = None

    class Config:
        arbitrary_types_allowed = True


class DebounceManager:
    def __init__(self, fire_callback, delay_seconds: float = 120.0):
        self._pending: dict[str, DebouncedChange] = {}
        self._fire_callback = fire_callback
        self._delay = delay_seconds

    def schedule(self, item_id: str, result: ChangeResult, raw_item: RawItem, old_raw: dict) -> None:
        loop = asyncio.get_running_loop()

        if item_id in self._pending:
            old_entry = self._pending[item_id]
            if old_entry.timer_handle is not None:
                old_entry.timer_handle.cancel()
            merged = self._merge_results(old_entry.merged_result, result)
            preserved_old_raw = old_entry.old_raw
        else:
            merged = result
            preserved_old_raw = old_raw

        handle = loop.call_later(
            self._delay,
            lambda iid=item_id: asyncio.ensure_future(self._fire(iid)),
        )

        self._pending[item_id] = DebouncedChange(
            item_id=item_id,
            merged_result=merged,
            raw_item=raw_item,
            old_raw=preserved_old_raw,
            timer_handle=handle,
        )

    async def _fire(self, item_id: str) -> None:
        entry = self._pending.pop(item_id, None)
        if entry is None:
            return
        await self._fire_callback(entry.item_id, entry.merged_result, entry.raw_item, entry.old_raw)

    @staticmethod
    def _merge_results(old: ChangeResult, new: ChangeResult) -> ChangeResult:
        merged_fields = list(dict.fromkeys(old.changed_fields + new.changed_fields))
        return ChangeResult(
            is_material=old.is_material or new.is_material,
            is_terminal=new.is_terminal,
            is_critical=old.is_critical or new.is_critical,
            changed_fields=merged_fields,
            change_type=new.change_type,
            reason=f"{old.reason}; {new.reason}",
        )

    def cancel(self, item_id: str) -> None:
        entry = self._pending.pop(item_id, None)
        if entry is not None and entry.timer_handle is not None:
            entry.timer_handle.cancel()

    def cancel_all(self) -> None:
        for entry in self._pending.values():
            if entry.timer_handle is not None:
                entry.timer_handle.cancel()
        self._pending.clear()

    @property
    def pending_count(self) -> int:
        return len(self._pending)
```

The debounce state is in-memory. On server restart, pending entries are lost. The next poll re-detects changes via the `ChangeDetector` comparing current raw data against stored `Item.raw_data`. Acceptable for single-user scale.

The `DebounceManager` is instantiated once in `WorkbenchScheduler.__init__()` and `cancel_all()` is called in `shutdown()`.

## ChangeContext and Card Re-Triage

### ChangeContext Model

```python
# src/workbench/models.py

class ChangeContext(BaseModel):
    change_type: str
    changed_fields: dict[str, dict[str, str]]
    change_summary: str
    previous_triage_action: str | None = None
    previous_priority: str | None = None
```

Built from `ChangeResult` + old/new raw data + existing triage card:

```python
def build_change_context(
    result: ChangeResult,
    old_raw: dict,
    new_raw: dict,
    previous_card: TriageCard | None,
) -> ChangeContext:
    changed_fields = {}
    for field in result.changed_fields:
        changed_fields[field] = {
            "old": str(old_raw.get(field, "")),
            "new": str(new_raw.get(field, "")),
        }

    prev_action = None
    prev_priority = None
    if previous_card and previous_card.status == "responded":
        prev_action = previous_card.response
        if previous_card.card_content:
            prev_priority = previous_card.card_content.get("priority")

    return ChangeContext(
        change_type=result.change_type,
        changed_fields=changed_fields,
        change_summary=result.reason,
        previous_triage_action=prev_action,
        previous_priority=prev_priority,
    )
```

### Card Generation Update

`generate_card()` in `src/workbench/pipeline/triage.py` gains an optional `change_context` parameter:

```python
async def generate_card(
    llm: LLMProvider,
    ext_item: ExtractedItem,
    enrichment: dict,
    source_type: str,
    *,
    memory: MemoryLayer | None = None,
    change_context: ChangeContext | None = None,
) -> TriageCard:
```

When `change_context` is provided, the LLM prompt includes the change details so it produces change-aware copy and contextual options. Re-triage card options differ from first-triage options:

- **First triage**: "Add as P2", "Defer 2h", "Skip", "Mute pattern", "Other"
- **Re-triage**: "Bump to P1", "Keep current priority", "Acknowledge change", "Drop"

The LLM generates these based on `ChangeContext` plus the previous triage action.

### Card Update Logic

```python
async def _fire_retriage(
    self,
    item_id: str,
    result: ChangeResult,
    raw_item: RawItem,
    old_raw: dict,
) -> None:
    """Called by DebounceManager after the 2-minute timer fires.
    old_raw is stashed at detection time (before update_raw_data overwrites it)."""
    item = await self.stores.items.get_item(item_id)
    if item is None or item.status == ItemStatus.ARCHIVED:
        return

    new_raw = json.loads(raw_item.raw_text)

    existing_card = await self.stores.triage.get_card_by_item_id(item.id)

    change_ctx = build_change_context(result, old_raw, new_raw, existing_card)

    # Check daily cap (critical changes bypass)
    if not result.is_critical:
        sent_today = await self.stores.triage.count_sent_today()
        if sent_today >= self.config.triage.daily_cap:
            logger.info("Daily cap reached; skipping re-triage for %s", item.id)
            return

    # Build an ExtractedItem from the raw_item for generate_card
    ext_item = ExtractedItem(
        summary=item.summary,
        category=item.category,
        source_context=raw_item.source_label,
        raw_item=RawItem(
            id=raw_item.id,
            source_type=raw_item.source_type,
            source_label=raw_item.source_label,
            raw_text=raw_item.raw_text,
            urgency_signals=raw_item.urgency_signals,
        ),
    )

    enrichment = await enrich_item(self.pipeline.enricher, ext_item, memory=self.memory)
    new_card = await generate_card(
        self.llm, ext_item, enrichment, raw_item.source_type,
        memory=self.memory,
        change_context=change_ctx,
    )
    new_card.item_id = item.id

    if existing_card is None:
        # No previous card — create and send
        new_card.expires_at = datetime.now(timezone.utc) + timedelta(
            days=self.pipeline.triage_expiry_days
        )
        await self.stores.triage.save_card(new_card)
        return

    # Re-read card status to mitigate race condition (user may have
    # responded between the initial read and now)
    existing_card = await self.stores.triage.get_card(existing_card.id)

    # Clear deferral if set (D13)
    if existing_card.deferred_until is not None:
        await self.stores.triage.clear_deferral(existing_card.id)

    if existing_card.status == "queued":
        # Not yet sent — replace content in-place
        existing_card.card_content = new_card.card_content
        existing_card.options = new_card.options
        existing_card.relevance_score = new_card.relevance_score
        existing_card.confidence_score = new_card.confidence_score
        await self.stores.triage.update_card(existing_card)

    elif existing_card.status == "sent":
        # Already sent — update in-place and notify via messenger
        existing_card.card_content = new_card.card_content
        existing_card.options = new_card.options
        existing_card.relevance_score = new_card.relevance_score
        existing_card.confidence_score = new_card.confidence_score
        await self.stores.triage.update_card(existing_card)
        if self.messenger:
            text = "[Updated] " + format_card_for_chat(existing_card)
            success = await self.messenger.update_message(
                existing_card.bot_message_id, text
            )
            if not success:
                await self.messenger.send_card(text)

    else:
        # Card already responded/expired — create new card for same item
        new_card.expires_at = datetime.now(timezone.utc) + timedelta(
            days=self.pipeline.triage_expiry_days
        )
        await self.stores.triage.save_card(new_card)
```

### Deferred Cards

When a material change is detected for an item with a deferred card (`deferred_until` is set), the deferral is cancelled via `stores.triage.clear_deferral(card_id)` before the card content is updated. This call runs unconditionally for both `queued` and `sent` cards — it's a no-op if `deferred_until` is already NULL. The card is then regenerated with change context and re-enters the send queue immediately (subject to the daily cap unless the change is critical).

## Messenger Update

### Interface Extension

```python
# src/workbench/providers/messenger/base.py  (addition to existing ABC)

class Messenger(ABC):
    @abstractmethod
    async def send_card(self, text: str) -> str:
        ...

    @abstractmethod
    async def poll_responses(self, message_id: str) -> list[dict]:
        ...

    async def update_message(self, message_id: str, text: str) -> bool:
        """Update an existing message in-place. Returns True on success.
        Default returns False (update not supported). Messengers that
        support in-place editing override this method."""
        return False
```

### ConsoleMessenger

```python
# src/workbench/providers/messenger/console.py
async def update_message(self, message_id: str, text: str) -> bool:
    print(f"[UPDATE {message_id}] {text}")
    return True
```

### Google Chat (workbench-meta)

```python
# workbench-meta: GoogleChatMessenger
async def update_message(self, message_id: str, text: str) -> bool:
    try:
        await self._patch_message(message_id, text)
        return True
    except Exception:
        logger.warning("Failed to update message %s", message_id)
        return False
```

When `update_message` returns `False`, the caller falls back to `send_card()`.

## Daily Cap Interaction

Re-triage cards count against the daily triage cap, same as first-triage cards. The `is_critical` field on `ChangeResult` bypasses the cap.

Critical conditions (classified by the `ChangeDetector`, not by LLM):
- CI failure on a diff the user authored
- Blocking review requested on the user's diff
- SEV status change on a monitored task

The daily cap check runs before `generate_card()` (the LLM call), so capped items skip unnecessary LLM spend.

## YAML Configuration

```yaml
sources:
  - class: workbench_meta.providers.source.phabricator.PhabricatorAdapter
    schedule: "*/5 * * * *"
    config:
      limit: 50
    change_detector:
      class: workbench_meta.providers.change_detector.phabricator.PhabricatorChangeDetector

  - class: workbench_meta.providers.source.meta_tasks.MetaTasksAdapter
    schedule: "*/10 * * * *"
    config:
      owner: anshulverma
    change_detector:
      class: workbench_meta.providers.change_detector.meta_tasks.MetaTasksChangeDetector

  - class: workbench_meta.providers.source.gmail.GmailAdapter
    schedule: "*/15 * * * *"
    connection: google
    # No change_detector — email doesn't support monitoring
```

When `change_detector` is omitted, `AlwaysMaterialDetector` is instantiated as fallback. But because re-check routing is gated on `adapter.supports_monitoring()`, the fallback detector is never called for non-monitoring sources — the routing step skips change detection entirely.

## New Store Methods

### ItemStore additions

```python
class ItemStore(ABC):
    # ... existing methods (get_items, get_item, save_item, update_item, ...) ...

    @abstractmethod
    async def get_item_by_source_id(
        self, source_type: str, source_id: str
    ) -> Item | None:
        """Look up an item by its stable source identifier.
        Distinct from existing get_items_by_source(source_type) which
        returns all items for a source type."""
        ...

    @abstractmethod
    async def get_active_by_source(self, source_type: str) -> list[Item]:
        """All non-terminal items for a source type
        (status NOT IN archived, done)."""
        ...

    @abstractmethod
    async def update_raw_data(self, item_id: str, raw_item: RawItem) -> None:
        """Update Item.raw_data with fresh source payload (full RawItem dump)."""
        ...
```

PostgreSQL implementation:

```sql
-- get_item_by_source_id
SELECT * FROM items
WHERE source_type = $1 AND source_id = $2
  AND status NOT IN ('archived', 'done')
ORDER BY created_at DESC LIMIT 1;

-- get_active_by_source
SELECT * FROM items
WHERE source_type = $1
  AND status NOT IN ('archived', 'done');

-- update_raw_data ($2 = json.dumps(raw_item.model_dump()))
UPDATE items SET raw_data = $2::jsonb, updated_at = NOW() WHERE id = $1;
```

### TriageStore additions

```python
class TriageStore(ABC):
    # ... existing methods (get_pending, save_card, update_card, ...) ...

    @abstractmethod
    async def get_card_by_item_id(self, item_id: str) -> TriageCard | None:
        """Most recent non-expired card for an item."""
        ...

    @abstractmethod
    async def clear_deferral(self, card_id: str) -> None:
        """Set deferred_until = NULL on a card."""
        ...
```

PostgreSQL implementation:

```sql
-- get_card_by_item_id
SELECT * FROM triage_cards
WHERE item_id = $1 AND status != 'expired'
ORDER BY created_at DESC LIMIT 1;

-- clear_deferral
UPDATE triage_cards SET deferred_until = NULL, updated_at = NOW() WHERE id = $1;
```

### Database indexes

```sql
CREATE INDEX idx_items_source_lookup ON items (source_type, source_id);
CREATE INDEX idx_triage_cards_item_id ON triage_cards (item_id);
```

## File Changes

### workbench (this repo)

| File | Change |
|---|---|
| `src/workbench/providers/change_detector/__init__.py` | New package |
| `src/workbench/providers/change_detector/base.py` | `ChangeDetector` ABC, `ChangeResult` model |
| `src/workbench/providers/change_detector/fallback.py` | `AlwaysMaterialDetector` |
| `src/workbench/providers/source/base.py` | Add `supports_monitoring()`, `stable_id()`, `poll_returns_complete_set()` concrete methods |
| `src/workbench/models.py` | Add `ChangeContext` model |
| `src/workbench/pipeline/debounce.py` | `DebounceManager`, `DebouncedChange` |
| `src/workbench/pipeline/change_context.py` | `build_change_context()` |
| `src/workbench/pipeline/scheduler.py` | Add `_route_poll_results()`, `_detect_disappeared()`, `_archive_terminal()`, `_fire_retriage()`, detector resolution at startup |
| `src/workbench/pipeline/triage.py` | Add `change_context` param to `generate_card()`, add `build_change_context()` |
| `src/workbench/providers/messenger/base.py` | Add `update_message()` with default `return False` |
| `src/workbench/providers/messenger/console.py` | Implement `update_message()` |
| `src/workbench/storage/base.py` | Add `get_item_by_source_id()`, `get_active_by_source()`, `update_raw_data()` to `ItemStore`; add `get_card_by_item_id()`, `clear_deferral()` to `TriageStore` |
| `src/workbench/storage/postgres/items.py` | Implement new `ItemStore` methods |
| `src/workbench/storage/postgres/triage.py` | Implement new `TriageStore` methods |
| `src/workbench/migrations/versions/` | New migration: indexes on `items(source_type, source_id)` and `triage_cards(item_id)` |
| `config.example.yml` | Document `change_detector` option in source config |

### workbench-meta (separate repo)

| File | Change |
|---|---|
| `workbench_meta/providers/change_detector/__init__.py` | New package |
| `workbench_meta/providers/change_detector/phabricator.py` | `PhabricatorChangeDetector` |
| `workbench_meta/providers/change_detector/meta_tasks.py` | `MetaTasksChangeDetector` |
| `workbench_meta/providers/source/phabricator.py` | Add `supports_monitoring()`, `stable_id()` |
| `workbench_meta/providers/source/meta_tasks.py` | Add `supports_monitoring()`, `stable_id()` |
| `workbench_meta/providers/messenger/gchat.py` | Implement `update_message()` |
| `config.meta.yml` | Add `change_detector` entries to source configs |

### Tests

| File | What it tests |
|---|---|
| `tests/test_change_detector.py` | `ChangeResult`, `AlwaysMaterialDetector` |
| `tests/test_recheck_routing.py` | Poll routing: new → enqueue, existing → detect, disappeared → archive |
| `tests/test_debounce.py` | `DebounceManager`: single fire, merge, cancel |
| `tests/test_card_retriage.py` | Card update: queued/sent/responded/deferred paths, race mitigation |

## Verification

1. `ChangeResult` constructs correctly. `is_critical` is independent of `is_material`.
2. `AlwaysMaterialDetector` returns `is_material=True, is_terminal=False, is_critical=False` for any input pair.
3. `DebounceManager`: single change fires after delay; second change within window resets timer; merged result combines `changed_fields`; `is_critical=True` survives merge; `cancel_all()` prevents pending fires.
4. Card update routing: queued → in-place update; sent → in-place + messenger update; responded → new card; sent-that-became-responded between reads → new card (race mitigation).
5. Deferred card: material change on deferred card clears `deferred_until` and regenerates in-place.
6. Daily cap: re-triage counted against cap; critical changes bypass cap.
7. New item path: `RawItem` with no existing `Item` → `pipeline.enqueue()` called, change detector not called.
8. Material change path: `RawItem` with existing `Item`, detector returns `is_material=True` → `_fire_retriage()` called after debounce.
9. Non-material change path: detector returns `is_material=False` → `raw_data` updated silently.
10. Terminal path: detector returns `is_terminal=True` → item archived, card expired.
11. Disappeared item path: item in DB but absent from poll → item archived, card expired.
12. Stable ID migration: first poll with stable IDs → old compound-key items re-ingested once, subsequent polls match correctly.
13. Messenger update fallback: `update_message` returns `False` → `send_card` called.

## Resolved Questions

| # | Question | Resolution |
|---|---|---|
| D1 | ChangeDetector interface shape | Synchronous, two dicts in, `ChangeResult` out. No LLM. |
| D2 | What counts as material? | Source-type-specific field sets hard-coded in each detector. |
| D3 | Where does old state come from? | `Item.raw_data` JSONB, already stored. No snapshot table. |
| D4 | How to match old and new items? | Stable `source_id` (D12345, T67890). Adapters migrated from compound keys. |
| D5 | Separate cron job for monitoring? | No. Single poll serves both ingestion and re-check. |
| D6 | No detector registered? | `AlwaysMaterialDetector` fallback, warning logged once at startup. |
| D7 | Config shape? | `change_detector` field per source in YAML, same provider pattern. |
| D8 | SourceAdapter changes? | `supports_monitoring()` and `stable_id()` concrete methods with backward-compatible defaults. |
| D9 | Terminal detection? | Dual signal: detector returns `is_terminal`, or item disappears from poll. |
| D10 | Card update vs new card? | Queued/sent: in-place update. Responded/expired: new card. |
| D11 | Messenger update? | `update_message(message_id, text) -> bool`. `False` → fallback to `send_card`. |
| D12 | Change-aware card copy? | `ChangeContext` model passed to `generate_card()`. LLM produces contextual copy and options. |
| D13 | Deferred cards? | Material change clears `deferred_until`, regenerates card in-place, re-enters send queue. |
| D14 | Debounce strategy? | 2-minute trailing-edge in-memory timer per `item_id`. Lost on restart (re-detected next poll). |
| D15 | Daily cap interaction? | Re-triage counts against cap. `is_critical` bypasses cap. |
| D16 | New store methods? | `get_item_by_source_id`, `get_active_by_source`, `update_raw_data` on `ItemStore`; `get_card_by_item_id`, `clear_deferral` on `TriageStore`. |
| D17 | Race condition? | Re-read card status before update. If status changed, create new card instead. |
| D18 | Terminal state? | Immediate archive + expire card. No cooldown. |
| D19 | Non-monitoring sources? | `supports_monitoring() == False`. Re-check routing skipped entirely. |
| D20 | Scale? | Single-user, ~50 items per source. No tiered cadence. |
| D21 | Re-triage options? | LLM-generated from `ChangeContext`. Contextual options differ from first-triage. |

## Out of Scope

- **Tiered polling cadence** (polling high-priority items more often). Not needed at single-user scale.
- **Persistent debounce state**. In-memory is sufficient; restart re-detects on next poll.
- **Monitored items table or view**. Items from monitoring-capable sources with non-terminal status are implicitly monitored.
- **LLM-based change detection**. Detectors are synchronous field comparisons.
- **Batch re-triage**. Each changed item is re-triaged individually.
- **Historical change log**. Only the latest `raw_data` is kept.
- **User-configurable material field sets**. Hard-coded per detector.
- **Cross-source change correlation** (e.g., "this task changed because this diff landed").

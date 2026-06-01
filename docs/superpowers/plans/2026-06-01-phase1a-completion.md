# Phase 1a Completion — End-to-End Triage Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps so the full pipeline runs end-to-end: source poll → ingestion queue → worker → extraction → filter → enrichment → triage card → Google Chat → user responds → interaction log.

**Architecture:** Six pieces are missing or incomplete. (1) A Google Chat messenger provider that sends triage cards and polls responses via the Google Chat REST API with service account auth and automatic token refresh. (2) A source polling job in the scheduler that periodically calls each source adapter's `poll(since)` and enqueues raw items, tracking `last_polled_at` per source in PostgreSQL via the ConfigStore. (3) Fix `GitHubSourceAdapter.poll()` to use the `since` parameter as a date filter. (4) A lightweight GitHub enricher that fetches PR/issue details so triage cards carry enough context for decisions. (5) Startup of the ingestion queue worker in the FastAPI lifespan. (6) Pipeline fix to populate `Item.raw_data` with source adapter's raw content.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, httpx, Google Chat REST API (`google-auth` for service account credentials), APScheduler, pytest + pytest-asyncio.

---

## File Structure

### New files
- `src/workbench/providers/messenger/google_chat.py` — Google Chat messenger (REST API + service account)
- `src/workbench/providers/enrichment/github.py` — lightweight GitHub enricher (PR/issue details via `gh` CLI)
- `tests/test_google_chat_messenger.py` — unit tests for the messenger
- `tests/test_github_enricher.py` — unit tests for the enricher

### Modified files
- `src/workbench/pipeline/scheduler.py` — add `_poll_sources()` job, accept `sources` param, use configurable triage poll interval
- `src/workbench/pipeline/engine.py` — populate `Item.raw_data` with raw source content
- `src/workbench/pipeline/triage.py` — update `format_card_for_chat` to render labeled enrichment fields
- `src/workbench/providers/source/github.py` — use `since` parameter to filter by date
- `src/workbench/config.py` — add `triage_poll_interval_seconds` to `TriageConfig`
- `src/workbench/main.py` — start ingestion queue worker in lifespan, pass sources to scheduler
- `config.example.yml` — show Google Chat config, triage poll interval
- `pyproject.toml` — add `google-auth` dependency
- `tests/test_pipeline.py` — source polling tests, end-to-end smoke tests

---

## Task 1: Google Chat Messenger Provider

**Files:**
- Create: `src/workbench/providers/messenger/google_chat.py`
- Test: `tests/test_google_chat_messenger.py`

This provider uses the Google Chat REST API to send triage cards as text messages and poll for user responses. Auth uses a GCP service account with automatic token refresh (tokens expire after ~1 hour; the `Credentials` object handles refresh transparently). The provider sends one card at a time as a plain text message. The user replies with a number. `poll_responses()` lists messages in the space after the sent message and returns only human messages.

### Step 1: Write the failing tests

- [ ] **Step 1.1: Create the test file with unit tests**

```python
# tests/test_google_chat_messenger.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.providers.messenger.google_chat import GoogleChatMessenger


@pytest.fixture
def mock_http_client():
    return AsyncMock()


@pytest.fixture
def messenger(mock_http_client):
    config = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/AAQA-RI-cA4",
        service_account_key_path="/fake/key.json",
    )
    m = GoogleChatMessenger(config)
    m._client = mock_http_client
    m._credentials = MagicMock()
    m._credentials.valid = True
    m._credentials.token = "fake-token"
    return m


@pytest.mark.asyncio
async def test_send_card_posts_message(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"name": "spaces/AAQA-RI-cA4/messages/msg123"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    msg_id = await messenger.send_card("*Test Card*\n1. Add todo\n2. Skip")

    assert msg_id == "spaces/AAQA-RI-cA4/messages/msg123"
    mock_http_client.post.assert_called_once()
    call_kwargs = mock_http_client.post.call_args
    assert "text" in call_kwargs[1]["json"]


@pytest.mark.asyncio
async def test_send_card_raises_on_failure(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = Exception("API error")
    mock_http_client.post.return_value = mock_response

    with pytest.raises(Exception, match="API error"):
        await messenger.send_card("test")


@pytest.mark.asyncio
async def test_send_card_refreshes_expired_token(messenger, mock_http_client):
    messenger._credentials.valid = False

    mock_response = MagicMock()
    mock_response.json.return_value = {"name": "spaces/x/messages/msg1"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    await messenger.send_card("test")

    messenger._credentials.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_poll_responses_returns_messages_after_id(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg100", "sender": {"type": "BOT"}, "text": "card"},
            {"name": "spaces/x/messages/msg101", "sender": {"type": "HUMAN"}, "text": "1"},
            {"name": "spaces/x/messages/msg102", "sender": {"type": "HUMAN"}, "text": "skip all"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses("spaces/x/messages/msg100")

    assert len(responses) == 2
    assert responses[0]["text"] == "1"
    assert responses[1]["text"] == "skip all"
    # Verify chronological ordering is requested
    call_kwargs = mock_http_client.get.call_args
    assert call_kwargs[1]["params"]["orderBy"] == "createTime asc"


@pytest.mark.asyncio
async def test_poll_responses_filters_bot_messages(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg100", "sender": {"type": "BOT"}, "text": "card"},
            {"name": "spaces/x/messages/msg101", "sender": {"type": "BOT"}, "text": "Got it"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses("spaces/x/messages/msg100")
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_poll_responses_no_since_returns_all_human(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg1", "sender": {"type": "HUMAN"}, "text": "2"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses(None)
    assert len(responses) == 1


@pytest.mark.asyncio
async def test_close_closes_http_client(messenger, mock_http_client):
    await messenger.close()
    mock_http_client.aclose.assert_called_once()


def test_provider_config_validation():
    config = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/ABC",
        service_account_key_path="/path/to/key.json",
    )
    assert config.space_id == "spaces/ABC"
```

- [ ] **Step 1.2: Run the tests to confirm they fail**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_google_chat_messenger.py -x -v`
Expected: `ModuleNotFoundError: No module named 'workbench.providers.messenger.google_chat'`

### Step 2: Implement the Google Chat messenger

- [ ] **Step 2.1: Write the implementation**

```python
# src/workbench/providers/messenger/google_chat.py
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from workbench.providers.messenger.base import Messenger

logger = logging.getLogger(__name__)

CHAT_API_BASE = "https://chat.googleapis.com/v1"


class GoogleChatMessenger(Messenger):
    class ProviderConfig(BaseModel):
        space_id: str
        service_account_key_path: str
        timeout_seconds: int = 30

    def __init__(self, config: ProviderConfig):
        self.space_id = config.space_id
        self._key_path = config.service_account_key_path
        self._timeout = config.timeout_seconds
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._credentials = None

    def _ensure_credentials(self) -> None:
        if self._credentials is None:
            import google.oauth2.service_account
            self._credentials = google.oauth2.service_account.Credentials.from_service_account_file(
                self._key_path,
                scopes=["https://www.googleapis.com/auth/chat.bot"],
            )

    def _get_headers(self) -> dict[str, str]:
        self._ensure_credentials()
        if not self._credentials.valid:
            import google.auth.transport.requests
            self._credentials.refresh(google.auth.transport.requests.Request())
        return {
            "Authorization": f"Bearer {self._credentials.token}",
            "Content-Type": "application/json",
        }

    async def send_card(self, card_text: str) -> str:
        url = f"{CHAT_API_BASE}/{self.space_id}/messages"
        headers = self._get_headers()
        resp = await self._client.post(url, headers=headers, json={"text": card_text})
        resp.raise_for_status()
        msg_name = resp.json()["name"]
        logger.info("Sent triage card: %s", msg_name)
        return msg_name

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        url = f"{CHAT_API_BASE}/{self.space_id}/messages"
        headers = self._get_headers()
        resp = await self._client.get(url, headers=headers, params={"orderBy": "createTime asc"})
        resp.raise_for_status()
        messages = resp.json().get("messages", [])

        found_since = since_message_id is None
        results = []
        for msg in messages:
            if not found_since:
                if msg.get("name") == since_message_id:
                    found_since = True
                continue
            if msg.get("sender", {}).get("type") == "HUMAN":
                results.append({"text": msg.get("text", ""), "message_id": msg["name"]})
        return results

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 2.2: Run the tests to confirm they pass**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_google_chat_messenger.py -x -v`
Expected: All 9 tests pass.

- [ ] **Step 2.3: Commit**

```bash
git commit -m "feat: add Google Chat messenger provider with token refresh"
```

---

## Task 2: Configurable Triage Poll Interval

**Files:**
- Modify: `src/workbench/config.py:28-31` (TriageConfig)
- Modify: `src/workbench/pipeline/scheduler.py:34` (triage_queue job interval)
- Test: `tests/test_config.py`

### Step 1: Write the failing test

- [ ] **Step 1.1: Add config test**

```python
# Append to tests/test_config.py

def test_triage_config_poll_interval_default():
    from workbench.config import TriageConfig
    config = TriageConfig()
    assert config.triage_poll_interval_seconds == 10


def test_triage_config_poll_interval_custom():
    from workbench.config import TriageConfig
    config = TriageConfig(triage_poll_interval_seconds=1)
    assert config.triage_poll_interval_seconds == 1
```

- [ ] **Step 1.2: Run to confirm failure**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_config.py -x -v -k "poll_interval"`
Expected: `TypeError` — `TriageConfig` has no field `triage_poll_interval_seconds`.

### Step 2: Implement

- [ ] **Step 2.1: Add `triage_poll_interval_seconds` to `TriageConfig` in `config.py`**

In `src/workbench/config.py`, update `TriageConfig`:

```python
class TriageConfig(BaseModel):
    daily_cap: int = 20
    expiry_days: int = 7
    timeout_minutes: int = 30
    triage_poll_interval_seconds: int = 10
```

- [ ] **Step 2.2: Update the scheduler to use the config value**

In `src/workbench/pipeline/scheduler.py`, change the triage_queue job in `start()` from:

```python
("triage_queue", "interval", {"seconds": 30}, self._manage_triage_queue),
```

to:

```python
("triage_queue", "interval", {"seconds": self.config.triage.triage_poll_interval_seconds}, self._manage_triage_queue),
```

- [ ] **Step 2.3: Run tests**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_config.py -x -v -k "poll_interval"`
Expected: Both tests pass.

- [ ] **Step 2.4: Commit**

```bash
git commit -m "feat: make triage poll interval configurable (default 10s)"
```

---

## Task 3: Source Polling with `last_polled_at` Tracking

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py` — add `_poll_sources()` method, accept `sources` param
- Modify: `src/workbench/providers/source/github.py` — use `since` filter in `gh` CLI
- Test: `tests/test_pipeline.py`

The scheduler tracks `last_polled_at` per source adapter in the `ConfigStore` (existing key-value table in PostgreSQL). After each successful poll, it writes the timestamp. Before each poll, it reads the timestamp and passes it as `since` to the adapter. On first poll (no stored timestamp), `since=None` fetches all open items.

The `GitHubSourceAdapter` is updated to pass `since` as a `--search "updated:>DATETIME"` filter to `gh pr list` and `gh issue list`.

### Step 1: Write the failing tests

- [ ] **Step 1.1: Add source polling tests to `test_pipeline.py`**

```python
# Append to tests/test_pipeline.py

@pytest.mark.asyncio
async def test_scheduler_poll_sources_enqueues_items(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type.return_value = "github"
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
        RawItem(id="gh-pr-2", source_type="github", source_label="PR #2", raw_text='{"number":2}'),
    ]

    messenger = AsyncMock()
    scheduler = WorkbenchScheduler(stores, memory, pipeline, messenger, config, sources=[mock_source])

    await scheduler._poll_sources()

    mock_source.poll.assert_called_once()
    assert await stores.ingestion_queue.queue_depth() == 2


@pytest.mark.asyncio
async def test_scheduler_poll_sources_tracks_last_polled(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type.return_value = "github"
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
    ]

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[mock_source])

    # First poll: since=None (no stored timestamp yet)
    await scheduler._poll_sources()
    assert mock_source.poll.call_args.kwargs["since"] is None

    # Verify last_polled_at was stored in ConfigStore
    stored = await stores.config.get("source_last_polled:github")
    assert stored is not None

    # Second poll: since should be the stored timestamp
    mock_source.poll.reset_mock()
    mock_source.poll.return_value = []
    await scheduler._poll_sources()
    assert mock_source.poll.call_args.kwargs["since"] is not None


@pytest.mark.asyncio
async def test_scheduler_poll_sources_skips_duplicates(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type.return_value = "github"
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
    ]

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[mock_source])

    await scheduler._poll_sources()
    await scheduler._poll_sources()

    # Second poll returns the same item — dedup should skip it
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_scheduler_poll_sources_handles_adapter_failure(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from unittest.mock import AsyncMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    failing_source = AsyncMock()
    failing_source.adapter_type.return_value = "github"
    failing_source.poll.side_effect = Exception("API timeout")

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[failing_source])

    # Should not raise — adapter failures are caught and logged
    await scheduler._poll_sources()
    assert await stores.ingestion_queue.queue_depth() == 0

    # last_polled_at should NOT be updated on failure
    stored = await stores.config.get("source_last_polled:github")
    assert stored is None
```

- [ ] **Step 1.2: Run to confirm failure**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "poll_sources"`
Expected: `TypeError` — `WorkbenchScheduler.__init__()` does not accept `sources`.

### Step 2: Implement source polling in the scheduler

- [ ] **Step 2.1: Update `WorkbenchScheduler.__init__` and `start()`, add `_poll_sources()`**

In `src/workbench/pipeline/scheduler.py`:

Add `JobTrigger` to imports:

```python
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, JobTrigger, Priority, TriageResponse,
)
```

Replace `__init__` and `start`:

```python
class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine,
                 messenger: Messenger | None, config: AppConfig, sources: list | None = None):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.config = config
        self.sources = sources or []
        self.scheduler = AsyncIOScheduler()

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
```

Add `_poll_sources` method (before `_manage_triage_queue`):

```python
    async def _poll_sources(self):
        for source in self.sources:
            adapter_type = source.adapter_type()
            try:
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

- [ ] **Step 2.2: Run the tests to confirm they pass**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "poll_sources"`
Expected: All 4 source polling tests pass.

- [ ] **Step 2.3: Commit**

```bash
git commit -m "feat: add source polling with last_polled_at tracking in ConfigStore"
```

### Step 3: Update GitHubSourceAdapter to use `since`

- [ ] **Step 3.1: Update `poll()` in `github.py` to pass `since` as a search filter**

In `src/workbench/providers/source/github.py`, update the `poll` method:

```python
    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        items = []
        search_filter = []
        if since:
            search_filter = ["--search", f"updated:>{since.strftime('%Y-%m-%dT%H:%M:%SZ')}"]

        for repo in self.repos:
            prs = await self._gh_json("pr", "list", "--repo", repo,
                                       *search_filter,
                                       "--json", "number,title,updatedAt,url,author")
            for pr in prs:
                items.append(RawItem(
                    id=f"gh-pr-{repo}-{pr['number']}",
                    source_type="github",
                    source_label=f"PR #{pr['number']} — {pr['title']}",
                    raw_text=json.dumps(pr),
                    urgency_signals={"type": "pull_request"},
                ))

            issues = await self._gh_json("issue", "list", "--repo", repo,
                                          *search_filter,
                                          "--json", "number,title,updatedAt,url,author")
            for issue in issues:
                items.append(RawItem(
                    id=f"gh-issue-{repo}-{issue['number']}",
                    source_type="github",
                    source_label=f"Issue #{issue['number']} — {issue['title']}",
                    raw_text=json.dumps(issue),
                    urgency_signals={"type": "issue"},
                ))
        return items
```

- [ ] **Step 3.2: Run the full test suite**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -x -v`
Expected: All tests pass.

- [ ] **Step 3.3: Commit**

```bash
git commit -m "feat: GitHubSourceAdapter uses since filter for incremental polling"
```

---

## Task 4: Populate Item.raw_data and Update Card Rendering

**Files:**
- Modify: `src/workbench/pipeline/engine.py:100-143` — set `raw_data` on items
- Modify: `src/workbench/pipeline/triage.py:7-24` — render labeled enrichment fields
- Test: `tests/test_pipeline.py`

### Step 1: Write the failing tests

- [ ] **Step 1.1: Add tests for raw_data and card rendering**

```python
# Append to tests/test_pipeline.py

@pytest.mark.asyncio
async def test_auto_include_populates_raw_data(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    raw = RawItem(
        id="D123", source_type="diff", source_label="D123",
        raw_text='{"number": 123, "title": "fix auth"}',
        urgency_signals={"type": "pull_request"},
    )
    job = await engine.enqueue(raw.raw_text, "diff")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].raw_data != {}
    assert items[0].raw_data["raw_text"] == '{"number": 123, "title": "fix auth"}'


@pytest.mark.asyncio
async def test_triage_item_populates_raw_data(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    raw = RawItem(
        id="D456", source_type="diff", source_label="D456",
        raw_text='{"number": 456, "title": "add tests"}',
    )
    job = await engine.enqueue(raw.raw_text, "diff")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    assert items[0].raw_data["source_type"] == "diff"


def test_format_card_with_enrichment_context():
    card = TriageCard(
        card_content={
            "summary": "Review D123: fix auth",
            "source_type": "github",
            "enrichment": {
                "context": {
                    "author": "alice",
                    "files_changed": 3,
                    "review_status": "changes_requested",
                    "labels": "security, auth",
                }
            },
        },
        options=[
            TriageOption(label="Add todo (P1)", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "alice" in text
    assert "3 files" in text
    assert "changes requested" in text


def test_format_card_without_enrichment():
    card = TriageCard(
        card_content={"summary": "Some item", "source_type": "manual"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "Some item" in text
    # No enrichment line should appear
    assert "By" not in text
```

- [ ] **Step 1.2: Run to confirm failure**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "raw_data or format_card_with_enrichment"`
Expected: `raw_data` tests fail (empty dict), enrichment rendering test fails (no labeled format).

### Step 2: Populate Item.raw_data

- [ ] **Step 2.1: Update `_process_extracted_item` in `engine.py`**

In `src/workbench/pipeline/engine.py`, add `raw_data=ext_item.raw_item.model_dump()` when creating items.

In the `auto_include` branch (~line 101):

```python
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P2,
                status=ItemStatus.ACTIVE,
                raw_data=ext_item.raw_item.model_dump(),
            )
```

In the `triage` branch (~line 126):

```python
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.TRIAGED, priority=Priority.PENDING,
                status=ItemStatus.PENDING_TRIAGE,
                raw_data=ext_item.raw_item.model_dump(),
            )
```

- [ ] **Step 2.2: Run raw_data tests**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "raw_data"`
Expected: Both tests pass.

### Step 3: Update card rendering

- [ ] **Step 3.1: Update `format_card_for_chat` in `triage.py`**

Replace the `format_card_for_chat` function in `src/workbench/pipeline/triage.py`:

```python
def format_card_for_chat(card: TriageCard, position: int = 1, total: int = 1) -> str:
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
        # Render any remaining keys not handled above
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

- [ ] **Step 3.2: Run rendering tests**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "format_card"`
Expected: All format_card tests pass (including existing `test_format_card_for_chat`).

- [ ] **Step 3.3: Commit**

```bash
git commit -m "feat: populate Item.raw_data, render labeled enrichment in triage cards"
```

---

## Task 5: Lightweight GitHub Enricher

**Files:**
- Create: `src/workbench/providers/enrichment/github.py`
- Test: `tests/test_github_enricher.py`

A lightweight enricher that implements the existing `ContextEnricher` interface. For `source_type="github"`, it parses the raw PR/issue JSON from the source adapter, then calls `gh pr view` or `gh issue view` to fetch additional details (files changed, review status, labels, CI status). For non-GitHub items, it returns the same empty result as the stub enricher. No orchestrator framework, no entity detection, no chaining — just one `gh` CLI call per item.

### Step 1: Write the failing tests

- [ ] **Step 1.1: Create the test file**

```python
# tests/test_github_enricher.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from workbench.providers.enrichment.github import GitHubEnricher
from workbench.models import ExtractedItem, ItemCategory, RawItem, EnrichmentBudget


def _make_item(source_type="github", raw_text=None, source_id="gh-pr-owner/repo-42"):
    if raw_text is None:
        raw_text = json.dumps({
            "number": 42,
            "title": "Fix auth flow",
            "url": "https://github.com/owner/repo/pull/42",
            "author": {"login": "alice"},
        })
    return ExtractedItem(
        summary="Fix auth flow",
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=RawItem(
            id=source_id,
            source_type=source_type,
            source_label="PR #42",
            raw_text=raw_text,
        ),
    )


@pytest.fixture
def enricher():
    return GitHubEnricher()


@pytest.mark.asyncio
async def test_enrich_github_pr(enricher):
    item = _make_item()
    gh_view_output = json.dumps({
        "files": [{"path": "auth.py"}, {"path": "tests/test_auth.py"}],
        "reviewDecision": "CHANGES_REQUESTED",
        "labels": [{"name": "security"}, {"name": "auth"}],
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    })

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=json.loads(gh_view_output)):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert ctx["author"] == "alice"
    assert ctx["files_changed"] == 2
    assert ctx["review_status"] == "changes_requested"
    assert "security" in ctx["labels"]
    assert result["calls_made"] == 1


@pytest.mark.asyncio
async def test_enrich_github_issue(enricher):
    item = _make_item(
        source_id="gh-issue-owner/repo-10",
        raw_text=json.dumps({
            "number": 10,
            "title": "Bug report",
            "url": "https://github.com/owner/repo/issues/10",
            "author": {"login": "bob"},
        }),
    )
    gh_view_output = {
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "carol"}],
        "comments": [{"body": "looking into it"}],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert ctx["author"] == "bob"
    assert ctx["assignees"] == "carol"
    assert ctx["comment_count"] == 1


@pytest.mark.asyncio
async def test_enrich_non_github_returns_stub(enricher):
    item = _make_item(source_type="email", raw_text="raw email body")
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result["calls_made"] == 0
    assert result["context"] == {}


@pytest.mark.asyncio
async def test_enrich_handles_gh_cli_failure(enricher):
    item = _make_item()

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, side_effect=Exception("gh not found")):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    assert result["calls_made"] == 0
    ctx = result["context"]
    # Should still have author from raw_text even if gh view fails
    assert ctx["author"] == "alice"


def test_provider_config():
    config = GitHubEnricher.ProviderConfig()
    assert config is not None
```

- [ ] **Step 1.2: Run to confirm failure**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_github_enricher.py -x -v`
Expected: `ModuleNotFoundError: No module named 'workbench.providers.enrichment.github'`

### Step 2: Implement the GitHub enricher

- [ ] **Step 2.1: Write the implementation**

```python
# src/workbench/providers/enrichment/github.py
from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import urlparse

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GitHubEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        self.config = config

    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget) -> dict:
        if item.raw_item.source_type != "github":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()
        context = {}
        calls_made = 0

        # Extract basic info from the raw_text JSON (always available)
        try:
            raw_data = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            raw_data = {}

        author = raw_data.get("author", {})
        if isinstance(author, dict):
            context["author"] = author.get("login", "unknown")
        elif isinstance(author, str):
            context["author"] = author

        # Determine if this is a PR or issue from the source ID or URL
        source_id = item.raw_item.id
        url = raw_data.get("url", "")
        is_pr = "/pull/" in url or "gh-pr-" in source_id

        # Parse repo and number from URL
        repo, number = self._parse_url(url)
        if not repo or not number:
            repo, number = self._parse_source_id(source_id)

        if repo and number:
            try:
                if is_pr:
                    details = await self._gh_json(
                        "pr", "view", str(number), "--repo", repo,
                        "--json", "files,reviewDecision,labels,statusCheckRollup",
                    )
                    calls_made = 1
                    files = details.get("files", [])
                    context["files_changed"] = len(files)
                    review = details.get("reviewDecision", "")
                    if review:
                        context["review_status"] = review.lower()
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    checks = details.get("statusCheckRollup", [])
                    if checks:
                        conclusions = [c.get("conclusion", "") for c in checks]
                        if all(c == "SUCCESS" for c in conclusions):
                            context["ci"] = "passing"
                        elif any(c == "FAILURE" for c in conclusions):
                            context["ci"] = "failing"
                        else:
                            context["ci"] = "pending"
                else:
                    details = await self._gh_json(
                        "issue", "view", str(number), "--repo", repo,
                        "--json", "labels,assignees,comments",
                    )
                    calls_made = 1
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    assignees = details.get("assignees", [])
                    if assignees:
                        context["assignees"] = ", ".join(a.get("login", "") for a in assignees)
                    comments = details.get("comments", [])
                    context["comment_count"] = len(comments)
            except Exception as e:
                logger.warning("GitHub enrichment failed for %s: %s", source_id, e)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}

    def _parse_url(self, url: str) -> tuple[str | None, str | None]:
        try:
            parts = urlparse(url).path.strip("/").split("/")
            # owner/repo/pull/123 or owner/repo/issues/123
            if len(parts) >= 4 and parts[2] in ("pull", "issues"):
                return f"{parts[0]}/{parts[1]}", parts[3]
        except Exception:
            pass
        return None, None

    def _parse_source_id(self, source_id: str) -> tuple[str | None, str | None]:
        # gh-pr-owner/repo-123 or gh-issue-owner/repo-123
        for prefix in ("gh-pr-", "gh-issue-"):
            if source_id.startswith(prefix):
                rest = source_id[len(prefix):]
                # Last segment after the last dash is the number
                last_dash = rest.rfind("-")
                if last_dash > 0:
                    return rest[:last_dash], rest[last_dash + 1:]
        return None, None

    async def _gh_json(self, *args) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"gh command failed: {' '.join(args)}")
        return json.loads(stdout.decode())
```

- [ ] **Step 2.2: Run the tests to confirm they pass**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_github_enricher.py -x -v`
Expected: All 5 tests pass.

- [ ] **Step 2.3: Commit**

```bash
git commit -m "feat: add lightweight GitHub enricher for PR/issue details"
```

---

## Task 6: Start Ingestion Queue Worker in Lifespan

**Files:**
- Modify: `src/workbench/main.py`
- Test: `tests/test_api.py`

### Step 1: Write the test

- [ ] **Step 1.1: Add a test that verifies enqueue works via the API**

```python
# Append to tests/test_api.py

@pytest.mark.asyncio
async def test_process_creates_queue_entry(client, app_with_state):
    """Verify /api/process enqueues to the ingestion queue."""
    r = await client.post(
        "/api/process",
        json={"text": "Review the auth migration PR", "source_type": "manual"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert job_id is not None

    stores = app_with_state.state.stores
    depth = await stores.ingestion_queue.queue_depth()
    assert depth == 1
```

- [ ] **Step 1.2: Run to verify**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_api.py::test_process_creates_queue_entry -x -v`
Expected: PASS.

### Step 2: Wire up the worker and sources in the lifespan

- [ ] **Step 2.1: Update `main.py`**

In `src/workbench/main.py`, the full updated lifespan function:

After the `PipelineEngine` creation (after line 69), add the worker:

```python
    from workbench.pipeline.worker import IngestionQueueWorker
    worker = IngestionQueueWorker(
        app.state.stores, app.state.pipeline,
        concurrency=config.queue.worker_concurrency,
    )
    worker.start()
    app.state.worker = worker
```

Update the scheduler creation to pass sources:

```python
    from workbench.pipeline.scheduler import WorkbenchScheduler
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline,
        app.state.messenger, config, sources=app.state.sources,
    )
    app.state.scheduler.start()
```

Update the shutdown section (after `yield`):

```python
    logger.info("Shutting down...")

    if hasattr(app.state, 'worker'):
        app.state.worker.stop()
    app.state.scheduler.scheduler.shutdown(wait=False)
```

- [ ] **Step 2.2: Run the full test suite**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -x -v`
Expected: All tests pass.

- [ ] **Step 2.3: Commit**

```bash
git commit -m "feat: start ingestion queue worker in lifespan, pass sources to scheduler"
```

---

## Task 7: Config and Dependency Updates

**Files:**
- Modify: `config.example.yml`
- Modify: `pyproject.toml`

### Step 1: Update files

- [ ] **Step 1.1: Update `config.example.yml`**

Replace the `triage:` section:

```yaml
triage:
  daily_cap: 20
  expiry_days: 7
  timeout_minutes: 30
  triage_poll_interval_seconds: 10
```

Replace the `messenger:` section:

```yaml
# Messenger — Google Chat (production) or Console (local dev)
messenger:
  class: workbench.providers.messenger.console.ConsoleMessenger
# Google Chat:
# messenger:
#   class: workbench.providers.messenger.google_chat.GoogleChatMessenger
#   space_id: ${oc.env:GOOGLE_CHAT_SPACE_ID}
#   service_account_key_path: ${oc.env:GOOGLE_CHAT_SA_KEY_PATH,/app/credentials/chat-sa.json}
```

Replace the `enrichment:` section:

```yaml
# Enrichment — GitHub (production) or Stub (no enrichment)
enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher
# GitHub enrichment:
# enrichment:
#   class: workbench.providers.enrichment.github.GitHubEnricher
```

- [ ] **Step 1.2: Add `google-auth` to dependencies in `pyproject.toml`**

Add `"google-auth>=2.0"` to the `dependencies` list.

- [ ] **Step 1.3: Commit**

```bash
git commit -m "chore: update config example, add google-auth dependency"
```

---

## Task 8: End-to-End Smoke Tests

**Files:**
- Test: `tests/test_pipeline.py`

Validates the complete pipeline path: enqueue → worker processes → extraction → filter → triage card created. Uses mocked LLM but real PostgreSQL storage.

### Step 1: Write the end-to-end tests

- [ ] **Step 1.1: Add the e2e tests**

```python
# Append to tests/test_pipeline.py
import asyncio


@pytest.mark.asyncio
async def test_e2e_enqueue_to_triage_card(stores, mock_llm):
    """Full pipeline: enqueue → worker dequeues → extraction → filter → triage card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (50, 50)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue("Review the auth migration PR #456", "diff")
    assert job.status == JobStatus.QUEUED
    assert await stores.ingestion_queue.queue_depth() == 1

    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

    assert await stores.ingestion_queue.queue_depth() == 0

    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].item_id is not None

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    assert items[0].id == pending[0].item_id
    assert items[0].raw_data != {}

    fetched_job = await stores.jobs.get_job(job.id)
    assert fetched_job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_e2e_auto_include(stores, mock_llm):
    """Full pipeline: high relevance → auto-include, no triage card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (90, 95)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue("P0 incident: auth service down", "incident")
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

    assert len(await stores.triage.get_pending()) == 0

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
    assert len(items) == 1
    assert items[0].raw_data != {}


@pytest.mark.asyncio
async def test_e2e_auto_drop(stores, mock_llm):
    """Full pipeline: low relevance → auto-drop, no item or card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (5, 95)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue("CI bot comment: lint passed", "github")
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

    assert len(await stores.triage.get_pending()) == 0
    assert len(await stores.items.get_items(ItemFilters())) == 0
```

- [ ] **Step 1.2: Run the e2e tests**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_pipeline.py -x -v -k "e2e"`
Expected: All 3 e2e tests pass.

- [ ] **Step 1.3: Run the full test suite**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 1.4: Commit**

```bash
git commit -m "test: add end-to-end pipeline smoke tests"
```

---

## Summary of Changes

After all 8 tasks, the Phase 1a loop is complete:

| Task | What it does |
|---|---|
| 1. Google Chat Messenger | Sends triage cards, polls for numeric replies, auto-refreshes tokens |
| 2. Triage Poll Interval | Configurable polling speed (default 10s, 1s for Meta internal) |
| 3. Source Polling | Scheduler polls sources on interval, tracks `last_polled_at` in PG, GitHub adapter filters by `since` |
| 4. Item.raw_data + Card Rendering | Preserves raw source content on items, renders labeled enrichment fields |
| 5. GitHub Enricher | Fetches PR/issue details (files, reviews, labels, CI) via `gh` CLI |
| 6. Worker Startup | Ingestion queue worker runs in FastAPI lifespan |
| 7. Config + Dependencies | Example config, `google-auth` dependency |
| 8. E2E Tests | Full pipeline path validation with real PG |

### Remaining for live validation (not in this plan)
- Configure `config.yml` with real Google Chat credentials and a GitHub source
- Deploy via `make up` and observe the loop running
- Trigger `/api/process` and verify the triage card arrives in Google Chat with enrichment context
- Respond to a card and verify the interaction log is written

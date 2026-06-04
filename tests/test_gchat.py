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
    assert {"type": "person", "id": "gchat:users/alice"} in refs
    assert {"type": "person", "id": "gchat:users/bob"} in refs


@pytest.mark.asyncio
async def test_enricher_extracts_space_entity():
    enricher = GChatEnricher(GChatEnricher.ProviderConfig())
    result = await enricher.enrich(_make_chat_item(), "shallow", EnrichmentBudget())
    refs = result["context"]["entity_refs"]
    assert {"type": "space", "id": "gchat:spaces/S/threads/t1"} in refs


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

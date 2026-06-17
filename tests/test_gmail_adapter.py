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
        "msg-1",
        "Test Subject",
        "alice@meta.com",
    )
    conn.gmail.users.return_value.messages.return_value.list.return_value = (
        messages_list
    )
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
    # Source link: deep link to the message in Gmail.
    assert items[0].source_url == "https://mail.google.com/mail/u/0/#all/msg-1"


def test_adapter_type():
    config = GmailAdapter.ProviderConfig()
    adapter = GmailAdapter(config)
    assert adapter.adapter_type() == "email"


@pytest.mark.asyncio
async def test_poll_with_no_messages():
    conn = _mock_connection()
    messages_list = MagicMock()
    messages_list.execute.return_value = {}
    conn.gmail.users.return_value.messages.return_value.list.return_value = (
        messages_list
    )

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
    msg = _make_gmail_message(
        "msg-2", "Urgent: Review needed", "bob@meta.com", "Please review ASAP"
    )
    messages_get = MagicMock()
    messages_get.execute.return_value = msg
    conn.gmail.users.return_value.messages.return_value.list.return_value = (
        messages_list
    )
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

    body = (
        "New content\n> Quoted line\n> Another quoted\nMore new content\n--\nSignature"
    )
    cleaned = _clean_body(body)
    assert "> Quoted line" not in cleaned
    assert "Signature" not in cleaned
    assert "New content" in cleaned
    assert "More new content" in cleaned

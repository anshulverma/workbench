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
    assert {"type": "person", "id": "email:alice@meta.com"} in refs


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
    assert {"type": "person", "id": "email:alice@meta.com"} in refs
    assert {"type": "person", "id": "email:me@meta.com"} in refs
    assert {"type": "person", "id": "email:bob@meta.com"} in refs
    assert {"type": "person", "id": "email:carol@meta.com"} in refs


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
    assert "entity_refs" in result["context"]

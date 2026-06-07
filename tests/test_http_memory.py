import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.memory.http import HttpMemoryLayer
from workbench.models import (
    EntityKnowledge,
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    Relationship,
    TriageCard,
    TriageOption,
    TriageResponse,
)


@pytest.fixture
def mock_http_client():
    return AsyncMock()


@pytest.fixture
def layer(mock_http_client):
    config = HttpMemoryLayer.ProviderConfig(base_url="http://localhost:8422")
    m = HttpMemoryLayer(config)
    m._client = mock_http_client
    return m


@pytest.mark.asyncio
async def test_record_triage_posts_to_memory_service(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    card = TriageCard(
        card_content={"summary": "Fix auth", "source_type": "github"},
        options=[TriageOption(label="Add todo (P1)", action="add_todo")],
    )
    response = TriageResponse(card_id=card.id, choice=1)

    await layer.record_triage(card, response)

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/triage" in call_args[0][0]


@pytest.mark.asyncio
async def test_record_triage_does_not_raise_on_failure(layer, mock_http_client):
    mock_http_client.post.side_effect = Exception("Connection refused")

    card = TriageCard(
        card_content={"summary": "test", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    response = TriageResponse(card_id=card.id, choice=1)

    # Should not raise — graceful degradation
    await layer.record_triage(card, response)


@pytest.mark.asyncio
async def test_query_preferences_returns_facts(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "facts": [
            {
                "content": "User prefers auth diffs",
                "source": "graphiti",
                "timestamp": "2026-06-01T00:00:00Z",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    facts = await layer.query_preferences("auth diffs")

    assert len(facts) == 1
    assert facts[0].content == "User prefers auth diffs"


@pytest.mark.asyncio
async def test_query_preferences_returns_empty_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    facts = await layer.query_preferences("anything")
    assert facts == []


@pytest.mark.asyncio
async def test_query_preferences_populates_id_and_timestamp(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "facts": [
            {
                "id": "f1",
                "content": "User prefers auth diffs",
                "source": "graphiti",
                "timestamp": "2026-06-01T00:00:00+00:00",
            },
            {"content": "No id or timestamp"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    facts = await layer.query_preferences("auth diffs")

    assert facts[0].id == "f1"
    assert facts[0].timestamp is not None
    assert facts[0].timestamp.year == 2026 and facts[0].timestamp.month == 6
    # Missing id/timestamp degrade to None, not now()
    assert facts[1].id is None
    assert facts[1].timestamp is None


@pytest.mark.asyncio
async def test_list_facts_returns_facts(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "facts": [
            {
                "id": "f1",
                "content": "a",
                "source": "graphiti",
                "timestamp": "2026-06-01T00:00:00+00:00",
            },
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    facts = await layer.list_facts()
    assert len(facts) == 1
    assert facts[0].id == "f1"


@pytest.mark.asyncio
async def test_delete_fact_calls_delete_endpoint(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_http_client.delete.return_value = mock_response

    await layer.delete_fact("f1")

    mock_http_client.delete.assert_awaited_once()
    assert "/facts/f1" in mock_http_client.delete.call_args[0][0]


@pytest.mark.asyncio
async def test_update_fact_calls_patch_endpoint(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_http_client.patch.return_value = mock_response

    await layer.update_fact("f1", "edited")

    mock_http_client.patch.assert_awaited_once()
    call = mock_http_client.patch.call_args
    assert "/facts/f1" in call[0][0]
    assert call[1]["json"] == {"content": "edited"}


@pytest.mark.asyncio
async def test_is_available_returns_true(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    assert await layer.is_available() is True


@pytest.mark.asyncio
async def test_is_available_returns_false_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    assert await layer.is_available() is False


@pytest.mark.asyncio
async def test_close_closes_client(layer, mock_http_client):
    await layer.close()
    mock_http_client.aclose.assert_called_once()


def test_http_memory_layer_provider_config():
    config = HttpMemoryLayer.ProviderConfig(
        base_url="http://localhost:8422",
        timeout_seconds=10,
    )
    assert config.base_url == "http://localhost:8422"
    assert config.timeout_seconds == 10


def test_http_memory_layer_default_config():
    config = HttpMemoryLayer.ProviderConfig()
    assert config.base_url == "http://localhost:8422"
    assert config.timeout_seconds == 5


def test_registry_can_create_http_memory_layer():
    from workbench.registry import create_provider

    layer = create_provider(
        {
            "class": "workbench.memory.http.HttpMemoryLayer",
            "base_url": "http://localhost:8422",
        }
    )
    assert isinstance(layer, HttpMemoryLayer)


# --- record_entity tests ---


@pytest.mark.asyncio
async def test_record_entity_posts_to_memory_service(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    await layer.record_entity("person", "alice", {"role": "eng", "team": "infra"})

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/entity" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload == {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {"role": "eng", "team": "infra"},
    }


@pytest.mark.asyncio
async def test_record_entity_does_not_raise_on_failure(layer, mock_http_client):
    mock_http_client.post.side_effect = Exception("Connection refused")

    # Should not raise — graceful degradation
    await layer.record_entity("person", "alice", {"role": "eng"})


# --- record_pipeline_decision tests ---


@pytest.mark.asyncio
async def test_record_pipeline_decision_posts_to_memory_service(
    layer, mock_http_client
):
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    item = Item(
        source_type="github",
        source_id="PR-100",
        summary="PR #100 rate limiting",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P1,
    )

    await layer.record_pipeline_decision(item, "include", "high priority PR")

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/decision" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload == {
        "item_summary": "PR #100 rate limiting",
        "decision": "include",
        "reason": "high priority PR",
        "source_type": "github",
    }


@pytest.mark.asyncio
async def test_record_pipeline_decision_does_not_raise_on_failure(
    layer, mock_http_client
):
    mock_http_client.post.side_effect = Exception("Connection refused")

    item = Item(
        source_type="github",
        source_id="PR-100",
        summary="PR #100 rate limiting",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P1,
    )

    # Should not raise — graceful degradation
    await layer.record_pipeline_decision(item, "drop", "noise")


# --- query_entity tests ---


@pytest.mark.asyncio
async def test_query_entity_returns_entity_knowledge(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {"role": "eng", "team": "infra"},
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    result = await layer.query_entity("person", "alice")

    assert result is not None
    assert isinstance(result, EntityKnowledge)
    assert result.entity_type == "person"
    assert result.entity_id == "alice"
    assert result.facts == {"role": "eng", "team": "infra"}

    mock_http_client.get.assert_called_once()
    call_args = mock_http_client.get.call_args
    assert "/query/entity" in call_args[0][0]
    assert call_args[1]["params"] == {"entity_type": "person", "entity_id": "alice"}


@pytest.mark.asyncio
async def test_query_entity_returns_none_on_404(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    result = await layer.query_entity("person", "unknown")

    assert result is None


@pytest.mark.asyncio
async def test_query_entity_returns_none_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    result = await layer.query_entity("person", "alice")

    assert result is None


# --- query_relationships tests ---


@pytest.mark.asyncio
async def test_query_relationships_returns_relationships(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "relationships": [
            {
                "from_entity": "person:alice",
                "to_entity": "team:infra",
                "relation": "member_of",
            },
            {
                "from_entity": "person:alice",
                "to_entity": "person:bob",
                "relation": "reports_to",
            },
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    result = await layer.query_relationships("person", "alice")

    assert len(result) == 2
    assert all(isinstance(r, Relationship) for r in result)
    assert result[0].from_entity == "person:alice"
    assert result[0].to_entity == "team:infra"
    assert result[0].relation == "member_of"
    assert result[1].from_entity == "person:alice"
    assert result[1].to_entity == "person:bob"
    assert result[1].relation == "reports_to"

    mock_http_client.get.assert_called_once()
    call_args = mock_http_client.get.call_args
    assert "/query/relationships" in call_args[0][0]
    assert call_args[1]["params"] == {"entity_type": "person", "entity_id": "alice"}


@pytest.mark.asyncio
async def test_query_relationships_returns_empty_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    result = await layer.query_relationships("person", "alice")

    assert result == []

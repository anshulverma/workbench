import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.memory.http import HttpMemoryLayer
from workbench.models import TriageCard, TriageOption, TriageResponse


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
            {"content": "User prefers auth diffs", "source": "graphiti", "timestamp": "2026-06-01T00:00:00Z"}
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
    layer = create_provider({
        "class": "workbench.memory.http.HttpMemoryLayer",
        "base_url": "http://localhost:8422",
    })
    assert isinstance(layer, HttpMemoryLayer)

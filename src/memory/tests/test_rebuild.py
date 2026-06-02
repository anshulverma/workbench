import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from memory.scripts.rebuild import (
    replay_interactions,
    reset_memory_graph,
    get_queue_depth,
    get_interactions,
    main,
    BATCH_SIZE,
    QUEUE_DEPTH_THRESHOLD,
)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "queued", "entry_id": "123"}
    client.post.return_value = mock_response

    depth_response = MagicMock()
    depth_response.status_code = 200
    depth_response.raise_for_status = MagicMock()
    depth_response.json.return_value = {"depth": 0, "dead_letters": 0}
    client.get.return_value = depth_response

    return client


def _make_interaction(id_val, card=None, choice_index=1):
    """Helper to build a valid interaction entry."""
    if card is None:
        card = {
            "id": f"card-{id_val}",
            "card_content": {"summary": f"test item {id_val}", "source_type": "github"},
            "options": [
                {"label": "Add todo (P1)", "action": "add_todo"},
                {"label": "Skip", "action": "skip"},
            ],
            "relevance_score": 50,
        }
    return {
        "id": id_val,
        "triage_card_full": card,
        "choice_index": choice_index,
        "timestamp": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_replay_interactions_posts_valid_entries(mock_client):
    interactions = [_make_interaction(1), _make_interaction(2), _make_interaction(3)]

    replayed = await replay_interactions(interactions, mock_client, "http://memory:8422")

    assert replayed == 3
    assert mock_client.post.call_count == 3
    for call in mock_client.post.call_args_list:
        url = call[0][0]
        assert url == "http://memory:8422/record/triage"
        payload = call[1]["json"]
        assert "card" in payload
        assert "response" in payload
        assert "card_id" in payload["response"]
        assert "choice" in payload["response"]


@pytest.mark.asyncio
async def test_replay_interactions_skips_no_choice_index(mock_client):
    interactions = [
        _make_interaction(1, choice_index=None),
        _make_interaction(2, choice_index=1),
    ]

    replayed = await replay_interactions(interactions, mock_client, "http://memory:8422")

    assert replayed == 1
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_replay_interactions_skips_incomplete_card(mock_client):
    # Card missing "id"
    no_id_card = {"options": [{"label": "Skip"}], "relevance_score": 10}
    # Card missing "options"
    no_options_card = {"id": "c99", "card_content": {"summary": "test"}}

    interactions = [
        _make_interaction(1, card=no_id_card),
        _make_interaction(2, card=no_options_card),
        _make_interaction(3),  # valid
    ]

    replayed = await replay_interactions(interactions, mock_client, "http://memory:8422")

    assert replayed == 1
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_reset_memory_graph_calls_admin_endpoint(mock_client):
    await reset_memory_graph(mock_client, "http://memory:8422")

    mock_client.post.assert_called_once_with("http://memory:8422/admin/reset-graph")
    mock_client.post.return_value.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_get_queue_depth_returns_depth(mock_client):
    mock_client.get.return_value.json.return_value = {"depth": 5, "dead_letters": 1}

    depth = await get_queue_depth(mock_client, "http://memory:8422")

    assert depth == 5
    mock_client.get.assert_called_once_with("http://memory:8422/admin/queue-depth")


@pytest.mark.asyncio
async def test_replay_polls_queue_depth_between_batches(mock_client):
    # Create exactly BATCH_SIZE valid interactions to trigger one poll
    interactions = [_make_interaction(i) for i in range(BATCH_SIZE)]

    replayed = await replay_interactions(interactions, mock_client, "http://memory:8422")

    assert replayed == BATCH_SIZE
    # Should have polled queue depth once after the batch
    mock_client.get.assert_called_once_with("http://memory:8422/admin/queue-depth")


@pytest.mark.asyncio
async def test_replay_waits_when_queue_deep(mock_client):
    """When queue depth exceeds threshold, replay should poll until it drains."""
    interactions = [_make_interaction(i) for i in range(BATCH_SIZE)]

    # First depth check returns over threshold, second returns under
    depth_over = MagicMock()
    depth_over.raise_for_status = MagicMock()
    depth_over.json.return_value = {"depth": QUEUE_DEPTH_THRESHOLD + 5}

    depth_under = MagicMock()
    depth_under.raise_for_status = MagicMock()
    depth_under.json.return_value = {"depth": 2}

    mock_client.get.side_effect = [depth_over, depth_under]

    with patch("memory.scripts.rebuild.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        replayed = await replay_interactions(interactions, mock_client, "http://memory:8422")

    assert replayed == BATCH_SIZE
    assert mock_client.get.call_count == 2
    mock_sleep.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_replay_constructs_correct_payload(mock_client):
    card = {
        "id": "card-42",
        "card_content": {"summary": "PR #42 fixing bug", "source_type": "github"},
        "options": [{"label": "Add todo", "action": "add_todo"}, {"label": "Skip", "action": "skip"}],
        "relevance_score": 75,
    }
    interactions = [_make_interaction(42, card=card, choice_index=2)]

    await replay_interactions(interactions, mock_client, "http://memory:8422")

    call_payload = mock_client.post.call_args[1]["json"]
    assert call_payload["card"] == card
    assert call_payload["response"] == {"card_id": "card-42", "choice": 2}


@pytest.mark.asyncio
async def test_main_with_reset():
    """Test main() calls reset when --reset is passed."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "ok"}
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response

    with patch("memory.scripts.rebuild.httpx.AsyncClient") as MockClient, \
         patch("memory.scripts.rebuild.get_interactions", new_callable=AsyncMock) as mock_get:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = []

        await main("postgres://test:test@localhost/test", "http://memory:8422", reset=True)

        mock_client.post.assert_called_once_with("http://memory:8422/admin/reset-graph")
        mock_get.assert_called_once_with("postgres://test:test@localhost/test")


@pytest.mark.asyncio
async def test_main_without_reset():
    """Test main() skips reset when --reset is not passed."""
    mock_client = AsyncMock()

    with patch("memory.scripts.rebuild.httpx.AsyncClient") as MockClient, \
         patch("memory.scripts.rebuild.get_interactions", new_callable=AsyncMock) as mock_get:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = []

        await main("postgres://test:test@localhost/test", "http://memory:8422", reset=False)

        mock_client.post.assert_not_called()

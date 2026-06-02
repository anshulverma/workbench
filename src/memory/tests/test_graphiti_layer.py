import sys
from unittest.mock import AsyncMock, MagicMock

# Mock graphiti_core modules so imports don't fail
mock_nodes = MagicMock()
mock_edges = MagicMock()


class FakeEntityNode:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeEntityEdge:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


mock_nodes.EntityNode = FakeEntityNode
mock_nodes.EpisodeType.text = "text"
mock_edges.EntityEdge = FakeEntityEdge

sys.modules["graphiti_core"] = MagicMock()
sys.modules["graphiti_core.nodes"] = mock_nodes
sys.modules["graphiti_core.edges"] = mock_edges

import pytest
from memory.graphiti_layer import GraphitiMemoryLayer


@pytest.fixture
def mock_graphiti():
    g = AsyncMock()
    g.add_episode = AsyncMock(return_value=MagicMock(
        nodes=[],
        edges=[MagicMock(fact="User prefers auth diffs", name="prefers")],
    ))
    g.add_triplet = AsyncMock(return_value=MagicMock(nodes=[], edges=[]))
    g.search = AsyncMock(return_value=[
        MagicMock(fact="User always prioritizes auth diffs", name="prefers", valid_at=None),
    ])
    return g


@pytest.fixture
def layer(mock_graphiti):
    return GraphitiMemoryLayer(graphiti=mock_graphiti)


@pytest.mark.asyncio
async def test_record_triage_creates_structured_preference_edge(layer, mock_graphiti):
    card = {
        "id": "c1",
        "card_content": {"summary": "Fix auth flow", "source_type": "github"},
        "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
        "relevance_score": 45,
    }
    response = {"card_id": "c1", "choice": 1}

    await layer.record_triage(card, response)

    mock_graphiti.add_triplet.assert_called_once()
    call_args = mock_graphiti.add_triplet.call_args
    source_node = call_args.args[0] if call_args.args else call_args.kwargs["source_node"]
    edge = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["edge"]
    target_node = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs["target_node"]
    assert source_node.name == "user"
    assert "prefers" in edge.name
    assert "Fix auth flow" in target_node.name


@pytest.mark.asyncio
async def test_record_triage_creates_avoids_edge_on_skip(layer, mock_graphiti):
    card = {
        "id": "c2",
        "card_content": {"summary": "CI bot notification", "source_type": "github"},
        "options": [
            {"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}},
            {"label": "Skip", "action": "skip"},
        ],
        "relevance_score": 20,
    }
    response = {"card_id": "c2", "choice": 2}

    await layer.record_triage(card, response)

    call_args = mock_graphiti.add_triplet.call_args
    edge = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["edge"]
    assert "avoids" in edge.name


@pytest.mark.asyncio
async def test_record_triage_creates_mute_edge(layer, mock_graphiti):
    card = {
        "id": "c3",
        "card_content": {"summary": "Weekly digest", "source_type": "email"},
        "options": [
            {"label": "Skip", "action": "skip"},
            {"label": "Never surface emails like this", "action": "mute_pattern"},
        ],
        "relevance_score": 15,
    }
    response = {"card_id": "c3", "choice": 2}

    await layer.record_triage(card, response)

    call_args = mock_graphiti.add_triplet.call_args
    edge = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["edge"]
    assert "avoids" in edge.name
    assert edge.attributes.get("permanent") is True


@pytest.mark.asyncio
async def test_record_triage_calls_add_episode(layer, mock_graphiti):
    card = {
        "id": "c1",
        "card_content": {"summary": "Fix auth", "source_type": "github"},
        "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
        "relevance_score": 45,
    }
    response = {"card_id": "c1", "choice": 1}

    await layer.record_triage(card, response)

    mock_graphiti.add_episode.assert_called_once()
    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert "Fix auth" in call_kwargs["episode_body"]


@pytest.mark.asyncio
async def test_record_triage_uses_custom_extraction_prompt(layer, mock_graphiti):
    card = {
        "id": "c1",
        "card_content": {"summary": "Fix auth", "source_type": "github"},
        "options": [{"label": "Skip", "action": "skip"}],
        "relevance_score": 20,
    }
    response = {"card_id": "c1", "choice": 1}

    await layer.record_triage(card, response)

    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs.get("custom_extraction_instructions") is not None
    assert "preference" in call_kwargs["custom_extraction_instructions"].lower()


@pytest.mark.asyncio
async def test_query_preferences_returns_facts(layer, mock_graphiti):
    facts = await layer.query_preferences("auth diffs")

    mock_graphiti.search.assert_called_once()
    assert len(facts) == 1
    assert "auth diffs" in facts[0].content


@pytest.mark.asyncio
async def test_query_preferences_empty_when_no_results(layer, mock_graphiti):
    mock_graphiti.search.return_value = []

    facts = await layer.query_preferences("unknown topic")
    assert facts == []


@pytest.mark.asyncio
async def test_record_triage_prefers_edge_has_priority(layer, mock_graphiti):
    card = {
        "id": "c4",
        "card_content": {"summary": "Urgent fix", "source_type": "github"},
        "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
        "relevance_score": 90,
    }
    response = {"card_id": "c4", "choice": 1}

    await layer.record_triage(card, response)

    call_args = mock_graphiti.add_triplet.call_args
    edge = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["edge"]
    assert edge.attributes.get("priority") == "P1"

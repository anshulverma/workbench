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


# --- Entity tests ---

@pytest.fixture
def mock_store():
    s = AsyncMock()
    s.get_entity = AsyncMock(return_value=None)
    s.get_entity_resolved = AsyncMock(return_value=None)
    s.upsert_entity = AsyncMock()
    s.update_graph_uuid = AsyncMock()
    s.resolve_identity = AsyncMock(side_effect=lambda et, eid, facts: eid)
    s.enqueue = AsyncMock(return_value="entry-123")
    return s


@pytest.mark.asyncio
async def test_record_entity_calls_add_triplet_per_fact(layer, mock_graphiti, mock_store):
    facts = {"name": "Alice", "role": "engineer"}
    await layer.record_entity("person", "p1", facts, mock_store)

    assert mock_graphiti.add_triplet.call_count == 2


@pytest.mark.asyncio
async def test_record_entity_upserts_in_pg_store(layer, mock_graphiti, mock_store):
    facts = {"name": "Alice"}
    await layer.record_entity("person", "p1", facts, mock_store)

    mock_store.upsert_entity.assert_called_once_with("person", "p1", facts)


@pytest.mark.asyncio
async def test_record_entity_updates_graph_uuid(layer, mock_graphiti, mock_store):
    facts = {"name": "Alice"}
    await layer.record_entity("person", "p1", facts, mock_store)

    mock_store.update_graph_uuid.assert_called_once()
    call_args = mock_store.update_graph_uuid.call_args
    assert call_args.args[0] == "person"
    assert call_args.args[1] == "p1"
    # graph_uuid should be a string (UUID)
    assert isinstance(call_args.args[2], str)


@pytest.mark.asyncio
async def test_record_entity_does_not_write_pg_on_graph_failure(layer, mock_graphiti, mock_store):
    mock_graphiti.add_triplet.side_effect = Exception("Neo4j down")

    with pytest.raises(Exception, match="Neo4j down"):
        await layer.record_entity("person", "p1", {"name": "Alice"}, mock_store)

    mock_store.upsert_entity.assert_not_called()
    mock_store.update_graph_uuid.assert_not_called()


@pytest.mark.asyncio
async def test_query_entity_returns_from_store(layer, mock_store):
    mock_store.get_entity_resolved.return_value = {
        "entity_type": "person",
        "entity_id": "p1",
        "facts": {"name": "Alice"},
        "graph_uuid": "uuid-123",
    }

    result = await layer.query_entity("person", "p1", mock_store)
    assert result is not None
    assert result["entity_id"] == "p1"
    assert result["facts"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_query_entity_returns_none_when_not_found(layer, mock_store):
    mock_store.get_entity_resolved.return_value = None

    result = await layer.query_entity("person", "p99", mock_store)
    assert result is None


@pytest.mark.asyncio
async def test_record_decision_creates_structured_edge(layer, mock_graphiti, mock_store):
    await layer.record_decision(
        "CI notifications from bot", "auto_drop", "low relevance", "github", mock_store
    )

    mock_graphiti.add_triplet.assert_called_once()
    call_args = mock_graphiti.add_triplet.call_args
    source_node = call_args.args[0]
    edge = call_args.args[1]
    target_node = call_args.args[2]
    assert source_node.name == "pipeline"
    assert edge.name == "dropped"
    assert "CI notifications" in target_node.name


@pytest.mark.asyncio
async def test_record_decision_calls_add_episode(layer, mock_graphiti, mock_store):
    await layer.record_decision(
        "Important PR review", "auto_include", "high relevance", "github", mock_store
    )

    mock_graphiti.add_episode.assert_called_once()
    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert "Important PR review" in call_kwargs["episode_body"]
    assert "auto_include" in call_kwargs["episode_body"]


@pytest.mark.asyncio
async def test_query_relationships_returns_from_cypher(layer, mock_graphiti, mock_store):
    mock_store.get_entity.return_value = {
        "entity_type": "person",
        "entity_id": "p1",
        "facts": {"name": "Alice"},
        "graph_uuid": "uuid-123",
    }
    mock_graphiti.driver.execute_query = AsyncMock(return_value=[
        {"from_entity": "person:p1", "to_entity": "team:eng", "relation": "member_of", "fact": "p1 is member of eng"},
    ])

    result = await layer.query_relationships("person", "p1", mock_store)
    assert len(result) == 1
    assert result[0]["from_entity"] == "person:p1"
    assert result[0]["relation"] == "member_of"


@pytest.mark.asyncio
async def test_query_relationships_returns_empty_without_graph_uuid(layer, mock_store):
    mock_store.get_entity.return_value = {
        "entity_type": "person",
        "entity_id": "p1",
        "facts": {"name": "Alice"},
        "graph_uuid": None,
    }

    result = await layer.query_relationships("person", "p1", mock_store)
    assert result == []

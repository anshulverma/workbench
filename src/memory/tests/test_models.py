import pytest
from memory.models import (
    TriageRecordRequest,
    PreferenceQueryResponse,
    Fact,
    EntityRecordRequest,
    DecisionRecordRequest,
    EntityResponse,
    RelationshipsResponse,
    QueueDepthResponse,
)


def test_triage_record_request():
    req = TriageRecordRequest(
        card={
            "id": "card-1",
            "card_content": {"summary": "Fix auth", "source_type": "github"},
            "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
            "relevance_score": 45,
        },
        response={"card_id": "card-1", "choice": 1},
    )
    assert req.card["id"] == "card-1"
    assert req.response["choice"] == 1


def test_fact_model():
    f = Fact(content="User prefers auth diffs", source="graphiti")
    assert f.content == "User prefers auth diffs"
    assert f.source == "graphiti"
    assert f.timestamp is not None


def test_preference_query_response():
    resp = PreferenceQueryResponse(facts=[
        Fact(content="User prefers P1 diffs", source="graphiti"),
    ])
    assert len(resp.facts) == 1


def test_preference_query_response_empty():
    resp = PreferenceQueryResponse(facts=[])
    assert resp.facts == []


def test_entity_record_request():
    req = EntityRecordRequest(
        entity_type="person",
        entity_id="alice",
        facts={"team": "infra", "role": "tech lead"},
    )
    assert req.entity_type == "person"
    assert req.entity_id == "alice"
    assert req.facts["team"] == "infra"


def test_entity_record_request_empty_facts():
    req = EntityRecordRequest(
        entity_type="repo",
        entity_id="infra-core",
        facts={},
    )
    assert req.facts == {}


def test_decision_record_request():
    req = DecisionRecordRequest(
        item_summary="PR #100 rate limiting",
        decision="auto_include",
        reason="relevance=85",
        source_type="github",
    )
    assert req.item_summary == "PR #100 rate limiting"
    assert req.decision == "auto_include"
    assert req.reason == "relevance=85"
    assert req.source_type == "github"


def test_decision_record_request_default_source_type():
    req = DecisionRecordRequest(
        item_summary="Some item",
        decision="auto_drop",
        reason="relevance=10",
    )
    assert req.source_type == "unknown"


def test_entity_response():
    resp = EntityResponse(
        entity_type="person",
        entity_id="alice",
        facts={"team": "infra", "repos": ["infra-core"]},
    )
    assert resp.entity_type == "person"
    assert resp.entity_id == "alice"
    assert resp.facts["repos"] == ["infra-core"]


def test_relationships_response():
    resp = RelationshipsResponse(
        relationships=[
            {"from_entity": "alice", "to_entity": "infra-core", "relation": "reviews"},
            {"from_entity": "alice", "to_entity": "bob", "relation": "collaborates_with"},
        ]
    )
    assert len(resp.relationships) == 2
    assert resp.relationships[0]["relation"] == "reviews"


def test_relationships_response_empty():
    resp = RelationshipsResponse(relationships=[])
    assert resp.relationships == []


def test_queue_depth_response():
    resp = QueueDepthResponse(depth=5, dead_letters=2)
    assert resp.depth == 5
    assert resp.dead_letters == 2


def test_queue_depth_response_zero():
    resp = QueueDepthResponse(depth=0, dead_letters=0)
    assert resp.depth == 0
    assert resp.dead_letters == 0

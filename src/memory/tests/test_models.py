import pytest
from memory.models import TriageRecordRequest, PreferenceQueryResponse, Fact


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

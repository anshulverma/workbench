from datetime import datetime, timezone

from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall


def test_record_roundtrips_with_subcalls():
    rec = LlmCallRecord(
        started_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        origin="triage",
        purpose="score",
        stage="triage",
        model="claude-opus-4-8",
        temperature=0.2,
        status="ok",
        batch=1,
        items=["D1"],
        tokens_in=10,
        tokens_out=5,
        system_prompt="sys",
        subcalls=[
            LlmSubcall(
                item="D1",
                prompt="p",
                completion="c",
                structured={"x": 1},
                tokens_in=10,
                tokens_out=5,
            )
        ],
    )
    assert rec.stage == "triage"
    assert rec.subcalls[0].structured == {"x": 1}
    assert rec.model_dump()["status"] == "ok"


def test_defaults():
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="extract",
        model="m",
        status="error",
    )
    assert rec.batch == 1 and rec.items == [] and rec.subcalls == []
    assert rec.tokens_estimated is False and rec.is_fallback is False


def test_llm_call_record_carries_raw_io():
    from datetime import datetime, timezone
    from workbench.domain.llm_calls import LlmCallRecord

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
        raw_request={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        raw_response={
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
        },
    )
    assert rec.raw_request["messages"][0]["content"] == "hi"
    assert rec.raw_response["stop_reason"] == "end_turn"
    # Defaults are None when omitted.
    rec2 = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
    )
    assert rec2.raw_request is None and rec2.raw_response is None

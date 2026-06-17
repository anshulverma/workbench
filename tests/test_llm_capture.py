import pytest
from types import SimpleNamespace
from workbench.providers.llm.plugboard import record_plugboard_call
from workbench.providers.llm.context import llm_call_context

pytestmark = pytest.mark.asyncio


async def _aval(v):
    return v


async def _raise():
    raise ValueError("boom")


async def test_captures_context_and_bodies():
    captured = []
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        content=[SimpleNamespace(text="hello")],
    )

    def extractor(r):
        return (
            "hello",
            {"k": 1},
            [
                {
                    "item": "i1",
                    "prompt": "p",
                    "completion": "hello",
                    "structured": {"k": 1},
                    "tokens_in": 10,
                    "tokens_out": 4,
                }
            ],
        )

    with llm_call_context(origin="triage", purpose="score", stage="triage"):
        await record_plugboard_call(
            client="main_llm",
            model="m",
            sink=captured.append,
            item_count=1,
            system_prompt="sys",
            input_prompt="p",
            temperature=0.2,
            result_extractor=extractor,
            do_call=lambda: _aval(resp),
        )
    rec = captured[0]
    assert rec.context.stage == "triage" and rec.system_prompt == "sys"
    assert rec.input_prompt == "p"
    assert (
        rec.completion == "hello"
        and rec.structured == {"k": 1}
        and rec.subcalls[0]["item"] == "i1"
    )
    assert rec.input_tokens == 10 and rec.temperature == 0.2


async def test_error_path_still_records_and_reraises():
    captured = []
    with pytest.raises(ValueError):
        await record_plugboard_call(
            client="c", model="m", sink=captured.append, do_call=_raise
        )
    assert captured[0].error_type == "ValueError"


async def test_backward_compatible_minimal_call():
    captured = []
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=5,
            output_tokens=2,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
    )
    await record_plugboard_call(
        client="c", model="m", sink=captured.append, do_call=lambda: _aval(resp)
    )
    rec = captured[0]
    assert rec.input_tokens == 5 and rec.completion is None and rec.subcalls is None


async def test_faulty_extractor_does_not_break_call():
    captured = []
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        content=[SimpleNamespace(text="hello")],
    )

    def faulty_extractor(r):
        raise RuntimeError("extractor failed")

    result = await record_plugboard_call(
        client="c",
        model="m",
        sink=captured.append,
        system_prompt="s",
        input_prompt="p",
        result_extractor=faulty_extractor,
        do_call=lambda: _aval(resp),
    )
    assert result is resp
    rec = captured[0]
    assert rec.completion is None and rec.structured is None and rec.subcalls is None
    assert rec.input_tokens == 10 and rec.output_tokens == 4


async def test_sink_none_passthrough_with_new_params():
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        content=[SimpleNamespace(text="hello")],
    )

    def ok_extractor(r):
        return "hello", {"k": 1}, []

    result = await record_plugboard_call(
        client="c",
        model="m",
        sink=None,
        system_prompt="s",
        input_prompt="p",
        result_extractor=ok_extractor,
        do_call=lambda: _aval(resp),
    )
    assert result is resp

    with pytest.raises(ValueError, match="boom"):
        await record_plugboard_call(client="c", model="m", sink=None, do_call=_raise)

import pytest
from types import SimpleNamespace

from workbench.providers.llm.plugboard import PlugboardCallRecord, record_plugboard_call


@pytest.mark.asyncio
async def test_shim_records_success_with_tokens():
    seen = []
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    resp = SimpleNamespace(usage=usage, content=[SimpleNamespace(text="ok")])

    async def call():
        return resp

    out = await record_plugboard_call(
        client="main_llm", model="m", item_count=3, sink=seen.append, do_call=call
    )
    assert out is resp
    rec = seen[0]
    assert isinstance(rec, PlugboardCallRecord)
    assert rec.client == "main_llm" and rec.model == "m"
    assert rec.input_tokens == 10 and rec.output_tokens == 5
    assert rec.item_count == 3 and rec.error_type is None


@pytest.mark.asyncio
async def test_shim_records_error_then_reraises():
    seen = []

    async def call():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await record_plugboard_call(
            client="queue_scorer", model="h", sink=seen.append, do_call=call
        )
    assert seen[0].error_type == "ValueError" and seen[0].input_tokens == 0


@pytest.mark.asyncio
async def test_shim_noop_when_sink_none():
    resp = SimpleNamespace(usage=None, content=[])

    async def call():
        return resp

    out = await record_plugboard_call(
        client="main_llm", model="m", sink=None, do_call=call
    )
    assert out is resp


@pytest.mark.asyncio
async def test_shim_captures_raw_request_and_serialized_response():
    seen = []

    class FakeResp:
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        content = [SimpleNamespace(text="ok")]

        def model_dump(self, mode="python"):
            return {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "ok"}],
            }

    req = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    async def call():
        return FakeResp()

    await record_plugboard_call(
        client="main_llm", model="m", sink=seen.append, do_call=call, raw_request=req
    )
    rec = seen[0]
    assert rec.raw_request == req
    assert rec.raw_response == {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
    }


@pytest.mark.asyncio
async def test_shim_raw_response_none_when_unserializable():
    seen = []
    # No model_dump and not a pydantic model -> serializer returns None, no raise.
    resp = SimpleNamespace(usage=None, content=[])

    async def call():
        return resp

    await record_plugboard_call(
        client="main_llm", model="m", sink=seen.append, do_call=call
    )
    assert seen[0].raw_response is None


@pytest.mark.asyncio
async def test_shim_records_raw_request_on_error_path():
    seen = []
    req = {"model": "m", "messages": [{"role": "user", "content": "boom"}]}

    async def call():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await record_plugboard_call(
            client="main_llm",
            model="m",
            sink=seen.append,
            do_call=call,
            raw_request=req,
        )
    assert seen[0].raw_request == req and seen[0].raw_response is None


@pytest.mark.asyncio
async def test_shim_raw_response_none_when_model_dump_raises():
    seen = []

    class FakeResp:
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        content = [SimpleNamespace(text="ok")]

        def model_dump(self, mode="python"):
            raise RuntimeError("cannot serialize")

    async def call():
        return FakeResp()

    out = await record_plugboard_call(
        client="main_llm", model="m", sink=seen.append, do_call=call
    )
    # The call still succeeds and returns the response...
    assert isinstance(out, FakeResp)
    # ...and raw_response degraded to None instead of raising.
    assert seen[0].raw_response is None

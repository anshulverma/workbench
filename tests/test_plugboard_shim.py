import pytest
from types import SimpleNamespace

from workbench.providers._plugboard import PlugboardCallRecord, record_plugboard_call


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

from workbench.telemetry.usage_aggregator import UsageAggregator
from workbench.providers._plugboard import PlugboardCallRecord


def test_aggregate_and_drain():
    agg = UsageAggregator()
    agg.record(
        PlugboardCallRecord(
            client="main_llm", model="m", input_tokens=10, output_tokens=2
        )
    )
    agg.record(
        PlugboardCallRecord(
            client="main_llm", model="m", input_tokens=5, error_type="X"
        )
    )
    snap = agg.drain()
    assert snap[("main_llm", "m")]["calls"] == 2
    assert snap[("main_llm", "m")]["errors"] == 1
    assert snap[("main_llm", "m")]["input_tokens"] == 15
    assert snap[("main_llm", "m")]["output_tokens"] == 2
    # drain resets
    assert agg.drain() == {}


def test_drain_empty_returns_empty():
    assert UsageAggregator().drain() == {}

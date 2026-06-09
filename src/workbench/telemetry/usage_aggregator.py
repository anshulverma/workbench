"""In-process per-interval aggregation of plugboard usage.

Fed by the same sink that updates Prometheus (so it sees tokens/model/client),
the aggregator accumulates calls/errors/tokens keyed by (client, model). A
periodic task drains it and emits one ``llm_usage_summary`` structlog line per
interval. Prometheus counters stay cumulative; the log shows per-interval
deltas. See spec 3.6-3.7.
"""

from __future__ import annotations

from workbench.providers._plugboard import PlugboardCallRecord


class UsageAggregator:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], dict[str, int]] = {}

    def record(self, rec: PlugboardCallRecord) -> None:
        key = (rec.client, rec.model)
        bucket = self._data.get(key)
        if bucket is None:
            bucket = {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0}
            self._data[key] = bucket
        bucket["calls"] += 1
        if rec.error_type:
            bucket["errors"] += 1
        bucket["input_tokens"] += rec.input_tokens
        bucket["output_tokens"] += rec.output_tokens

    def drain(self) -> dict[tuple[str, str], dict[str, int]]:
        """Return accumulated counts since the last drain and reset."""
        snapshot = self._data
        self._data = {}
        return snapshot

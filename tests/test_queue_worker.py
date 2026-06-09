"""Graceful-shutdown behavior for the ingestion queue worker.

When PostgreSQL goes away (most commonly because it is a separate container
shutting down at the same time as Workbench), the poll loop must treat the
connection failure as a benign, recoverable condition -- a one-line warning
with no traceback -- and `stop()` must be awaitable so the lifespan can wait for
the loop to unwind before closing the DB pool.
"""

import asyncio
import io
import json
import logging

import pytest

from workbench.telemetry.logging import setup_logging
from workbench.pipeline.worker import IngestionQueueWorker


def _attach_capture():
    """Attach a StringIO handler reusing setup_logging's JSON formatter.
    Returns (lines_callable, detach_callable). Call AFTER setup_logging."""
    buf = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)

    def _lines():
        return [ln for ln in buf.getvalue().splitlines() if ln.strip()]

    return _lines, lambda: root.removeHandler(handler)


class _FakeQueue:
    def __init__(self, exc):
        self._exc = exc

    async def recover_stuck(self):
        return 0

    async def dequeue(self, limit=1):
        raise self._exc


class _FakeStores:
    def __init__(self, exc):
        self.ingestion_queue = _FakeQueue(exc)


def test_worker_module_placeholder():
    """Worker tests require running PG and pipeline — tested in E2E."""
    assert True


@pytest.mark.asyncio
async def test_connection_refused_logs_warning_not_error_traceback():
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    worker = IngestionQueueWorker(
        _FakeStores(ConnectionRefusedError(111, "Connection refused")),
        pipeline=None,
        concurrency=1,
    )
    try:
        worker.start()
        await asyncio.sleep(0.05)  # let one dequeue raise and log
        await worker.stop()
    finally:
        detach()

    recs = [json.loads(ln) for ln in lines()]
    warns = [
        r
        for r in recs
        if r.get("level") == "warning" and "database unavailable" in r.get("event", "")
    ]
    assert warns, f"expected a 'database unavailable' warning, got: {recs}"
    assert "exception" not in warns[0], "benign warning must not carry a traceback"
    # No error-level noise for an expected connection failure.
    assert not [r for r in recs if r.get("level") == "error"], recs


@pytest.mark.asyncio
async def test_stop_is_awaitable_and_idempotent():
    worker = IngestionQueueWorker(
        _FakeStores(ConnectionRefusedError(111, "Connection refused")),
        pipeline=None,
        concurrency=1,
    )
    worker.start()
    await asyncio.sleep(0.01)
    await worker.stop()
    assert worker._task is None
    # Calling stop() again after the loop is gone must not raise.
    await worker.stop()

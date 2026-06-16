# tests/test_request_logging.py
"""The request-outcome log line is the safety net for HTTP failures. For a
warning (4xx) or error (5xx) it must say *what* went wrong — the response body
(FastAPI's `{"detail": ...}` / validation errors), the query string, and the
client — not merely that a request "completed" with some status code."""

import io
import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from workbench.runtime.middleware import CorrelationIdMiddleware
from workbench.telemetry.logging import setup_logging


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


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=400, detail="thing was invalid")

    @app.get("/crash")
    async def crash():
        raise RuntimeError("kaboom")

    @app.get("/ok")
    async def ok():
        return {"status": "fine"}

    return app


def _completion_line(lines):
    recs = [json.loads(ln) for ln in lines]
    return next(r for r in recs if r.get("event") == "request completed")


def test_4xx_surfaces_response_body_and_query():
    """A 4xx 'request completed' warning carries the response body (the error
    detail) and the query string, so the log says why the request failed."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        resp = client.get("/boom?widget=42")
        assert resp.status_code == 400
        # The original error body is preserved for the caller, not swallowed.
        assert resp.json() == {"detail": "thing was invalid"}
    finally:
        detach()

    rec = _completion_line(lines())
    assert rec["level"] == "warning"
    assert rec["status_code"] == 400
    assert "thing was invalid" in rec["error_detail"]
    assert rec["query"] == "widget=42"


def test_5xx_unhandled_surfaces_exception():
    """An unhandled exception logs at error level with a full traceback."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        resp = client.get("/crash")
        assert resp.status_code == 500
    finally:
        detach()

    recs = [json.loads(ln) for ln in lines()]
    failed = next(r for r in recs if r.get("event") == "request failed")
    assert failed["level"] == "error"
    assert "RuntimeError" in failed["exception"]
    assert "kaboom" in failed["exception"]


def test_2xx_stays_quiet_and_unbuffered():
    """A success response is logged at info level with no error_detail, and its
    body is passed through untouched (not drained/rebuilt)."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        resp = client.get("/ok")
        assert resp.status_code == 200
        assert resp.json() == {"status": "fine"}
    finally:
        detach()

    rec = _completion_line(lines())
    assert rec["level"] == "info"
    assert rec["status_code"] == 200
    assert "error_detail" not in rec

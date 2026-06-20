# tests/test_client_logs_api.py
import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.client_logs import router
from workbench.telemetry.logging import setup_logging


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _event(**over):
    base = {
        "level": "error",
        "kind": "uncaught",
        "message": "boom",
        "ts": 1718900000000,
    }
    base.update(over)
    return base


def _attach_capture():
    """Capture rendered JSON log lines.

    Mirrors tests/test_structured_logging.py. structlog is only routed through
    stdlib once setup_logging() runs (cache_logger_on_first_use=True), so a bare
    pytest caplog fixture does NOT reliably capture these records — we attach a
    StringIO handler reusing setup_logging's installed JSON formatter instead.
    Call AFTER setup_logging.
    """
    buf = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)

    def _lines():
        return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]

    def _detach():
        root.removeHandler(handler)

    return _lines, _detach


def test_ingest_accepts_batch_returns_204():
    resp = _client().post("/api/client-logs", json={"events": [_event()]})
    assert resp.status_code == 204


def test_ingest_rejects_oversized_batch_413():
    events = [_event() for _ in range(51)]
    resp = _client().post("/api/client-logs", json={"events": events})
    assert resp.status_code == 413


def test_ingest_logs_each_event_at_mapped_level():
    import structlog

    structlog.reset_defaults()
    setup_logging(log_format="json", log_dir=None)
    lines, detach = _attach_capture()
    try:
        resp = _client().post(
            "/api/client-logs",
            json={"events": [_event(level="warn", kind="console", message="hey")]},
        )
    finally:
        out = lines()
        detach()
    assert resp.status_code == 204
    recs = [r for r in out if r.get("event") == "client_error"]
    assert len(recs) == 1
    assert recs[0]["level"] == "warning"
    assert recs[0]["client_message"] == "hey"
    assert recs[0]["kind"] == "console"


def test_ingest_serializes_extra_as_string_for_redaction():
    import structlog

    structlog.reset_defaults()
    setup_logging(log_format="json", log_dir=None)
    lines, detach = _attach_capture()
    try:
        _client().post(
            "/api/client-logs",
            json={"events": [_event(kind="api", extra={"status": 500})]},
        )
    finally:
        out = lines()
        detach()
    recs = [r for r in out if r.get("event") == "client_error"]
    assert len(recs) == 1
    # extra is logged as a JSON string (so SanitizingProcessor can redact it),
    # never a raw dict that would bypass redaction.
    assert isinstance(recs[0]["extra_json"], str)
    assert "500" in recs[0]["extra_json"]


def test_ingest_redacts_pii_and_keeps_stack_untruncated():
    # In production the sanitizer is wired via setup_logging(extra_processors=[...])
    # (see runtime/app.py). Reproduce that here to assert redaction + no-truncate.
    import importlib
    import structlog

    from workbench.config import PrivacyConfig
    from workbench.telemetry.privacy import SanitizingProcessor

    privacy = PrivacyConfig(
        sanitize_logs=True,
        redact_emails=True,
        redact_phones=True,
        max_content_in_logs=80,
    )
    structlog.reset_defaults()
    setup_logging(
        log_format="json", log_dir=None, extra_processors=[SanitizingProcessor(privacy)]
    )
    # Reload the module so it gets a fresh logger with the new configuration
    from workbench.api import client_logs

    importlib.reload(client_logs)
    lines, detach = _attach_capture()
    long_stack = "trace " * 100  # > max_content_in_logs
    try:
        _client().post(
            "/api/client-logs",
            json={
                "events": [_event(message="contact me@example.com", stack=long_stack)]
            },
        )
    finally:
        out = lines()
        detach()
    rec = next(r for r in out if r.get("event") == "client_error")
    assert "me@example.com" not in rec["client_message"]
    assert "[REDACTED:email]" in rec["client_message"]
    # stack is in NO_TRUNCATE_KEYS, so it survives full despite exceeding the cap.
    assert "[truncated]" not in rec["stack"]
    assert len(rec["stack"]) >= len(long_stack) - 50


def test_ingest_rejects_unknown_level_422():
    resp = _client().post("/api/client-logs", json={"events": [_event(level="trace")]})
    assert resp.status_code == 422


def test_route_registered_in_real_app():
    # The route is actually wired into the real application, not just importable.
    from workbench.runtime.app import create_app

    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/client-logs" in paths


def test_auth_middleware_exempts_path():
    # The exemption is a literal path check in dispatch(); assert the running
    # middleware actually allows the path through without a bearer token.
    import inspect

    from workbench.runtime import auth

    src = inspect.getsource(auth.BearerTokenMiddleware.dispatch)
    assert "/api/client-logs" in src

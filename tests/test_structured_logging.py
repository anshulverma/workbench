# tests/test_structured_logging.py

import io
import json
import logging
import uuid

import pytest
import structlog

from workbench.logging import setup_logging
from workbench.middleware import CorrelationIdMiddleware


def _attach_capture():
    """Attach a StringIO StreamHandler over the root logger's JSON formatter and
    return (lines_callable, detach_callable). Must be called AFTER setup_logging,
    since setup_logging clears the root logger's handlers."""
    buf = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(buf)
    # Reuse the formatter setup_logging installed so we capture JSON lines.
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)

    def _lines():
        return [ln for ln in buf.getvalue().splitlines() if ln.strip()]

    def _detach():
        root.removeHandler(handler)

    return _lines, _detach


def test_json_output_format(tmp_path, capsys):
    """JSON format produces parseable JSON lines."""
    setup_logging(log_format="json", log_dir=None)
    logger = structlog.get_logger("test")
    logger.info("test_event", key="value", count=42)
    captured = capsys.readouterr()
    line = json.loads(captured.err.strip())
    assert line["event"] == "test_event"
    assert line["key"] == "value"
    assert line["count"] == 42


def test_console_output_format(capsys):
    """Console format produces human-readable output."""
    setup_logging(log_format="console", log_dir=None)
    logger = structlog.get_logger("test")
    logger.info("test_event", key="value")
    captured = capsys.readouterr()
    assert "test_event" in captured.err
    assert "key=" in captured.err or "key" in captured.err


def test_stdlib_logger_gets_structlog_processing(capsys):
    """Existing logging.getLogger() (stdlib/foreign) records go through the FULL
    pipeline via foreign_pre_chain — level/logger/file:line/timestamp, not just event."""
    setup_logging(log_format="json", log_dir=None)
    logger = logging.getLogger("legacy.module")
    logger.warning("legacy message %s", "arg1")
    captured = capsys.readouterr()
    line = json.loads(captured.err.strip())
    assert "legacy message arg1" in line.get("event", "")
    # The bug this guards: foreign records used to emit bare {"event": ...}.
    assert line["level"] == "warning"
    assert line["logger"] == "legacy.module"
    assert line["filename"] == "test_structured_logging.py"
    assert isinstance(line["lineno"], int) and line["lineno"] > 0
    assert line["timestamp"].endswith("Z") or line["timestamp"].endswith("+00:00")


def test_file_handler_preserved(tmp_path):
    """AgeRotatingFileHandler still writes logs to files."""
    log_dir = str(tmp_path / "logs")
    setup_logging(log_format="json", log_dir=log_dir)
    logger = structlog.get_logger("test")
    logger.info("file_test")
    import os
    assert os.path.exists(log_dir)
    log_files = os.listdir(log_dir)
    assert len(log_files) >= 1


@pytest.mark.asyncio
async def test_correlation_id_middleware():
    """Middleware adds X-Request-ID to response and binds to context."""
    from starlette.testclient import TestClient
    from fastapi import FastAPI, Request

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/test")
    async def handler(request: Request):
        return {"request_id": request.state.request_id}

    client = TestClient(app)
    resp = client.get("/test")
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-ID")
    assert request_id is not None
    uuid.UUID(request_id)  # valid UUID
    assert resp.json()["request_id"] == request_id


def test_callsite_fields_present_in_json():
    """JSON lines include real filename/lineno, never 'unknown'."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = structlog.get_logger("workbench.test")
        log.info("hello world", count=3)
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert rec["filename"] == "test_structured_logging.py"
    assert isinstance(rec["lineno"], int) and rec["lineno"] > 0
    assert rec["func_name"] == "test_callsite_fields_present_in_json"
    assert rec["event"] == "hello world"
    assert rec["count"] == 3
    assert rec["level"] == "info"
    # UTC 'Z' on disk (utc=True)
    assert rec["timestamp"].endswith("Z") or rec["timestamp"].endswith("+00:00")


def test_unknown_format_falls_back_to_json():
    """An unknown log_format (e.g. legacy 'glog') renders JSON, not an error."""
    setup_logging(log_format="glog")
    lines, detach = _attach_capture()
    try:
        structlog.get_logger("workbench.test").info("fallback", n=1)
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert rec["event"] == "fallback"
    assert rec["n"] == 1


def test_json_is_default_format():
    from workbench.config import LoggingConfig
    assert LoggingConfig().format == "json"


def test_sanitizer_excludes_callsite_fields():
    from workbench.config import PrivacyConfig
    from workbench.privacy import SanitizingProcessor

    config = PrivacyConfig(max_content_in_logs=5, redact_emails=True, redact_phones=True)
    p = SanitizingProcessor(config)
    out = p(
        None,
        "info",
        {
            "event": "e",
            "filename": "a_very_long_filename.py",
            "lineno": 4242,
            "func_name": "some_long_function_name",
        },
    )
    assert out["filename"] == "a_very_long_filename.py"  # not truncated
    assert out["lineno"] == 4242
    assert out["func_name"] == "some_long_function_name"

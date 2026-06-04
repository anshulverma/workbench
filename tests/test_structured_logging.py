# tests/test_structured_logging.py

import json
import logging
import uuid

import pytest
import structlog

from workbench.logging import setup_logging
from workbench.middleware import CorrelationIdMiddleware


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
    """Existing logging.getLogger() calls go through structlog pipeline."""
    setup_logging(log_format="json", log_dir=None)
    logger = logging.getLogger("legacy.module")
    logger.info("legacy message %s", "arg1")
    captured = capsys.readouterr()
    line = json.loads(captured.err.strip())
    assert "legacy message arg1" in line.get("event", "")


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

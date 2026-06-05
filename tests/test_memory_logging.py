import io
import json
import logging
import pathlib
import sys

import structlog

# `import memory` resolves to a namespace stub in this venv (__file__ is None),
# so point at the real package source before importing memory.logging.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "src" / "memory")
)

from memory.logging import _json_formatter, setup_logging

REQUIRED_KEYS = {
    "timestamp",
    "level",
    "logger",
    "filename",
    "lineno",
    "func_name",
    "event",
}


def test_memory_logging_module_resolves_to_src():
    import memory.logging as mem_logging

    assert mem_logging.__file__ is not None
    assert mem_logging.__file__.endswith("src/memory/memory/logging.py")


def test_memory_emits_shared_json_schema():
    buf = io.StringIO()
    setup_logging()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_json_formatter())
    root.addHandler(handler)
    # structlog logger so structured kwargs flow through the processor chain.
    structlog.get_logger("memory.test").info("ping", attempt=1)
    rec = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert REQUIRED_KEYS <= set(rec)
    assert rec["filename"] == "test_memory_logging.py"
    assert rec["event"] == "ping"
    assert rec["logger"] == "memory.test"
    assert rec["level"] == "info"
    assert isinstance(rec["lineno"], int) and rec["lineno"] > 0
    assert rec["func_name"] == "test_memory_emits_shared_json_schema"
    assert rec["attempt"] == 1
    assert rec["timestamp"].endswith("Z") or rec["timestamp"].endswith("+00:00")


def test_memory_log_dir_writes_rotating_json_file(tmp_path):
    """setup_logging(log_dir=...) creates <log_dir>/memory.log and writes
    structured JSON records there with the shared schema."""
    setup_logging(log_dir=str(tmp_path))
    log_file = tmp_path / "memory.log"
    assert log_file.exists()

    structlog.get_logger("memory.file").info("to-file", attempt=7)

    for handler in logging.getLogger().handlers:
        handler.flush()

    line = log_file.read_text().strip().splitlines()[-1]
    rec = json.loads(line)
    assert REQUIRED_KEYS <= set(rec)
    assert rec["event"] == "to-file"
    assert rec["logger"] == "memory.file"
    assert rec["level"] == "info"
    assert rec["filename"] == "test_memory_logging.py"
    assert isinstance(rec["lineno"], int) and rec["lineno"] > 0
    assert rec["timestamp"].endswith("Z") or rec["timestamp"].endswith("+00:00")


def test_memory_stdlib_record_gets_full_schema():
    """Foreign (stdlib) records — uvicorn, logging.getLogger — get the full schema
    via foreign_pre_chain, not a bare {"event": ...}."""
    buf = io.StringIO()
    setup_logging()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_json_formatter())
    root.addHandler(handler)
    logging.getLogger("memory.legacy").warning("stdlib %s", "msg")
    rec = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert REQUIRED_KEYS <= set(rec)
    assert "stdlib msg" in rec["event"]
    assert rec["level"] == "warning"
    assert rec["logger"] == "memory.legacy"
    assert rec["filename"] == "test_memory_logging.py"

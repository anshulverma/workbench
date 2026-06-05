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

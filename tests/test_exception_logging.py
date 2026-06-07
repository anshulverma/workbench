# tests/test_exception_logging.py
"""Exceptions caught and logged must always render a full traceback, even when
the call site forgets exc_info=True. Guards against silently-hidden exceptions."""

import io
import json
import logging

import structlog

from workbench.logging import setup_logging


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


def test_structlog_error_in_except_renders_traceback():
    """A structlog .error() inside an except block, WITHOUT exc_info=True, still
    emits the full traceback (exception type + message + stack frame)."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = structlog.get_logger("workbench.test")
        try:
            raise ValueError("boom-structlog")
        except Exception as e:  # noqa: BLE001 — exactly the swallow-pattern we fix
            log.error(f"something failed: {e}")
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert "exception" in rec, "no traceback was attached"
    assert "ValueError" in rec["exception"]
    assert "boom-structlog" in rec["exception"]
    assert "Traceback" in rec["exception"]


def test_stdlib_error_in_except_renders_traceback():
    """A stdlib logging.getLogger().error() inside an except block (the dominant
    pattern across the codebase), WITHOUT exc_info=True, still emits the traceback."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = logging.getLogger("workbench.legacy")
        try:
            raise RuntimeError("boom-stdlib")
        except Exception as e:  # noqa: BLE001
            log.error("worker error: %s", e)
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert "exception" in rec, "no traceback was attached to foreign/stdlib record"
    assert "RuntimeError" in rec["exception"]
    assert "boom-stdlib" in rec["exception"]


def test_no_active_exception_means_no_traceback():
    """Outside an except block, ordinary logs must NOT grow a spurious traceback."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        structlog.get_logger("workbench.test").error("plain error, no exception")
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert "exception" not in rec


def test_explicit_exc_info_still_works():
    """An explicit exc_info=True is honored and not double-rendered."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = structlog.get_logger("workbench.test")
        try:
            raise KeyError("explicit")
        except Exception:
            log.error("explicit path", exc_info=True)
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert rec["exception"].count("Traceback") == 1
    assert "KeyError" in rec["exception"]


def test_warning_in_except_has_no_traceback():
    """A warning logged inside an except block (e.g. apscheduler's benign
    "maximum number of running instances reached" MaxInstancesReachedError) is a
    handled, expected condition — it must NOT get a spurious auto-traceback."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = logging.getLogger("apscheduler.scheduler")
        try:
            raise RuntimeError("MaxInstancesReachedError")
        except Exception:  # noqa: BLE001
            log.warning(
                "Execution of job skipped: maximum number of running instances reached (1)"
            )
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert "exception" not in rec, "benign warning should not carry a traceback"


def test_warning_with_explicit_exc_info_keeps_traceback():
    """A warning that genuinely wants a traceback can still opt in with
    exc_info=True — the auto-attach gate only affects the implicit safety net."""
    setup_logging(log_format="json")
    lines, detach = _attach_capture()
    try:
        log = logging.getLogger("workbench.test")
        try:
            raise ValueError("warn-boom")
        except Exception:  # noqa: BLE001
            log.warning("degraded but recoverable", exc_info=True)
    finally:
        detach()
    rec = json.loads(lines()[-1])
    assert "exception" in rec
    assert "ValueError" in rec["exception"]
    assert "warn-boom" in rec["exception"]

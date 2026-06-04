from __future__ import annotations

import datetime
import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog


class AgeRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that also removes old backup files beyond max_age_days."""

    def __init__(self, filename, max_age_days=84, **kwargs):
        self.max_age_days = max_age_days
        super().__init__(filename, **kwargs)

    def doRollover(self):
        super().doRollover()
        self._cleanup_old_files()

    def _cleanup_old_files(self):
        log_dir = os.path.dirname(self.baseFilename)
        base_name = os.path.basename(self.baseFilename)
        cutoff = time.time() - (self.max_age_days * 86400)
        for f in os.listdir(log_dir):
            if f.startswith(base_name + ".") and f != base_name:
                path = os.path.join(log_dir, f)
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)


_GLOG_SEVERITY = {
    "debug": "D",
    "info": "I",
    "warning": "W",
    "error": "E",
    "critical": "F",
}


class GlogRenderer:
    """Render log lines in glog format.

    Output: ``I0604 13:15:30.123456 12345 module.py:42] message key=value ...``
    """

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> str:
        level = event_dict.pop("level", method)
        severity = _GLOG_SEVERITY.get(level, "I")

        # Timestamp -- prefer the structlog-injected ISO timestamp, fall back to now.
        ts_raw = event_dict.pop("timestamp", None)
        if ts_raw and isinstance(ts_raw, str):
            try:
                dt = datetime.datetime.fromisoformat(ts_raw)
            except (ValueError, TypeError):
                dt = datetime.datetime.now()
        else:
            dt = datetime.datetime.now()

        date_part = dt.strftime("%m%d")
        time_part = dt.strftime("%H:%M:%S.%f")

        pid = os.getpid()

        # Location: prefer logger_name, fall back to filename:lineno if present.
        logger_name = event_dict.pop("logger", None)
        location = logger_name or "unknown"

        event = event_dict.pop("event", "")

        # Remaining keys as key=value pairs.
        extras = " ".join(f"{k}={v}" for k, v in event_dict.items()) if event_dict else ""

        msg = f"{severity}{date_part} {time_part} {pid} {location}] {event}"
        if extras:
            msg = f"{msg} {extras}"
        return msg


def setup_logging(
    log_format: str = "glog",
    log_dir: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    max_age_days: int = 84,
    timezone: str = "America/Los_Angeles",
    extra_processors: list | None = None,
) -> None:
    """Configure structlog with glog, JSON, or console output.

    Args:
        log_format: "glog" (default), "json" for production, "console" for dev.
        log_dir: Directory for log files. None = stderr only.
        level: Logging level.
        max_bytes: Max log file size before rotation.
        max_age_days: Delete rotated logs older than this.
        timezone: Timezone for timestamps.
        extra_processors: Additional structlog processors (e.g., SanitizingProcessor).
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if extra_processors:
        shared_processors.extend(extra_processors)

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    elif log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = GlogRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = AgeRotatingFileHandler(
            os.path.join(log_dir, "workbench.log"),
            max_age_days=max_age_days,
            maxBytes=max_bytes,
            backupCount=10,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

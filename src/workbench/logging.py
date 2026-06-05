from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog
from structlog.processors import CallsiteParameter, CallsiteParameterAdder


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


def setup_logging(
    log_format: str = "json",
    log_dir: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    max_age_days: int = 84,
    timezone: str = "America/Los_Angeles",
    extra_processors: list | None = None,
) -> None:
    """Configure structlog with JSON (default) or console output.

    File output is always JSON (the logview.py viewer's input contract);
    log_format controls only the stderr stream renderer.

    Args:
        log_format: "json" (default) or "console" for dev. Unknown values
            fall back to JSON.
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
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        CallsiteParameterAdder(
            [CallsiteParameter.FILENAME, CallsiteParameter.LINENO, CallsiteParameter.FUNC_NAME]
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if extra_processors:
        shared_processors.extend(extra_processors)

    stderr_renderer = (
        structlog.dev.ConsoleRenderer()
        if log_format == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    def _formatter(renderer):
        # foreign_pre_chain runs shared_processors on stdlib LogRecords (apscheduler,
        # uvicorn, logging.getLogger(...)) so they get timestamp/level/logger/file:line
        # too — not just structlog-native loggers.
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(_formatter(stderr_renderer))
    root_logger.addHandler(stderr_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = AgeRotatingFileHandler(
            os.path.join(log_dir, "workbench.log"),
            max_age_days=max_age_days,
            maxBytes=max_bytes,
            backupCount=10,
        )
        file_handler.setFormatter(_formatter(structlog.processors.JSONRenderer()))
        root_logger.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

import logging
import logging.handlers
import os
import sys
from typing import Any

import structlog
from structlog.processors import CallsiteParameter, CallsiteParameterAdder


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        CallsiteParameterAdder(
            [
                CallsiteParameter.FILENAME,
                CallsiteParameter.LINENO,
                CallsiteParameter.FUNC_NAME,
            ]
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def _json_formatter() -> logging.Formatter:
    return structlog.stdlib.ProcessorFormatter(
        # foreign_pre_chain runs the shared chain on stdlib LogRecords (uvicorn,
        # logging.getLogger(...)) so they get timestamp/level/logger/file:line too.
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )


def setup_logging(
    level: int = logging.INFO,
    timezone: str = "America/Los_Angeles",
    log_dir: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
) -> None:
    """Configure structlog -> JSON, matching the workbench JSON line schema.

    timezone is accepted for call-site compatibility; ISO timestamps are emitted
    in UTC (with a trailing 'Z'/'+00:00') regardless of the configured zone.

    When log_dir is set, a rotating file handler writes pure JSON (same schema
    as stderr) to <log_dir>/memory.log, so the on-disk log stays clean and
    rotates. The stderr StreamHandler is always kept (it feeds docker logs).
    """
    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    logging.captureWarnings(True)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_json_formatter())
    root.addHandler(handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "memory.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setFormatter(_json_formatter())
        root.addHandler(file_handler)

    for name in ("uvicorn.access", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True

import datetime
import logging
import os
import sys
import threading
import zoneinfo


class GlogFormatter(logging.Formatter):
    """Google-style log format: Lmmdd HH:MM:SS.uuuuuu threadid file:line] msg"""

    LEVEL_CHAR = {
        logging.DEBUG: "D",
        logging.INFO: "I",
        logging.WARNING: "W",
        logging.ERROR: "E",
        logging.CRITICAL: "F",
    }

    def __init__(self, timezone: str = "America/Los_Angeles", **kwargs):
        super().__init__(**kwargs)
        self._tz = zoneinfo.ZoneInfo(timezone)

    def format(self, record: logging.LogRecord) -> str:
        level = self.LEVEL_CHAR.get(record.levelno, "?")
        dt = datetime.datetime.fromtimestamp(record.created, tz=self._tz)
        ts = dt.strftime("%m%d %H:%M:%S")
        usecs = f"{record.created % 1:.6f}"[2:]
        tid = threading.get_ident() % 100000
        filename = os.path.basename(record.pathname)
        msg = f"{level}{ts}.{usecs} {tid:5d} {filename}:{record.lineno}] {record.getMessage()}"
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = f"{msg}\n{record.exc_text}"
        if record.stack_info:
            msg = f"{msg}\n{record.stack_info}"
        return msg


def setup_logging(
    level: int = logging.INFO,
    timezone: str = "America/Los_Angeles",
) -> None:
    formatter = GlogFormatter(timezone=timezone)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True
    logging.getLogger("uvicorn.error").handlers.clear()
    logging.getLogger("uvicorn.error").propagate = True

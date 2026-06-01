import datetime
import logging
import os
import sys
import threading
import time
import zoneinfo
from logging.handlers import RotatingFileHandler


class AgeRotatingFileHandler(RotatingFileHandler):
    """Size-based rotation with age-based backup cleanup."""

    def __init__(self, filename: str, max_age_days: int = 84, **kwargs):
        kwargs.pop("backupCount", None)
        super().__init__(filename, backupCount=1, **kwargs)
        self.max_age_days = max_age_days

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        max_i = 0
        while os.path.exists(f"{self.baseFilename}.{max_i + 1}"):
            max_i += 1

        cutoff = time.time() - self.max_age_days * 86400
        for i in range(max_i, 0, -1):
            if os.path.getmtime(f"{self.baseFilename}.{i}") < cutoff:
                os.remove(f"{self.baseFilename}.{i}")
                max_i = i - 1
            else:
                break

        for i in range(max_i, 0, -1):
            os.rename(
                f"{self.baseFilename}.{i}",
                f"{self.baseFilename}.{i + 1}",
            )

        if os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, f"{self.baseFilename}.1")

        if not self.delay:
            self.stream = self._open()


class GlogFormatter(logging.Formatter):
    """Google-style log format: Lmmdd HH:MM:SS.uuuuuu threadid file:line] msg"""

    LEVEL_CHAR = {
        logging.DEBUG: "D",
        logging.INFO: "I",
        logging.WARNING: "W",
        logging.ERROR: "E",
        logging.CRITICAL: "F",
    }

    _tz = zoneinfo.ZoneInfo("America/Los_Angeles")

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
    log_dir: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    max_age_days: int = 84,
) -> None:
    formatter = GlogFormatter()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stdout_handler = logging.StreamHandler(sys.stderr)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = AgeRotatingFileHandler(
            os.path.join(log_dir, "workbench.log"),
            maxBytes=max_bytes,
            max_age_days=max_age_days,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True
    logging.getLogger("uvicorn.error").handlers.clear()
    logging.getLogger("uvicorn.error").propagate = True

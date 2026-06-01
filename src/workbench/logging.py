import logging
import os
import sys
import threading


class GlogFormatter(logging.Formatter):
    """Google-style log format: Lmmdd HH:MM:SS.uuuuuu threadid file:line] msg"""

    LEVEL_CHAR = {
        logging.DEBUG: "D",
        logging.INFO: "I",
        logging.WARNING: "W",
        logging.ERROR: "E",
        logging.CRITICAL: "F",
    }

    def format(self, record: logging.LogRecord) -> str:
        level = self.LEVEL_CHAR.get(record.levelno, "?")
        ts = self.formatTime(record, "%m%d %H:%M:%S")
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


def setup_logging(log_dir: str | None = None, level: int = logging.INFO) -> None:
    formatter = GlogFormatter()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stdout_handler = logging.StreamHandler(sys.stderr)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "workbench.log"))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True
    logging.getLogger("uvicorn.error").handlers.clear()
    logging.getLogger("uvicorn.error").propagate = True

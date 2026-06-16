"""Unified Rich log viewer for workbench logs.

Tails every *.log under a directory, parses each emitter's format into a
normalized record, and renders one consistent colored stream.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.text import Text

_LEVELS = {"debug", "info", "warning", "error", "critical"}
_LEVEL_ALIASES = {
    "warn": "warning",
    "err": "error",
    "fatal": "critical",
    "panic": "critical",
    "log": "info",
    "detail": "info",
    "hint": "info",
    "notice": "info",
    "statement": "debug",
    "trace": "debug",
}


@dataclass
class Record:
    ts: datetime.datetime | None
    service: str
    level: str
    location: str | None
    message: str
    extras: dict[str, str] = field(default_factory=dict)
    exception: str | None = None
    raw: str = ""
    logger: str | None = None


def _norm_level(token: str) -> str:
    t = token.strip().lower()
    if t in _LEVELS:
        return t
    return _LEVEL_ALIASES.get(t, "unknown")


def _parse_ts(value: str) -> datetime.datetime | None:
    try:
        # fromisoformat handles 'Z' on 3.11+, but normalize for safety.
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


_GLOG_RE = re.compile(
    r"^(?P<level>[IWEF])(?P<date>\d{4}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+(?P<pid>\d+) "
    r"(?P<loc>.+?)\] (?P<msg>.*)$"
)
_GLOG_LEVELS = {"I": "info", "W": "warning", "E": "error", "F": "critical"}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_PY_WARNING_RE = re.compile(r"\w+Warning\b")

_STRUCTURAL = {
    "timestamp",
    "level",
    "logger",
    "filename",
    "lineno",
    "func_name",
    "event",
    "exception",
}


def parse_json(line: str, service: str) -> Record:
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return parse_raw(line, service)
    logger_name = str(obj.get("logger", ""))
    if logger_name.split(".", 1)[0] == "uvicorn":
        loc = logger_name  # framework internal callsite is misleading; show the logger
    elif obj.get("filename") and obj.get("lineno") is not None:
        loc = f"{obj['filename']}:{obj['lineno']}"
    else:
        loc = None
    extras = {k: str(v) for k, v in obj.items() if k not in _STRUCTURAL}
    exc = obj.get("exception")
    return Record(
        ts=_parse_ts(obj.get("timestamp", "")),
        service=service,
        level=_norm_level(obj.get("level", "info")),
        location=loc,
        message=str(obj.get("event", "")),
        extras=extras,
        exception=str(exc) if exc else None,
        raw=line,
        logger=logger_name or None,
    )


# Tolerates the double space that appears when %q%u@%d collapses to empty
# (non-session logs) but the trailing space in the prefix remains.
_PG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ \w+) \[(?P<pid>\d+)\]\s+"
    r"(?P<level>[A-Z]+):\s+(?P<msg>.*)$"
)


def parse_postgres(line: str, service: str) -> Record:
    m = _PG_RE.match(line)
    if not m:
        if line.startswith("\t"):
            return Record(
                ts=None,
                service=service,
                level="debug",
                location=None,
                message=line.strip(),
                raw=line,
            )
        return parse_raw(line, service)
    ts = None
    try:
        ts = datetime.datetime.strptime(m["ts"][:23], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        pass
    return Record(
        ts=ts,
        service=service,
        level=_norm_level(m["level"]),
        location=f"pid {m['pid']}",
        message=m["msg"],
        raw=line,
    )


_NEO4J_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+[+\-]\d{4}) "
    r"(?P<level>[A-Z]+)\s+(?:\[(?P<comp>[^\]]*)\]\s*)?(?P<msg>.*)$"
)


def parse_neo4j(line: str, service: str) -> Record:
    m = _NEO4J_RE.match(line)
    if not m:
        return parse_raw(line, service)
    return Record(
        ts=_parse_ts(m["ts"]),
        service=service,
        level=_norm_level(m["level"]),
        location=m["comp"] or None,
        message=m["msg"],
        raw=line,
    )


_KW_RE = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG)\b")
_KW_CI_RE = re.compile(
    r"\b(critical|fatal|error|warning|warn|info|debug)\b", re.IGNORECASE
)


def _parse_glog_ts(date_str: str, time_str: str) -> datetime.datetime | None:
    try:
        month, day = int(date_str[:2]), int(date_str[2:])
        t = datetime.datetime.strptime(time_str[:15], "%H:%M:%S.%f")
        return datetime.datetime(
            datetime.date.today().year,
            month,
            day,
            t.hour,
            t.minute,
            t.second,
            t.microsecond,
        )
    except (ValueError, AttributeError):
        return None


def parse_raw(line: str, service: str) -> Record:
    m = _GLOG_RE.match(line)
    if m:
        return Record(
            ts=_parse_glog_ts(m["date"], m["time"]),
            service=service,
            level=_GLOG_LEVELS[m["level"]],
            location=m["loc"],
            message=m["msg"],
            raw=line,
        )
    clean = _ANSI_RE.sub("", line) if "\x1b" in line else line
    m = _KW_RE.search(clean)
    if not m:
        m = _KW_CI_RE.search(clean)
    if m:
        level = _norm_level(m.group(1))
    elif _PY_WARNING_RE.search(clean):
        level = "warning"
    else:
        level = "unknown"
    return Record(
        ts=None, service=service, level=level, location=None, message=line, raw=line
    )


PARSERS = {
    "workbench": parse_json,
    "memory": parse_json,
    "postgres": parse_postgres,
    "neo4j": parse_neo4j,
}


def parser_for(service: str):
    return PARSERS.get(service, parse_raw)


DEFAULT_TZ = ZoneInfo("America/Los_Angeles")

LEVEL_GLYPH = {
    "debug": "D",
    "info": "I",
    "warning": "W",
    "error": "E",
    "critical": "F",
    "unknown": "?",
}
LEVEL_STYLE = {
    "debug": "dim",
    "info": "green",
    "warning": "yellow",
    "error": "red",
    "critical": "bold red",
    "unknown": "dim",
}
_SERVICE_STYLES = ["cyan", "magenta", "blue", "bright_black", "bright_cyan"]
_service_color: dict[str, str] = {}


def _service_style(service: str) -> str:
    if service not in _service_color:
        _service_color[service] = _SERVICE_STYLES[
            len(_service_color) % len(_SERVICE_STYLES)
        ]
    return _service_color[service]


def render_line(r: Record, display_tz: datetime.tzinfo = DEFAULT_TZ) -> Text:
    style = LEVEL_STYLE.get(r.level, "dim")
    t = Text()
    if r.ts is None:
        when = "--:--:--"
    elif r.ts.tzinfo is not None:
        when = r.ts.astimezone(display_tz).strftime("%H:%M:%S")  # UTC -> display zone
    else:
        when = r.ts.strftime("%H:%M:%S")  # naive: already in its configured zone
    t.append(f"{when} ", style="dim")
    t.append(f"[{r.service}] ", style=_service_style(r.service))
    t.append(f"{LEVEL_GLYPH.get(r.level, '?')} ", style=style)
    if r.location:
        t.append(f"{r.location}  ", style="dim")
    t.append(r.message, style=style)
    for k, v in r.extras.items():
        t.append(f"  {k}={v}", style="dim")
    if r.exception:
        for ln in r.exception.splitlines():
            t.append(f"\n    {ln}", style="dim red")
    return t


_LEVEL_ORDER = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
    "unknown": 1,
}


def service_from_path(path: str) -> str:
    return Path(path).stem


def should_show(
    r: Record, services: set, excludes: set, min_level, exclude_loggers=frozenset()
) -> bool:
    if excludes and r.service in excludes:
        return False
    # Match on the logger name or any dotted prefix, so "uvicorn" also hides
    # "uvicorn.access" / "uvicorn.error". Catches access lines that propagate
    # into other service files, not just the dedicated access.log.
    if exclude_loggers and r.logger:
        parts = r.logger.split(".")
        if any(
            ".".join(parts[:i]) in exclude_loggers for i in range(1, len(parts) + 1)
        ):
            return False
    if services and r.service not in services:
        return False
    # unknown is fail-open so parse_raw lines are never dropped by a level filter
    if (
        min_level
        and r.level != "unknown"
        and _LEVEL_ORDER.get(r.level, 1) < _LEVEL_ORDER[min_level]
    ):
        return False
    return True


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _is_request_completed(r: Record) -> bool:
    return r.message == "request completed" and "duration_ms" in r.extras


class RequestBatcher:
    """Rolls up high-frequency 'request completed' middleware records into one
    periodic summary line (count, ok/failed, avg + slowest endpoint) instead of
    one line per request. Failures (status >= 400) are still printed individually
    by the caller so they stay visible; they are also counted in the rollup.

    A window closes on a wall-clock idle gap (follow mode) or once it spans
    MAX_SPAN seconds of log time, whichever comes first; the caller flushes any
    remainder at EOF / on exit."""

    IDLE_GAP = 16.0  # wall-clock seconds of quiet that closes a window (follow)
    MAX_SPAN = 480.0  # max log-time seconds a single summary may cover

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.failed = 0
        self.dur_sum = 0.0
        self.slow_ms = -1.0
        self.slow_label = ""
        self.first_ts = None
        self.last_ts = None
        self.last_added_mono = None

    @property
    def pending(self) -> bool:
        return self.count > 0

    def add(self, r: Record, now_mono: float) -> None:
        status = _as_int(r.extras.get("status_code"))
        ms = _as_float(r.extras.get("duration_ms"))
        self.count += 1
        if status is not None and status >= 400:
            self.failed += 1
        if ms is not None:
            self.dur_sum += ms
            if ms > self.slow_ms:
                self.slow_ms = ms
                self.slow_label = (
                    f"{r.extras.get('method', '')} {r.extras.get('path', '')}".strip()
                )
        if self.first_ts is None:
            self.first_ts = r.ts
        self.last_ts = r.ts
        self.last_added_mono = now_mono

    def span_exceeded(self, new_ts) -> bool:
        if self.first_ts is None or new_ts is None:
            return False
        return (new_ts - self.first_ts).total_seconds() > self.MAX_SPAN

    def idle(self, now_mono: float) -> bool:
        return (
            self.pending
            and self.last_added_mono is not None
            and now_mono - self.last_added_mono >= self.IDLE_GAP
        )

    def _summary_record(self) -> Record:
        avg = self.dur_sum / self.count if self.count else 0.0
        span = 0.0
        if self.first_ts and self.last_ts:
            span = (self.last_ts - self.first_ts).total_seconds()
        ok = self.count - self.failed
        head = f"{self.count} requests"
        if span >= 1:
            head += f" in {span:.0f}s"
        parts = [head]
        parts.append("all ok" if not self.failed else f"{ok} ok, {self.failed} failed")
        parts.append(f"avg {avg:.1f}ms")
        if self.slow_ms >= 0:
            parts.append(f"slowest {self.slow_label} ({self.slow_ms:.1f}ms)")
        return Record(
            ts=self.last_ts,
            service="workbench",
            level="warning" if self.failed else "info",
            location="requests",
            message="Σ " + " · ".join(parts),
            raw="",
        )

    def flush(self, console: Console, display_tz) -> None:
        if not self.pending:
            return
        console.print(render_line(self._summary_record(), display_tz), soft_wrap=True)
        self.reset()


def _emit(
    console: Console, path: str, line: str, args, display_tz, batcher=None
) -> None:
    service = service_from_path(path)
    r = parser_for(service)(line.rstrip("\n"), service)
    if not should_show(
        r,
        set(args.service or []),
        set(args.exclude or []),
        args.level,
        set(args.exclude_logger or []),
    ):
        return
    if batcher is not None and _is_request_completed(r):
        if batcher.span_exceeded(r.ts):
            batcher.flush(console, display_tz)
        batcher.add(r, _time.monotonic())
        status = _as_int(r.extras.get("status_code"))
        if status is not None and status >= 400:
            # keep failures visible inline; they are also counted in the rollup
            console.print(render_line(r, display_tz), soft_wrap=True)
        return
    console.print(render_line(r, display_tz), soft_wrap=True)


def _drain(console: Console, sp: str, fh, args, display_tz, batcher=None) -> None:
    """Emit only complete (newline-terminated) lines; rewind on a partial line
    so it is rendered once, later, when the writer finishes it."""
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line or not line.endswith("\n"):
            fh.seek(pos)
            return
        _emit(console, sp, line, args, display_tz, batcher)


def _follow(console: Console, directory: str, args, display_tz) -> None:
    batcher = RequestBatcher() if args.batch_requests else None
    handles: dict = {}
    inodes: dict = {}
    first_pass = True
    announced_empty = False
    try:
        while True:
            paths = sorted(Path(directory).glob("*.log"))
            if not paths and not announced_empty:
                console.print(f"[dim]no *.log files in {directory} yet…[/dim]")
                announced_empty = True
            for path in paths:
                sp = str(path)
                try:
                    st = path.stat()
                except FileNotFoundError:
                    continue
                tracked = sp in handles
                if not tracked or inodes.get(sp) != st.st_ino:
                    if tracked:
                        handles[sp].close()
                    fh = open(sp, "r", encoding="utf-8", errors="replace")
                    # On the first pass, skip history of pre-existing files. New or
                    # rotated files (inode changed) are read from the start.
                    if first_pass:
                        fh.seek(0, os.SEEK_END)
                    handles[sp] = fh
                    inodes[sp] = st.st_ino
                fh = handles[sp]
                if fh.tell() > st.st_size:  # truncated in place
                    fh.seek(0)
                _drain(console, sp, fh, args, display_tz, batcher)
            first_pass = False
            if batcher is not None and batcher.idle(_time.monotonic()):
                batcher.flush(console, display_tz)
            _time.sleep(0.25)
    except KeyboardInterrupt:
        if batcher is not None:
            batcher.flush(console, display_tz)
        raise


def _read_once(console: Console, directory: str, args, display_tz) -> None:
    batcher = RequestBatcher() if args.batch_requests else None
    for path in sorted(Path(directory).glob("*.log")):
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.endswith("\n"):
                    _emit(console, str(path), line, args, display_tz, batcher)
    if batcher is not None:
        batcher.flush(console, display_tz)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unified Rich log viewer for workbench.")
    p.add_argument("directory", nargs="?", default="data/logs")
    p.add_argument("--level", choices=sorted(_LEVEL_ORDER))
    p.add_argument(
        "--service", action="append", help="repeatable; show only these services"
    )
    p.add_argument("--exclude", action="append", help="repeatable; hide these services")
    p.add_argument(
        "--exclude-logger",
        action="append",
        help="repeatable; hide records from these loggers (matches dotted prefixes, "
        "e.g. 'uvicorn' hides 'uvicorn.access')",
    )
    p.add_argument("--tz", default="America/Los_Angeles", help="display timezone")
    p.add_argument("--no-follow", action="store_true")
    p.add_argument(
        "--batch-requests",
        action="store_true",
        help="roll up 'request completed' middleware logs into periodic summary "
        "lines (count, avg + slowest endpoint); failures still shown individually",
    )
    args = p.parse_args(argv)
    console = Console()
    display_tz = ZoneInfo(args.tz)
    if args.no_follow:
        _read_once(console, args.directory, args, display_tz)
        return 0
    try:
        _follow(console, args.directory, args, display_tz)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

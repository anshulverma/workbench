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
    "warn": "warning", "err": "error", "fatal": "critical", "panic": "critical",
    "log": "info", "detail": "info", "hint": "info", "notice": "info",
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


_STRUCTURAL = {"timestamp", "level", "logger", "filename", "lineno",
               "func_name", "event", "exception"}


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
        level=_norm_level(obj.get("level", "unknown")),
        location=loc,
        message=str(obj.get("event", "")),
        extras=extras,
        exception=str(exc) if exc else None,
        raw=line,
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
        return parse_raw(line, service)
    ts = None
    try:
        ts = datetime.datetime.strptime(m["ts"][:23], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        pass
    return Record(ts=ts, service=service, level=_norm_level(m["level"]),
                  location=f"pid {m['pid']}", message=m["msg"], raw=line)


_NEO4J_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+[+\-]\d{4}) "
    r"(?P<level>[A-Z]+)\s+\[(?P<comp>[^\]]*)\]\s*(?P<msg>.*)$"
)


def parse_neo4j(line: str, service: str) -> Record:
    m = _NEO4J_RE.match(line)
    if not m:
        return parse_raw(line, service)
    return Record(ts=_parse_ts(m["ts"]), service=service, level=_norm_level(m["level"]),
                  location=m["comp"] or None, message=m["msg"], raw=line)


_KW_RE = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG)\b")


def parse_raw(line: str, service: str) -> Record:
    m = _KW_RE.search(line)
    level = _norm_level(m.group(1)) if m else "unknown"
    return Record(ts=None, service=service, level=level, location=None,
                  message=line, raw=line)


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
    "debug": "D", "info": "I", "warning": "W",
    "error": "E", "critical": "F", "unknown": "?",
}
LEVEL_STYLE = {
    "debug": "dim", "info": "green", "warning": "yellow",
    "error": "red", "critical": "bold red", "unknown": "dim",
}
_SERVICE_STYLES = ["cyan", "magenta", "blue", "bright_black", "bright_cyan"]
_service_color: dict[str, str] = {}


def _service_style(service: str) -> str:
    if service not in _service_color:
        _service_color[service] = _SERVICE_STYLES[len(_service_color) % len(_SERVICE_STYLES)]
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


_LEVEL_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4, "unknown": 1}


def service_from_path(path: str) -> str:
    return Path(path).stem


def should_show(r: Record, services: set, excludes: set, min_level) -> bool:
    if excludes and r.service in excludes:
        return False
    if services and r.service not in services:
        return False
    # unknown is fail-open so parse_raw lines are never dropped by a level filter
    if min_level and r.level != "unknown" and _LEVEL_ORDER.get(r.level, 1) < _LEVEL_ORDER[min_level]:
        return False
    return True


def _emit(console: Console, path: str, line: str, args, display_tz) -> None:
    service = service_from_path(path)
    r = parser_for(service)(line.rstrip("\n"), service)
    if should_show(r, set(args.service or []), set(args.exclude or []), args.level):
        console.print(render_line(r, display_tz), soft_wrap=True)


def _drain(console: Console, sp: str, fh, args, display_tz) -> None:
    """Emit only complete (newline-terminated) lines; rewind on a partial line
    so it is rendered once, later, when the writer finishes it."""
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line or not line.endswith("\n"):
            fh.seek(pos)
            return
        _emit(console, sp, line, args, display_tz)


def _follow(console: Console, directory: str, args, display_tz) -> None:
    handles: dict = {}
    inodes: dict = {}
    first_pass = True
    announced_empty = False
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
            _drain(console, sp, fh, args, display_tz)
        first_pass = False
        _time.sleep(0.25)


def _read_once(console: Console, directory: str, args, display_tz) -> None:
    for path in sorted(Path(directory).glob("*.log")):
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.endswith("\n"):
                    _emit(console, str(path), line, args, display_tz)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unified Rich log viewer for workbench.")
    p.add_argument("directory", nargs="?", default="data/logs")
    p.add_argument("--level", choices=sorted(_LEVEL_ORDER))
    p.add_argument("--service", action="append", help="repeatable; show only these services")
    p.add_argument("--exclude", action="append", help="repeatable; hide these services")
    p.add_argument("--tz", default="America/Los_Angeles", help="display timezone")
    p.add_argument("--no-follow", action="store_true")
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

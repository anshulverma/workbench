import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import logview


# --- Task 3: parsers + normalized record -------------------------------------

def test_parse_json_maps_fields():
    line = ('{"timestamp":"2026-06-04T20:15:30.123456Z","level":"info",'
            '"logger":"workbench.adapters.gmail","filename":"gmail.py","lineno":42,'
            '"event":"fetched","count":17}')
    r = logview.parse_json(line, "workbench")
    assert r.service == "workbench"
    assert r.level == "info"
    assert r.location == "gmail.py:42"
    assert r.message == "fetched"
    assert r.extras["count"] == "17"
    assert isinstance(r.ts, datetime.datetime)


def test_parse_json_bad_json_falls_back_to_raw():
    r = logview.parse_json("{not json", "workbench")
    assert r.level == "unknown"
    assert r.raw == "{not json"


def test_parse_json_lifts_exception_and_normalizes_utc():
    line = ('{"timestamp":"2026-06-04T20:15:30.123456Z","level":"error",'
            '"logger":"workbench.x","filename":"x.py","lineno":9,"event":"boom",'
            '"exception":"Traceback (most recent call last):\\n  ValueError"}')
    r = logview.parse_json(line, "workbench")
    assert r.exception and "Traceback" in r.exception
    assert "exception" not in r.extras
    assert r.ts is not None and r.ts.utcoffset() == datetime.timedelta(0)


def test_parse_postgres_extracts_level():
    # double space: %q%u@%d is empty for non-session logs, prefix trailing space remains
    line = "2026-06-04 13:15:30.123 PDT [123]  ERROR:  relation does not exist"
    r = logview.parse_postgres(line, "postgres")
    assert r.service == "postgres"
    assert r.level == "error"
    assert "relation does not exist" in r.message


def test_parse_neo4j_extracts_level():
    line = "2026-06-04 13:15:30.000+0000 WARN  [o.n.k.a.p.GlobalProcedures] something"
    r = logview.parse_neo4j(line, "neo4j")
    assert r.level == "warning"


def test_parse_raw_detects_level_keyword():
    r = logview.parse_raw("token refresh ERROR: expired", "dcat")
    assert r.level == "error"
    assert r.service == "dcat"


# --- Task 4: renderer --------------------------------------------------------

def test_render_escapes_markup_and_shows_location():
    r = logview.Record(ts=None, service="workbench", level="error",
                       location="gmail.py:42", message="boom [bold]x[/bold]",
                       extras={"count": "3"}, raw="")
    text = logview.render_line(r)  # returns a rich Text; .plain is the string
    s = text.plain
    assert "[workbench]" in s
    assert "gmail.py:42" in s
    assert "boom [bold]x[/bold]" in s  # literal, not interpreted
    assert "count=3" in s


def test_level_glyph_mapping():
    assert logview.LEVEL_GLYPH["error"] == "E"
    assert logview.LEVEL_GLYPH["info"] == "I"
    assert logview.LEVEL_GLYPH["unknown"] == "?"


# --- Task 5: tail + filters + CLI --------------------------------------------

def test_service_from_path():
    assert logview.service_from_path("/x/data/logs/workbench.log") == "workbench"
    assert logview.service_from_path("/x/data/logs/postgres.log") == "postgres"
    assert logview.service_from_path("/x/data/logs/dcat.log") == "dcat"


def test_should_show_filters():
    r = logview.Record(ts=None, service="memory", level="info", location=None,
                       message="m", raw="")
    # default: nothing filtered, everything shown
    assert logview.should_show(r, services=set(), excludes=set(), min_level=None)
    # service filter (allowlist)
    assert not logview.should_show(r, services={"workbench"}, excludes=set(), min_level=None)
    # level filter
    assert not logview.should_show(r, services=set(), excludes=set(), min_level="warning")
    # generic exclude (Meta passes --exclude dcat)
    dcat = logview.Record(ts=None, service="dcat", level="info", location=None, message="m", raw="")
    assert not logview.should_show(dcat, services=set(), excludes={"dcat"}, min_level=None)
    assert logview.should_show(dcat, services=set(), excludes=set(), min_level=None)
    # unknown level is fail-open under --level so parse_raw lines are never dropped
    unk = logview.Record(ts=None, service="neo4j", level="unknown", location=None, message="m", raw="")
    assert logview.should_show(unk, services=set(), excludes=set(), min_level="error")


# --- Glog format parsing ----------------------------------------------------

def test_glog_info():
    r = logview.parse_raw(
        'I0604 11:33:26.400957 34336 base.py:203] Job executed', "workbench")
    assert r.level == "info"
    assert r.location == "base.py:203"
    assert r.message == "Job executed"
    assert r.ts is not None


def test_glog_error():
    r = logview.parse_raw(
        'E0604 12:54:56.406770 2794032 FileUtil.cpp:546] Open failed', "dcat")
    assert r.level == "error"
    assert r.location == "FileUtil.cpp:546"


def test_glog_warning():
    r = logview.parse_raw("W0604 10:00:00.000000 123 x.py:1] caution", "workbench")
    assert r.level == "warning"


def test_glog_fatal():
    r = logview.parse_raw("F0604 10:00:00.000000 123 x.py:1] crash", "workbench")
    assert r.level == "critical"


# --- JSON missing level defaults to info ------------------------------------

def test_json_missing_level_defaults_info():
    r = logview.parse_json('{"event":"startup"}', "workbench")
    assert r.level == "info"
    assert r.message == "startup"


# --- Neo4j bracketless format -----------------------------------------------

def test_neo4j_bracketless():
    line = "2026-06-02 16:39:28.052+0000 INFO  Logging config in use"
    r = logview.parse_neo4j(line, "neo4j")
    assert r.level == "info"
    assert "Logging config" in r.message
    assert r.location is None


# --- PostgreSQL STATEMENT + SQL continuations --------------------------------

def test_pg_statement_level():
    line = "2026-06-02 19:33:51.930 UTC [287] STATEMENT:  TRUNCATE entities"
    r = logview.parse_postgres(line, "postgres")
    assert r.level == "debug"


def test_pg_sql_continuation():
    r = logview.parse_postgres("\t            UPDATE pending_ingestions", "postgres")
    assert r.level == "debug"
    assert "UPDATE pending_ingestions" in r.message


# --- ThriftPyDeprecatedWarning and ANSI codes --------------------------------

def test_python_warning_pattern():
    line = "monitoring.obc.py:13: ThriftPyDeprecatedWarning: Uses thrift-py-deprecated"
    r = logview.parse_raw(line, "dcat")
    assert r.level == "warning"


def test_ansi_colored_line():
    line = ("\x1b[2m2026-06-04T20:02:59\x1b[0m "
            "[\x1b[32m\x1b[1minfo     \x1b[0m] \x1b[1mConfig loaded\x1b[0m")
    r = logview.parse_raw(line, "workbench")
    assert r.level == "info"


def test_case_insensitive_level_keyword():
    r = logview.parse_raw("INFO:     Started server process [14]", "memory")
    assert r.level == "info"


# --- Acceptance criterion 2: partial-line safety -----------------------------

class _Args:
    service = None
    exclude = None
    level = None


def test_drain_rewinds_on_partial_line_then_renders_once(tmp_path):
    """A line written without a trailing newline must not be emitted until it
    is completed; once completed it renders exactly once."""
    from rich.console import Console

    log = tmp_path / "workbench.log"
    log.write_text(
        '{"timestamp":"2026-06-04T20:15:30Z","level":"info",'
        '"logger":"workbench.x","filename":"x.py","lineno":1,"event":"partial"',
    )  # NOTE: no trailing newline -> partial line

    buf = []

    class _Cap(Console):
        def print(self, renderable, **kwargs):  # capture rendered text
            buf.append(renderable.plain if hasattr(renderable, "plain") else str(renderable))

    console = _Cap(force_terminal=False)
    fh = open(str(log), "r", encoding="utf-8", errors="replace")
    args = _Args()

    # First drain: partial line, nothing emitted, position rewound.
    logview._drain(console, str(log), fh, args, logview.DEFAULT_TZ)
    assert buf == []

    # Complete the line.
    with open(str(log), "a", encoding="utf-8") as w:
        w.write(',"count":2}\n')

    # Second drain: now the full line is emitted exactly once.
    logview._drain(console, str(log), fh, args, logview.DEFAULT_TZ)
    fh.close()
    assert len(buf) == 1
    assert "partial" in buf[0]
    assert "count=2" in buf[0]

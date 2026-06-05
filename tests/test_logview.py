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

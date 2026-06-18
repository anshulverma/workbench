"""Tests for the memory subservice's full-fidelity LLM capture.

These tests exercise the row-builder, the cross-DB writer, and the
enable-flag + table-presence preflight gating WITHOUT importing graphiti_core
or talking to a live Anthropic/Postgres. The asyncpg pool is faked.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from memory.llm_capture import (
    LLM_CALLS_COLUMNS,
    LlmCallWriter,
    build_memory_row,
    extract_completion_text,
    extract_messages,
)


# --------------------------------------------------------------------------
# Row builder / mapping
# --------------------------------------------------------------------------


def test_build_row_origin_stage_and_estimated_tokens():
    started = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    row = build_memory_row(
        started_at=started,
        model="claude-haiku-4-5",
        latency_ms=123,
        status="ok",
        system_prompt="You are a graph extractor.",
        input_prompt="Extract entities from: hello world",
        completion='{"entities": []}',
        structured={"entities": []},
        tokens_in=0,
        tokens_out=0,
        tokens_available=False,
    )
    assert row["origin"] == "memory_subservice"
    assert row["stage"] == "memory"
    assert row["purpose"] == "memory"
    assert row["status"] == "ok"
    assert row["batch"] == 1
    assert row["items"] == []
    assert row["tokens_estimated"] is True
    assert row["is_fallback"] is False
    assert row["system_prompt"] == "You are a graph extractor."
    assert row["latency_ms"] == 123
    assert row["started_at"] == started
    # subcall captured with body
    assert len(row["subcalls"]) == 1
    sub = row["subcalls"][0]
    assert sub["item"] == ""
    assert sub["prompt"] == "Extract entities from: hello world"
    assert sub["completion"] == '{"entities": []}'
    assert sub["structured"] == {"entities": []}
    assert sub["tokens_in"] == 0
    assert sub["tokens_out"] == 0


def test_build_row_tokens_available_not_estimated():
    row = build_memory_row(
        started_at=datetime.now(timezone.utc),
        model="m",
        latency_ms=10,
        status="ok",
        system_prompt=None,
        input_prompt="p",
        completion="c",
        structured=None,
        tokens_in=12,
        tokens_out=34,
        tokens_available=True,
    )
    assert row["tokens_estimated"] is False
    assert row["tokens_in"] == 12
    assert row["tokens_out"] == 34
    assert row["subcalls"][0]["tokens_in"] == 12
    assert row["subcalls"][0]["tokens_out"] == 34


def test_build_row_error_status_with_error_type():
    row = build_memory_row(
        started_at=datetime.now(timezone.utc),
        model="m",
        latency_ms=5,
        status="error",
        error_type="ValueError",
        system_prompt=None,
        input_prompt=None,
        completion=None,
        structured=None,
        tokens_in=0,
        tokens_out=0,
        tokens_available=False,
    )
    assert row["status"] == "error"
    assert row["error_type"] == "ValueError"
    # no body captured => empty subcalls
    assert row["subcalls"] == []


def test_build_row_column_contract_matches_store():
    row = build_memory_row(
        started_at=datetime.now(timezone.utc),
        model="m",
        latency_ms=1,
        status="ok",
        system_prompt=None,
        input_prompt="p",
        completion="c",
        structured=None,
        tokens_in=0,
        tokens_out=0,
        tokens_available=False,
    )
    # Every persisted column (except DB-managed id/created_at) is present.
    assert set(row.keys()) == set(LLM_CALLS_COLUMNS)


# --------------------------------------------------------------------------
# Message / completion extraction (graphiti-agnostic, defensive)
# --------------------------------------------------------------------------


def test_extract_messages_from_message_objects():
    class _Msg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    msgs = [_Msg("system", "sys text"), _Msg("user", "user text")]
    system_prompt, input_prompt = extract_messages(msgs)
    assert system_prompt == "sys text"
    assert "user text" in input_prompt


def test_extract_messages_from_dicts():
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U1"},
        {"role": "user", "content": "U2"},
    ]
    system_prompt, input_prompt = extract_messages(msgs)
    assert system_prompt == "S"
    assert "U1" in input_prompt and "U2" in input_prompt


def test_extract_messages_handles_garbage():
    system_prompt, input_prompt = extract_messages(None)
    assert system_prompt is None
    assert input_prompt is None


def test_extract_completion_text_from_dict():
    assert extract_completion_text({"a": 1}).startswith("{")
    assert extract_completion_text("plain") == "plain"
    assert extract_completion_text(None) is None


# --------------------------------------------------------------------------
# Writer: preflight / gating / best-effort
# --------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, regclass="llm_calls", fail_execute=False):
        self._regclass = regclass
        self._fail_execute = fail_execute
        self.executed = []

    async def fetchval(self, query, *args):
        if "to_regclass" in query:
            return self._regclass
        return None

    async def execute(self, query, *args):
        if self._fail_execute:
            raise RuntimeError("db down")
        self.executed.append((query, args))


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def _row():
    return build_memory_row(
        started_at=datetime.now(timezone.utc),
        model="m",
        latency_ms=1,
        status="ok",
        system_prompt=None,
        input_prompt="p",
        completion="c",
        structured=None,
        tokens_in=0,
        tokens_out=0,
        tokens_available=False,
    )


@pytest.mark.asyncio
async def test_writer_disabled_when_flag_off_does_not_write():
    conn = _FakeConn()
    w = LlmCallWriter(pool=_FakePool(conn), enabled=False)
    await w.preflight()
    assert w.active is False
    await w.write(_row())
    assert conn.executed == []


@pytest.mark.asyncio
async def test_writer_disabled_when_no_pool():
    w = LlmCallWriter(pool=None, enabled=True)
    await w.preflight()
    assert w.active is False
    await w.write(_row())  # no crash


@pytest.mark.asyncio
async def test_writer_preflight_table_absent_disables_and_warns(caplog):
    conn = _FakeConn(regclass=None)
    w = LlmCallWriter(pool=_FakePool(conn), enabled=True)
    with caplog.at_level(logging.WARNING):
        await w.preflight()
    assert w.active is False
    assert any("llm_calls" in r.message for r in caplog.records)
    await w.write(_row())
    assert conn.executed == []


@pytest.mark.asyncio
async def test_writer_preflight_table_present_enables_and_writes():
    conn = _FakeConn(regclass="llm_calls")
    w = LlmCallWriter(pool=_FakePool(conn), enabled=True)
    await w.preflight()
    assert w.active is True
    await w.write(_row())
    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "INSERT INTO llm_calls" in query
    # 19 columns => 19 bound params
    assert len(args) == len(LLM_CALLS_COLUMNS)


@pytest.mark.asyncio
async def test_writer_db_failure_does_not_propagate(caplog):
    conn = _FakeConn(regclass="llm_calls", fail_execute=True)
    w = LlmCallWriter(pool=_FakePool(conn), enabled=True)
    await w.preflight()
    assert w.active is True
    # Must not raise even though execute() raises.
    with caplog.at_level(logging.WARNING):
        await w.write(_row())
    # best-effort: error logged, swallowed
    assert any(
        "llm_calls" in r.message.lower() or "capture" in r.message.lower()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_writer_write_noop_before_preflight():
    conn = _FakeConn(regclass="llm_calls")
    w = LlmCallWriter(pool=_FakePool(conn), enabled=True)
    # active defaults False until preflight passes
    await w.write(_row())
    assert conn.executed == []

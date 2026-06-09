import asyncio

import pytest

from workbench.models import RawItem
from workbench.providers.change_detector.base import ChangeResult
from workbench.pipeline.debounce import DebounceManager


def _raw(rid="i1"):
    return RawItem(id=rid, source_type="diff", source_label="l", raw_text="{}")


def _result(critical=False, fields=None, ctype="status_changed", reason="r"):
    return ChangeResult(
        is_material=True,
        is_critical=critical,
        changed_fields=fields or ["status"],
        change_type=ctype,
        reason=reason,
    )


@pytest.mark.asyncio
async def test_single_fire_after_delay():
    fired = []

    async def cb(iid, result, raw, old):
        fired.append((iid, result))

    mgr = DebounceManager(cb, delay_seconds=0.02)
    mgr.schedule("it1", _result(), _raw(), {"a": 1})
    assert mgr.pending_count == 1
    await asyncio.sleep(0.06)
    assert len(fired) == 1 and fired[0][0] == "it1"
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_merge_within_window_fires_once_and_keeps_earliest_old_raw():
    fired = []

    async def cb(iid, result, raw, old):
        fired.append((result, old))

    mgr = DebounceManager(cb, delay_seconds=0.05)
    mgr.schedule("it1", _result(fields=["status"], critical=False), _raw(), {"a": 1})
    await asyncio.sleep(0.01)
    mgr.schedule("it1", _result(fields=["ci"], critical=True), _raw(), {"a": 2})
    await asyncio.sleep(0.12)
    assert len(fired) == 1
    merged, old = fired[0]
    assert set(merged.changed_fields) == {"status", "ci"}
    assert merged.is_critical is True
    assert old == {"a": 1}  # earliest pre-change snapshot preserved


@pytest.mark.asyncio
async def test_cancel_prevents_fire():
    fired = []

    async def cb(*a):
        fired.append(a)

    mgr = DebounceManager(cb, delay_seconds=0.02)
    mgr.schedule("it1", _result(), _raw(), {})
    mgr.cancel("it1")
    await asyncio.sleep(0.06)
    assert fired == []
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_cancel_all_clears_pending():
    fired = []

    async def cb(*a):
        fired.append(a)

    mgr = DebounceManager(cb, delay_seconds=0.02)
    mgr.schedule("a", _result(), _raw("a"), {})
    mgr.schedule("b", _result(), _raw("b"), {})
    mgr.cancel_all()
    await asyncio.sleep(0.06)
    assert fired == []
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_different_item_ids_fire_independently():
    fired = []

    async def cb(iid, *a):
        fired.append(iid)

    mgr = DebounceManager(cb, delay_seconds=0.02)
    mgr.schedule("a", _result(), _raw("a"), {})
    mgr.schedule("b", _result(), _raw("b"), {})
    await asyncio.sleep(0.06)
    assert set(fired) == {"a", "b"}

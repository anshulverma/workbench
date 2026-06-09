from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict

from workbench.domain import RawItem
from workbench.providers.change_detector.base import ChangeResult


class DebouncedChange(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_id: str
    merged_result: ChangeResult
    raw_item: RawItem
    old_raw: dict
    timer_handle: asyncio.TimerHandle | None = None


class DebounceManager:
    """In-memory trailing-edge timer (per item_id) that collapses rapid
    re-triage requests into a single regeneration. State is lost on restart;
    the next poll re-detects via the ChangeDetector (acceptable single-user)."""

    def __init__(self, fire_callback, delay_seconds: float = 120.0):
        self._pending: dict[str, DebouncedChange] = {}
        self._fire_callback = fire_callback
        self._delay = delay_seconds

    def schedule(
        self, item_id: str, result: ChangeResult, raw_item: RawItem, old_raw: dict
    ) -> None:
        loop = asyncio.get_running_loop()

        if item_id in self._pending:
            old_entry = self._pending[item_id]
            if old_entry.timer_handle is not None:
                old_entry.timer_handle.cancel()
            merged = self._merge_results(old_entry.merged_result, result)
            preserved_old_raw = (
                old_entry.old_raw
            )  # keep the earliest pre-change snapshot
        else:
            merged = result
            preserved_old_raw = old_raw

        handle = loop.call_later(
            self._delay,
            lambda iid=item_id: asyncio.ensure_future(self._fire(iid)),
        )

        self._pending[item_id] = DebouncedChange(
            item_id=item_id,
            merged_result=merged,
            raw_item=raw_item,
            old_raw=preserved_old_raw,
            timer_handle=handle,
        )

    async def _fire(self, item_id: str) -> None:
        entry = self._pending.pop(item_id, None)
        if entry is None:
            return
        await self._fire_callback(
            entry.item_id, entry.merged_result, entry.raw_item, entry.old_raw
        )

    @staticmethod
    def _merge_results(old: ChangeResult, new: ChangeResult) -> ChangeResult:
        merged_fields = list(dict.fromkeys(old.changed_fields + new.changed_fields))
        return ChangeResult(
            is_material=old.is_material or new.is_material,
            is_terminal=new.is_terminal,
            is_critical=old.is_critical or new.is_critical,
            changed_fields=merged_fields,
            change_type=new.change_type,
            reason=f"{old.reason}; {new.reason}",
        )

    def cancel(self, item_id: str) -> None:
        entry = self._pending.pop(item_id, None)
        if entry is not None and entry.timer_handle is not None:
            entry.timer_handle.cancel()

    def cancel_all(self) -> None:
        for entry in self._pending.values():
            if entry.timer_handle is not None:
                entry.timer_handle.cancel()
        self._pending.clear()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

from __future__ import annotations

from workbench.providers.change_detector.base import ChangeDetector, ChangeResult


class AlwaysMaterialDetector(ChangeDetector):
    """Fallback detector used when no source-specific detector is configured.
    Treats every change as material (and never terminal). Because re-check
    routing is gated on adapter.supports_monitoring(), this is never invoked
    for sources that do not support monitoring."""

    def __init__(self, source_type_name: str):
        self._source_type = source_type_name

    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult:
        return ChangeResult(
            is_material=True,
            is_terminal=False,
            is_critical=False,
            changed_fields=[],
            change_type="unknown",
            reason="No change detector registered; treating all changes as material",
        )

    def source_type(self) -> str:
        return self._source_type

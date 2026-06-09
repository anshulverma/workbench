# providers/change_detector

**Purpose:** ChangeDetector implementations behind the `ChangeDetector` base
interface — they decide whether a re-observed source item has materially changed
and warrants re-triage.

**What belongs here:** the `ChangeDetector` base interface (`base.py`) and
concrete implementations — `fallback.py` (the default fallback detector).

**What does NOT belong here:** other provider families, the ChangeContext
building or debounce logic (`pipeline/change_context.py`, `pipeline/debounce.py`),
or change-state persistence (`storage/`).

**Update this README when** you add a new KIND of code here (a new change
detector) — not for every new file.

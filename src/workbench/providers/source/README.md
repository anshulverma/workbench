# providers/source

**Purpose:** SourceAdapter implementations behind the `SourceAdapter` base
interface — the inbound integrations that produce raw items.

**What belongs here:** the `SourceAdapter` base interface (`base.py`) and
concrete adapters — `github.py`, `gmail.py`, `gcalendar.py`, `gchat.py`.

**What does NOT belong here:** other provider families, shared external
credentials/sessions (those live in `providers/connection/`), ingestion
scheduling or the queue worker (`pipeline/`), or adapter cursor persistence
(`storage/adapter_state.py`).

**Update this README when** you add a new KIND of code here (a new source
adapter) — not for every new file.

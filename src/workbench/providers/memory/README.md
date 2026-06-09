# providers/memory

**Purpose:** MemoryLayer providers (`NoopMemoryLayer` default, `HttpMemoryLayer`); was `workbench/memory/`.

**What belongs here:** the `MemoryLayer` base interface (`base.py`) and its concrete
implementations — `noop.py` (the default no-op layer) and `http.py` (the HTTP-backed
memory service client).

**What does NOT belong here:** other provider families, pipeline stages, or the memory
*service* distribution (`src/memory/`, package `memory`, run as `memory.main:app`), which
is a separate package.

**Update this README when** you add a new KIND of code here (a new MemoryLayer
implementation is just a new file; update only if the family's purpose changes).

# ADR 0004: Zep as a Parallel Knowledge Layer, Not a Storage Replacement

Zep runs alongside the primary storage backend (SQLite/XDB) as an additive intelligence layer. SQLite remains the source of truth for all structured data (items, triage cards, jobs, filter rules). Zep receives a copy of triage interactions, entity data, and pipeline decisions for knowledge extraction and graph construction. The pipeline queries Zep for preferences, entity knowledge, and relationship context, falling back gracefully if Zep is unavailable.

We chose this over making Zep the primary store (Approach B) because: (1) Zep as a single point of failure would break the core triage loop on any Zep outage; (2) the dual-write adds minor complexity but keeps the system resilient; (3) Zep's knowledge graph is always rebuildable from the interaction log in SQLite, so data durability concerns are eliminated.

**Consequence:** The pipeline engine holds both `stores` (repositories) and `memory` (MemoryLayer). Dual-writes happen at the pipeline level with no transaction coupling. If Zep fails, the pipeline runs with degraded intelligence (explicit filter rules only) but doesn't break.

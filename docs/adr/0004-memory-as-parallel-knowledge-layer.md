# ADR 0004: Memory Service as a Parallel Knowledge Layer, Not a Storage Replacement

The memory service (Graphiti + Neo4j) runs alongside the primary storage backend (PostgreSQL) as an additive intelligence layer. PostgreSQL remains the source of truth for all structured data (items, triage cards, jobs, filter rules). The memory service receives a copy of triage interactions for knowledge extraction and graph construction. The pipeline queries the memory service for preferences and relationship context, falling back gracefully if the memory service is unavailable.

We chose this over making the memory service the primary store (Approach B) because: (1) the memory service as a single point of failure would break the core triage loop on any outage; (2) the dual-write adds minor complexity but keeps the system resilient; (3) the memory service's knowledge graph is always rebuildable from the interaction log in PostgreSQL, so data durability concerns are eliminated.

**Consequence:** The pipeline engine holds both `stores` (repositories) and `memory` (MemoryLayer). Dual-writes happen at the pipeline level with no transaction coupling. If the memory service fails, the pipeline runs with degraded intelligence (explicit filter rules only) but doesn't break. See also ADR 0009 for why the memory layer is a separate HTTP service.

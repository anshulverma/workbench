# 0065 — Ingestion pipeline is a Routing DAG with single-path execution

**Status:** Accepted

**Context:** Different source types need different paths (a diff needs no task
enrichment), branches should be able to converge on shared stages and diverge again, and
the pipeline must be user-authored and visualizable. A linear list can't express
convergence or conditional routing; a fully concurrent DAG adds join/concurrency machinery
unjustified for a single-user feed.

**Decision:** Model the pipeline as a directed acyclic graph of typed nodes connected by
edges carrying route predicates. Each item traverses exactly one deterministic path
(single-path execution, one node at a time, no concurrency). The node/edge model is
retained so parallel fan-out/fan-in can be added later without a rewrite.

**Alternatives:** Source-scoped linear list (rejected: no convergence or conditional
routing). Full concurrent DAG (rejected now: join semantics, concurrency caps, and
partial-failure handling are over-engineering for a single-user tool).

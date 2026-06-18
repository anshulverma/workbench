# ADR 0062 — Item lineage via materialized path, not ltree/closure

Status: Accepted
Date: 2026-06-18

## Context

Items form a lineage tree (ingested source artifact → extracted items → actions,
addressed as `#123`, `#123.1`, `#123.1.2`). We need stable, navigable
hierarchical identity on top of the existing integer surrogate PK.

## Decision

Encode lineage with a denormalized materialized `path TEXT` column (e.g.
`"123.1.2"`) plus a per-parent `seq SMALLINT`, keeping the integer autoincrement
PK and the existing `parent_item_id` FK. Subtree queries use indexed
`path LIKE '123.%'`; point lookups use a unique index on `path`.

## Alternatives rejected

- **Path string as primary key** — reverses the recent UUID→BIGINT migration and
  breaks every integer FK. Too costly.
- **Postgres `ltree` / closure table** — built for large, deep, hot trees and for
  reparenting. Here trees are shallow and small, dominant access is point-lookup
  and one-level children, and identity is immutable (no reparenting), which
  removes the closure table's main advantage. `ltree` also adds a Postgres
  extension dependency. Can be layered on later as a derived index if the
  workload grows into it.

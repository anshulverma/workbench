# ADR 0024: Diff Code Fetched Lazily in the Diff Enricher, Never in the Source Adapter or `raw_text`

The actual diff code (per-file hunks) is fetched **lazily** by the Meta `DiffEnricher` during deep-mode Enrichment, not by the Phabricator Source Adapter's `poll()`. `poll()` stays metadata-only and fetch-only. The fetched diff is produced as Enrichment context and is **never** written to `RawItem.raw_text`.

We chose lazy enricher fetch over eager fetch in `poll()` because `meta phabricator.diff list` returns up to 50 diffs per poll and most never survive the Ingestion Queue to reach Enrichment — fetching every diff's full body up front is wasteful and violates the Source Adapter "fetch only, no semantic work" contract. We keep the diff out of `raw_text` because foundational extraction truncates `raw_text[:10000]`, which would silently corrupt a diff, and because adding a structured diff field to `RawItem` would change a foundational domain model for a Meta-specific concern.

**Consequence:** Enrichment depth (shallow/deep) and budget controls gate the cost of `meta phabricator.diff get`. On fetch timeout, nonzero exit, or missing THRIFT_TLS cert, the enricher degrades to shallow context (metadata + entity_refs) and never raises. No `RawItem`/`TriageCard` column schema change is required. The diff-specific fetch logic stays entirely in `workbench-meta`.

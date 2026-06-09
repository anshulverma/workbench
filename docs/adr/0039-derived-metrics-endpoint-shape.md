# ADR 0039: Derived Metrics Ship as a `metrics` Block on /api/stats/overview Plus a Generic /api/stats/timeseries

**Status:** Accepted — 2026-06-08

**Context.** The redesigned Overview and Triage pages need scalar KPIs and time-series signals (signal velocity, throughput) that don't exist in the current stats API.

**Decision.** Add a **`metrics` block** of scalars to `GET /api/stats/overview`, and a generic **`GET /api/stats/timeseries?metric={signal_velocity|throughput}&window=&bucket={hour|day}`** that returns the **full bucket array** (`count:0` for empty buckets, never omitted — mirroring the existing ingestion-timeseries shape). No caching. Scalars return `null` (rendered "n/a") when a denominator is 0 or history is insufficient; percent deltas are `null` when the prior window is empty.

**Consequences / Alternatives.** A single generic timeseries endpoint parameterized by `metric` is preferred over one endpoint per signal, matching the established ingestion-timeseries contract and keeping the client charting uniform. Never omitting empty buckets means clients render continuous axes without gap-filling. Honesty of the underlying derivations is governed by ADR 0040; metrics with no honest source (active_sessions, unread pings, blocked tasks) are dropped, not faked.

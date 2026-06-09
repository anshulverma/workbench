# ADR 0038: A Centralized, Token-Driven chart-theme Module Replaces Hardcoded DONUT_COLORS

**Status:** Accepted — 2026-06-08

**Context.** Chart colors were hardcoded per-page (`DONUT_COLORS`), so charts drifted from the theme tokens and could not follow light/dark or the brand palette.

**Decision.** Introduce a single `src/lib/chart-theme.ts` exporting token-driven `CHART_COLORS` (orange primary + cyan tertiary + semantic red/amber/blue/green) plus shared Recharts defaults (grid / axis / tooltip / legend), imported by every chart page. It **replaces the hardcoded `DONUT_COLORS`**. Degenerate Sparkline states are standardized here too (empty → flat baseline + "—"; single point → dot).

**Consequences / Alternatives.** All charts now share one palette and automatically track the theme tokens (ADR 0033), so a token change propagates everywhere. We rejected leaving per-page color arrays (the source of the drift) and rejected a heavier charting abstraction — a plain exported constants/defaults module is enough and keeps Recharts usage direct.

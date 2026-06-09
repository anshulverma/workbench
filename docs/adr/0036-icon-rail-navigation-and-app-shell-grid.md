# ADR 0036: Icon-Rail Navigation (64px, lucide, Radix Tooltips) Over a CSS-Grid App Shell

**Status:** Accepted — 2026-06-08

**Context.** The current `AppShell` is a flex layout with a labeled sidebar. The redesign calls for a compact icon rail and a sticky top app bar, while preserving HashRouter (ADR 0018) and the accessibility guarantees the test suite asserts.

**Decision.** Replace the flex shell with a CSS grid `grid-cols-[64px_1fr] grid-rows-[auto_1fr]`: a full-height **64px icon rail** (`row-span-2`), a sticky top app bar in row 1 / col 2, and a single scrollable `<main>`. The rail uses lucide 20px icons, with the active item marked by a **2px orange left bar + orange icon**. Each link keeps `NavLink` (HashRouter-safe), carries an `aria-label`, **preserves `aria-current="page"`** (asserted by `a11y.test`), and shows its label via a Radix tooltip (`@radix-ui/react-tooltip`). Below 768px the rail collapses to a drawer/hamburger.

**Consequences / Alternatives.** Adds `@radix-ui/react-tooltip` as a dependency. Labels are no longer always-visible, so the tooltip + `aria-label` pair is load-bearing for both sighted and AT users — this is why we did not drop labels entirely. We chose CSS grid over nested flex because the full-height rail + sticky-bar + single-scroll-region layout is expressed directly by grid tracks and avoids overflow/sticky bugs.

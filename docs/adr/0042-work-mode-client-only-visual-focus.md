# ADR 0042: Work Mode Is a Client-Only Visual Focus Preference and Does Not Suppress Notifications

**Status:** Accepted — 2026-06-08

**Context.** "Work Mode / Terminal Focus" lets the user collapse the dashboard to only the most critical active work. A natural-seeming extension would be to also mute messenger notifications while focused.

**Decision.** Work Mode is a **client-only `localStorage` view preference**. When on, it filters the feed/Overview to the top active P0 "vector", hides non-critical widgets, and dims chrome; it syncs across tabs via the `storage` event and shows a focused empty state when nothing is active. It does **not** mute notifications.

**Consequences / Alternatives.** Keeping it client-only means no backend changes and no risk to delivery semantics. We explicitly rejected having Work Mode suppress notifications: the messenger is a notification surface (ADR 0001), and quiet-hours/suppression is out of scope for v1. This honors ADR 0001 — backend notification suppression remains a future option only if Work Mode should ever mute.

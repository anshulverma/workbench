# ADR 0034: Default Theme Is System/Auto With Both Light and Dark, Despite a Dark-Only Design

**Status:** Accepted — 2026-06-08

**Context.** The shipped design references are dark-first (`stitch-design.html`), and `index.html` currently hardcodes `class="dark"`. A light reference (`stitch-design-light.html`) also exists. The question is whether to ship dark-only or honor the OS preference.

**Decision.** Ship **light + dark + auto** with `defaultTheme="system"`. Mount `next-themes` `ThemeProvider` (`attribute="class"`, `enableSystem`) in `main.tsx` and **remove the hardcoded `class="dark"`** from `index.html`. The light palette is grounded in `stitch-design-light.html`; the brand orange stays the primary/ring in both themes. A light/dark/auto toggle lives in the top app bar.

**Consequences / Alternatives.** Both palettes must be maintained and both must satisfy the contrast contract (ADR 0046), roughly doubling token-tuning work versus dark-only. We chose this because respecting the OS preference is the accessible default and a toggle is cheap; shipping dark-only would have been less work but would ignore users in light environments. The full token surface ladder (ADR 0033) is authored per-theme.

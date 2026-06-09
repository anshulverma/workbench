# ADR 0046: Contrast Contract — Orange-on-Dark Usage Rules

**Status:** Accepted — 2026-06-08

**Context.** The brand orange `#ff6a2b` is used widely, but it only passes WCAG AA as small text on the darkest surfaces; it fails on elevated surfaces and fails badly as white-on-orange. Without explicit rules the redesign would ship inaccessible text.

**Decision.** Adopt a fixed contrast contract for orange on dark: `#ff6a2b` may be used as small text **only on base surfaces ≤ `#2a2a2d`** (AA: `#0e0e11` 6.74:1, `#1b1b1e` ~6:1). On **orange fills**, text uses **near-black `#0e0e11`** (white-on-orange is 2.86:1 — disallowed). On **elevated/popover/tooltip surfaces** (≥ ~`#303038`), use `on-surface` text or the lighter peach orange `#ffb59a` instead of `#ff6a2b`. The orange focus ring is a 2px outline with 2px offset; the `.prio-*` classes stay AA-tuned.

**Consequences / Alternatives.** This is a hard constraint on the surface ladder of ADR 0033 and applies to both themes (ADR 0034): a token's allowed text colors depend on which surface tier it sits on. We rejected lightening the brand orange to pass AA everywhere (it would no longer match the design) and rejected white-on-orange buttons (fail AA) — hence the near-black foreground on orange fills.

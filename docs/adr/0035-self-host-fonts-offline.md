# ADR 0035: Self-Host Fonts Offline via @fontsource-variable (No CDN)

**Status:** Accepted — 2026-06-08

**Context.** The design uses Space Grotesk (display), Hanken Grotesk (sans), and JetBrains Mono (data). Workbench is an offline-deployable single-user tool; the decision log forbids external CDNs.

**Decision.** Self-host all three offline via `@fontsource-variable/{space-grotesk,hanken-grotesk,jetbrains-mono}` (latin subset; weights 400/500/600/700 covered by the variable axis), imported in `index.css` and bundled by Vite. No Google Fonts CDN. Map them in `@theme inline` (`--font-sans`, `--font-display`, `--font-mono`) with `font-display: swap`.

**Consequences / Alternatives.** The three fonts are SIL OFL 1.1, so they are OSS-redistributable — a deliberate license check, not an accident. Bundle size grows by the three variable font files (acceptable for a self-hosted tool). We rejected Google Fonts / any CDN (breaks the offline-deploy requirement) and rejected static per-weight font files (the variable axis covers the weights we need in one file each).

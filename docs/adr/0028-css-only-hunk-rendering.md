# ADR 0028: CSS-Only Curated-Hunk Rendering in the UI (No Syntax-Highlight or Diff Library)

The Triage Card Detail View renders curated Diff Hunks with CSS-only `+`/`-` line coloring inside `<pre>`, driven by server-provided structured hunk lines. No syntax-highlighting or diff-viewer library (shiki, prism, react-syntax-highlighter, monaco) is added to the UI.

We chose CSS-only rendering because the detail view is a quick-triage surface, not a Phabricator clone — per-token syntax coloring is not needed to decide how to triage, the curated hunks are already small, and a heavy WASM/highlighter dependency worsens the already-painful npm-blocked build (which uses a standalone Node v20 in `/tmp`). The trade-off is losing per-token syntax coloring, which is acceptable for triage and reversible later.

**Consequence:** `ui/package.json` gains no highlighting dependency. The diff renderer is a small first-party `DiffHunks` component mapping a line's change type (`+`/`-`/context) to a background CSS class. Annotations render as inline severity badges; hunks collapse per file. For the real review action the card links out to Phabricator.

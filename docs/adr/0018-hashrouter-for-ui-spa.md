# ADR 0018: HashRouter for the `/ui` SPA

The Management Dashboard uses react-router's `HashRouter`, so all client routes live under `/ui/#/...` and the server only ever serves `/ui/index.html`. The SPA is mounted via Starlette `StaticFiles(directory=ui_dir, html=True)`, whose `html=True` serves `index.html` only for an exact directory match — a hard GET to `/ui/sources` resolves to a non-existent path and returns 404.

We chose `HashRouter` over `BrowserRouter basename="/ui"` because BrowserRouter works for in-app navigation but breaks on hard refresh, deep-link, or bookmark of any subpath (404 from StaticFiles, since there is no SPA catch-all). We chose it over adding a FastAPI catch-all route that rewrites unknown `/ui/*` paths to `index.html` because that adds server routing complexity for a single-user internal tool and the project explicitly opted for "no server catch-all."

The trade-off is the cosmetically uglier `#/` in URLs and that hash fragments are client-only (not sent to the server, which is fine here). 

**Consequence:** Zero server changes are needed for routing; the existing `tsc && vite build` → `ui/dist` → `/ui` mount is unchanged. Deep-links and hard refreshes work because the server always serves the same `index.html`.

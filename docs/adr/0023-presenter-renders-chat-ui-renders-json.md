# ADR 0023: Presenter Renders Chat Server-Side; the UI Renders Client-Side from Structured JSON

One structured Card Content must reach two surfaces — Google Chat and the dashboard. The `CardPresenter` renders the **chat** surface server-side (it builds a transport-neutral `CardMessage` that `GoogleChatMessenger` translates to cardsV2 with threaded hunks). The **UI** gets no presenter method: the detail API serves the raw structured `card_content` JSON and the React app renders it client-side (expand/collapse, CSS-only diff coloring, Phabricator links).

We chose this split over (a) the server rendering both surfaces — which couples the server to UI layout and defeats the interactive, expandable quick-triage experience; (b) the UI rendering the chat surface too — impossible, since Google Chat needs a server-built cardsV2 payload posted via the bot. Chat is a push surface that must be built where the post happens; the dashboard is a pull surface that owns its own interactivity.

**Consequence:** `CardPresenter` is a pure, deterministic function (no LLM, no Memory Layer) producing a `CardMessage`. The detail API returns the full `TriageCard` including `card_content.sections`. The two surfaces evolve independently — chat density caps live in the presenter/messenger, UI density caps live in the client.

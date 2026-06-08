# ADR 0027: Triage Interaction Stays Numbered Text Replies Under cardsV2 (Buttons Are Display-Only Links)

Under the new cardsV2 cards, the triage interaction model is unchanged: the user replies by typing a number or free text, captured by `poll_responses` reading the card's thread. cardsV2 cards carry **link buttons only** (Open in dashboard, View in Phabricator) — not interactive triage buttons.

We chose this over full button-based triage because cardsV2 interactive buttons fire events to a webhook / Pub/Sub endpoint, and Workbench's response model is thread polling, not event ingress — adopting buttons would require standing up an interactive-event listener and would bypass the LLM free-text interpretation path that is core to triage. Hybrid buttons that merely post equivalent text add complexity for marginal value on a single-user tool.

**Consequence:** No Chat event-ingress infrastructure is built for v1. The stored `message_id` plus a client-generated `threadKey` drive response recovery; replies to the parent card or to any threaded hunk land in the same thread and are captured. Interactive tap-to-triage remains a clean future extension gated on building an event ingress. This preserves the interaction model established in ADR 0001 (messenger as the primary interactive triage surface).

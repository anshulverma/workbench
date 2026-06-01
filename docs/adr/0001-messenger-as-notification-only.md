# ADR 0001: Messenger as Bidirectional Triage Surface (Superseded)

~~Original decision: Messenger is send-only.~~ Superseded — the configured messenger is now the primary interactive triage surface.

The original reasoning was that response matching across platforms with different threading models is fragile. That no longer applies: the pluggable messenger system handles one messenger at a time, eliminating multi-platform concerns.

The bot uses **text-based replies** (user types "1", "2", "3") as the primary input method. Triage cards are sent **one at a time, sequentially** to eliminate response-matching ambiguity. The API and `workbench triage` CLI remain available as alternative input methods.

**Consequence:** The Messenger interface has `send_card()` and `poll_responses()`. The scheduler manages a triage queue, sending one card at a time and waiting for a response before advancing.

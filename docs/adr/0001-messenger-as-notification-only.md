# ADR 0001: Google Chat as Bidirectional Triage Surface (Superseded)

~~Original decision: Messenger is send-only.~~ Superseded — Google Chat is now the primary interactive triage surface.

The original reasoning was that response matching across platforms (WhatsApp/Discord) with different threading models is fragile. That no longer applies: we narrowed to Google Chat only, eliminating multi-platform concerns.

Google Chat interactive card buttons (postback callbacks) require the PHP/WIB pipeline in WWW, which conflicts with our goal of keeping all code outside fbcode. Instead, the bot uses **text-based replies** (user types "1", "2", "3") with **openLink buttons as fallback** (URL hits the devserver API directly). Triage cards are sent **one at a time, sequentially** to eliminate response-matching ambiguity. The API and `/workbench:triage` CLI remain available if Google Chat is down.

**Consequence:** The Messenger interface has `send()` and `poll_responses()`. The scheduler manages a triage queue, sending one card at a time and waiting for a response before advancing. The `google_api.py` module (from `fbcode/claude-templates`) provides send and poll capabilities without fbcode dependencies.

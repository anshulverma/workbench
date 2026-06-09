# providers/messenger

**Purpose:** Messenger implementations behind the `Messenger` base interface —
the user-facing surface for triage cards and responses.

**What belongs here:** the `Messenger` base interface (`base.py`) and concrete
implementations — `console.py` (`ConsoleMessenger`) and `google_chat.py`
(`GoogleChatMessenger`).

**What does NOT belong here:** other provider families, card content generation
or presentation (`pipeline/`), or domain card models (`domain/`).

**Update this README when** you add a new KIND of code here (a new messenger
backend) — not for every new file.

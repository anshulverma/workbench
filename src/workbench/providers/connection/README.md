# providers/connection

**Purpose:** Connection implementations behind the `Connection` base interface —
shared external credentials/sessions reused across provider families (e.g.
Google auth shared by the gmail/gcalendar/gchat source and enrichment
providers).

**What belongs here:** the `Connection` base interface (`base.py`) and concrete
implementations — `google.py` (`GoogleConnection`).

**What does NOT belong here:** the source/enrichment providers that consume a
connection (those live in their own subfolders), other provider families, or
credential persistence.

**Update this README when** you add a new KIND of code here (a new shared
connection) — not for every new file.

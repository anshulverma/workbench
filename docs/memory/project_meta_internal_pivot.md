---
name: meta-internal-pivot
description: Workbench pivoted from open-source to Meta-internal only tool for personal work use
metadata:
  type: project
---

Workbench is now Meta-internal only, not open source. Single-user tool for Anshul's work.

**Why:** The user only needs this for internal Meta work — no external use case.

**How to apply:** All design decisions should target Meta infrastructure. No need for portable/generic solutions. Remove multi-tenant complexity — single user, single workspace is fine.

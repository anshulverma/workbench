---
name: tech-decisions
description: "Concrete technology choices for Workbench — storage, LLM, messaging, deployment, sources, memory"
metadata:
  type: project
---

Decided as of 2026-05-27:

- **Storage**: Pluggable via repository pattern. SQLite for Phase 1, XDB (MySQL) and PostgreSQL as later options. [[meta-internal-pivot]]
- **Memory**: Zep knowledge graph as parallel knowledge layer. Dual-write: SQLite is source of truth, Zep extracts knowledge. MemoryLayer interface with ZepMemoryLayer and NoopMemoryLayer implementations.
- **LLM**: Claude API (Anthropic) via Plugboard proxy. Single model (Sonnet) to start.
- **Messaging**: Google Chat only. No WhatsApp/Discord/Slack.
- **Sources**: Phase 1: Phabricator (Conduit API) + Gmail (Google API proxy). Phase 2: Tasks, Workplace, Calendar, SEVs, Oncall.
- **Deployment**: All services via Podman Compose on devgpu (workbench + zep + zep-postgres). Managed by systemd user service. `network_mode: host` for internal network access. `with-proxy` for pulling external container images.
- **Auth**: Static bearer token (`WORKBENCH_API_TOKEN`). No user management.
- **Plugin architecture**: Claude Code plugin is a thin HTTP client only — all reads and writes go through the FastAPI server API.
- **Google Chat bot**: "Jarvis" — WIB no-code bot, ID `31903689702586240`, space `AAQA-RI-cA4`. Text-based replies + openLink fallback. One triage card at a time. Uses `google_api.py` from `fbcode/claude-templates` with `as_bot=true`.

**Why:** Meta-internal tool, single user, needs shared state across devservers/ODs. Single data path through the server keeps things simple. Zep adds intelligence without being a single point of failure.

**How to apply:** Spec and implementation should reflect these choices. Repository pattern for storage, MemoryLayer for Zep. Plugin never imports storage code — it only knows the server URL.

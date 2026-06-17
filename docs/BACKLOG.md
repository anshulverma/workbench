# Backlog

Future work, not yet planned into ADRs/specs. Captured for "eventually" — promote
to `docs/specs/` + `docs/adr/` when picked up.

## 1. Transparent LLM call batching

Batch LLM inference instead of firing many small, independent calls. The batching
should be **fully transparent to callers** — built into the LLM infra (the LLM
provider layer), so call sites stay unaware.

Design sketch:
- Accumulate requests and flush on an interval (e.g. 1 batch / 10s) and/or a size
  threshold.
- Each batch is structured (JSON) with layered context, sent once:
  1. **Stable "me" context** — who I am, my preferences. Cache-friendly prefix.
  2. **Fresher "env" / "daily" context** — slower-moving but refreshed periodically.
  3. **The batched requests**, recorded in order, each with a **unique request ID**.
- Output is JSON keyed by request ID so responses can be **un-batched** and routed
  back to the right caller.
- Caller-facing API is unchanged: submit a request, await its response; the
  batching, flushing, and de-batching happen underneath.

Why: cuts per-call overhead and lets the shared "me"/context prefix be reused
(and cached) across many requests, which also sets up #2.

## 2. Auto-triage accuracy tracking + labeled dataset

Premise of #1: an ever-evolving "context about me" should make the LLM
progressively better at auto-triaging items. To measure and exploit that, record
two things about how the LLM infra performs:

- **Auto-triage accuracy / rate** — how often the LLM's triage decision matches
  what I'd actually want (its rate of correct auto-triage over time).
- **Labeled dataset** — for each interaction, capture `(request, response,
  my_feedback_on_that_response)`. This becomes a training/eval dataset down the
  line (fine-tuning or eval harness for the triage models/prompts).

Why: closes the loop — feedback both scores the system and accrues into reusable
training/eval data as the context grows.

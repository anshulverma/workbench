# Ralph Progress — Plugboard Call Reduction & Observability (master T275074754)

One subtask per iteration. Pick the lowest-numbered incomplete subtask whose deps are complete.

| Subtask | Plan task | Deps | Status | sl commit | Notes |
|---------|-----------|------|--------|-----------|-------|
| S1 T275074837 auto_drop config gate | T1 | — | DONE | (pending) | 21 pipeline tests pass; ruff unavailable in env |
| S2 T275074853 main-app observability | T2-3 | — | DONE | (pending) | shim + plugboard_* metrics + sink wiring; 8 llm/scorer + 7 metrics/shim tests pass |
| S6 T275074867 memory-service observability | T7 | — | todo | — | |
| S3 T275074882 periodic usage summary | T4 | S2 | todo | — | |
| S4 T275074896 batch score_relevance | T5 | S2 | todo | — | |
| S5 T275074915 batch score_urgency | T6 | S2 | todo | — | |
| S7 T275074941 ops wiring | T8 | S2,S4,S5,S6 | todo | — | ready-for-human (author only) |

## Log
- iter 2: validated S1 (on disk, all wiring present). S2 done — created providers/_plugboard.py (PlugboardCallRecord + record_plugboard_call); added on_plugboard_call to AnthropicLLM + LLMQueueScorer ProviderConfig + self._sink; routed _call_with_retry (with item_count param for S4), interpret_triage_response, and score_urgency through the shim; added plugboard_* metric family (calls/errors/tokens{direction}/items + call_seconds buckets→60s) to metrics.py; wired _plugboard_sink in main.py lifespan onto app.state.llm._inner and queue_scorer, gated on config.metrics.enabled. Tests: test_plugboard_shim.py (3) + test_metrics plugboard test + test_anthropic_llm/test_queue_scorer/test_queue_worker (8) + test_pipeline (21) all green.
- iter 1: S1 done — `pipeline.record_drop_decisions` (default False) gates the auto_drop `record_pipeline_decision` call; `job.items_dropped` stays outside the gate; wired `triage_expiry_days` + `record_drop_decisions` in main.py lifespan. 2 new tests + 21 test_pipeline.py pass. Note: `ruff` not installed in venv, lint not runnable here.

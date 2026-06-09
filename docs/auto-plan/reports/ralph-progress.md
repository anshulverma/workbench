# Ralph Progress — Plugboard Call Reduction & Observability (master T275074754)

One subtask per iteration. Pick the lowest-numbered incomplete subtask whose deps are complete.

| Subtask | Plan task | Deps | Status | sl commit | Notes |
|---------|-----------|------|--------|-----------|-------|
| S1 T275074837 auto_drop config gate | T1 | — | DONE | (pending) | 21 pipeline tests pass; ruff unavailable in env |
| S2 T275074853 main-app observability | T2-3 | — | todo | — | |
| S6 T275074867 memory-service observability | T7 | — | todo | — | |
| S3 T275074882 periodic usage summary | T4 | S2 | todo | — | |
| S4 T275074896 batch score_relevance | T5 | S2 | todo | — | |
| S5 T275074915 batch score_urgency | T6 | S2 | todo | — | |
| S7 T275074941 ops wiring | T8 | S2,S4,S5,S6 | todo | — | ready-for-human (author only) |

## Log
- iter 1: S1 done — `pipeline.record_drop_decisions` (default False) gates the auto_drop `record_pipeline_decision` call; `job.items_dropped` stays outside the gate; wired `triage_expiry_days` + `record_drop_decisions` in main.py lifespan. 2 new tests + 21 test_pipeline.py pass. Note: `ruff` not installed in venv, lint not runnable here.

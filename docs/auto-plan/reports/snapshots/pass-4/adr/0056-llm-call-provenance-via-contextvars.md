# 0056 — LLM call provenance via contextvars

**Status:** Accepted (2026-06-17)

## Context

Full-fidelity LLM usage tracking needs each call labelled with `origin`, `purpose`, and `stage`. The single instrumentation seam (`record_plugboard_call`) cannot derive these — `client` is a constant per provider (`main_llm`/`queue_scorer`). The `LLMProvider` ABC has no per-call context parameter.

## Decision

Carry provenance in a task-local `ContextVar[LLMCallContext]` set by an `llm_call_context(origin, purpose, stage)` context manager entered at each pipeline stage; `record_plugboard_call` reads the current value when building a record.

## Alternatives

- Thread an `LLMCallContext` parameter through every `LLMProvider` method and call site — explicit/greppable but large blast radius across the interface, instrumented wrapper, and all callers.
- Infer stage from the `client` constant — insufficient (can't distinguish extract/filter/triage/aggregate).

## Consequences

Zero signature churn; correct under concurrent pipeline workers (contextvars are task-local). Provenance flows implicitly, so a missing context manager yields `None` provenance (acceptable; recorded as unknown). Hard to reverse once call sites depend on the ambient context.

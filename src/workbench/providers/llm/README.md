# providers/llm

**Purpose:** LLMProvider implementations behind the `LLMProvider` base interface.

**What belongs here:** the `LLMProvider` base interface (`base.py`), concrete
implementations (`anthropic.py` — `AnthropicLLM`), and `plugboard.py` — the
Plugboard transport shim/record used as the LLM-gateway call sink (metrics-free;
instrumentation/metrics are layered in `telemetry/`).

**What does NOT belong here:** other provider families, the Provider Registry
(one level up in `providers/`), metrics or instrumentation wrappers
(`telemetry/`), or pipeline stages that consume the LLM (`pipeline/`).

**Update this README when** you add a new KIND of code here (a new LLM backend
or transport) — not for every new file.

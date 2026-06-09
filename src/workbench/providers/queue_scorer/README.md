# providers/queue_scorer

**Purpose:** QueueScorer implementations behind the `QueueScorer` base interface
— priority/urgency scoring for the ingestion queue.

**What belongs here:** the `QueueScorer` base interface (`base.py`) and concrete
implementations — `llm.py` (`LLMQueueScorer`).

**What does NOT belong here:** other provider families, the queue worker or
scheduler (`pipeline/`), or queue-entry persistence (`storage/`).

**Update this README when** you add a new KIND of code here (a new scoring
strategy) — not for every new file.

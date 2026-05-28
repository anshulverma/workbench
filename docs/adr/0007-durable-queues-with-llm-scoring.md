# ADR 0007: Durable Queues with LLM-Based Priority Scoring

All content entering Workbench flows through two durable, priority-ordered queues persisted in PostgreSQL:

**Ingestion queue** (input): Source adapters and `/api/process` enqueue raw content into the `ingestion_queue` table instead of running the pipeline directly. Items are dedup-checked against ProcessedStore at enqueue time; manual submissions bypass dedup. Each item gets an inline LLM urgency score at enqueue time before the row is inserted. An in-process async queue worker (asyncio task with `asyncio.Semaphore`, default concurrency 2) dequeues items via `SELECT ... FOR UPDATE SKIP LOCKED` ordered by urgency score and runs the pipeline. Failed items retry with exponential backoff (`2^attempt * base_delay`, default base 5s) up to max_attempts (default 3), then become dead-letter entries for manual inspection. Dead letters are inspectable via `GET /api/queue/dead-letter`, retryable via `POST /api/queue/dead-letter/{id}/retry`, and purgeable via `DELETE /api/queue/dead-letter/{id}` — no auto-purge.

**Ingestion queue schema:**
```
ingestion_queue:
  id              TEXT PRIMARY KEY
  raw_content     TEXT NOT NULL
  source_type     TEXT NOT NULL
  source_id       TEXT              -- nullable for manual submissions (bypass dedup)
  urgency_signals JSONB NOT NULL DEFAULT '{}'
  urgency_score   INT NOT NULL      -- set inline by queue scorer at enqueue time
  job_id          TEXT NOT NULL      -- FK to jobs (created eagerly, starts as QUEUED)
  status          TEXT NOT NULL DEFAULT 'queued'
                                    -- queued → processing → completed / failed / dead_letter
  attempt         INT NOT NULL DEFAULT 0
  max_attempts    INT NOT NULL DEFAULT 3
  next_retry_at   TIMESTAMP         -- null when not in retry backoff
  error           TEXT              -- last error message
  created_at      TIMESTAMP NOT NULL
  updated_at      TIMESTAMP NOT NULL
```

**Triage queue** (output): Implemented as columns on the `triage_cards` table (not a separate table). Triage cards are ordered by relevance score (highest first) and sent one at a time to Google Chat. Queue status lifecycle: `queued → sent → responded / expired`. Daily cap (default 20) limits triage fatigue. Cards older than a configurable expiry (default 7 days) auto-include at P3. Queue state (including `bot_message_id` per card) is persisted — survives server restarts.

**Additional columns on `triage_cards`:**
- `relevance_score` (int) — for priority ordering
- `confidence_score` (int) — for audit/debugging
- `expires_at` (timestamp) — created_at + expiry_days
- `daily_sequence` (int, nullable) — position within today's batch
- `status` (text) — queue state: `queued`, `sent`, `responded`, `expired`
- `bot_message_id` (text, nullable) — Google Chat message ID for response polling recovery

Priority for the ingestion queue is determined by a dedicated `QueueScorer` interface (`async def score_urgency(raw_text, urgency_signals) -> int`), separate from `LLMProvider`. The default implementation (`LLMQueueScorer`) uses a cheap model (Haiku) configured under `queue.scorer:` in YAML config. The scorer evaluates raw content + urgency signals (structured metadata from source adapters) and returns an urgency score (0-100). Scoring happens inline at enqueue time — items are always correctly ordered when inserted. The scorer determines dequeue ordering only — it never auto-drops items (that's the noise filter's job after full extraction). In Phase 1b+, Zep preference context is injected for learned priority boosting.

We chose LLM scoring over static source-type priority because a static ranking ("diffs before emails") is too blunt — an email from your manager about a deadline matters more than a CI bot diff notification. Urgency depends on content and context, not just source type.

We chose durable queues over the original inline processing because: (1) source polling can produce bursts of 40+ items — without a queue, the pipeline blocks on sequential LLM calls for minutes; (2) in-memory queue state (like `_last_bot_message_id`) is lost on server restart, causing duplicate triage cards or missed responses; (3) the queue provides natural backpressure, rate limiting, retry with backoff, and dead-letter inspection.

We chose an in-process async worker over a separate worker process because this is a single-user tool on a devgpu — the API handles minimal traffic, and all pipeline code is fully async (AsyncAnthropic, asyncpg, `asyncio.create_subprocess_exec` for external calls). The semaphore naturally limits pipeline load. If the event loop ever becomes a bottleneck, splitting to a separate process is straightforward since the queue is durable in PostgreSQL.

The ingestion queue is an internal mechanism. API clients interact only with pipeline jobs (created eagerly at enqueue time, status: `queued → pending → running → completed/failed`). This preserves the existing API contract from ADR 0003.

**Consequence:** Two new tables (`ingestion_queue`, plus queue columns on `triage_cards`). New store interface `IngestionQueueStore`. New `QueueScorer` ABC and `LLMQueueScorer` default implementation. `RawItem` gains an `urgency_signals: dict[str, Any]` field. `JobStatus` gains a `QUEUED` value. The pipeline engine no longer processes content directly — it receives dequeued items from the worker. Startup includes a recovery step: items stuck in `processing` from an unclean shutdown are re-enqueued. All blocking subprocess calls in providers use `asyncio.create_subprocess_exec`.

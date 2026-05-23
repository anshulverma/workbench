# Step 7: Processing Pipeline

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [05-provider-interfaces.md](05-provider-interfaces.md), [06-provider-implementations.md](06-provider-implementations.md)

## Goal

The core pipeline engine that orchestrates all six stages: source adapter → LLM extraction → noise filter → context enrichment → triage card generation → messenger delivery and response processing.

## Files to Create

```
server/
  pipeline/
    __init__.py
    engine.py              -- pipeline orchestration
    extraction.py          -- LLM extraction stage
    filter.py              -- adaptive noise filter
    enrichment.py          -- context enrichment with budget
    triage.py              -- triage card generation and response processing
    preferences.py         -- preference synthesis (incremental digest)
```

## Pipeline Engine (engine.py)

The main orchestrator. Two entry points:

### `process_raw_input(workspace_id, raw_text, source_type, source_label)`

Called by `/process` endpoint and source adapter polling. Runs the full pipeline for a single input.

### `poll_sources(workspace_id)`

Called by the scheduler. For each enabled source in the workspace:
1. Get the source adapter from the registry
2. Call `adapter.poll(config, since=last_poll_time)`
3. For each raw item, check dedup (`processed` table)
4. Run `process_raw_input()` for each new item
5. Mark items as processed

### Pipeline stages (called sequentially per item):

```python
async def process_item(workspace_id, raw_item):
    # Stage 2: LLM extraction
    extracted = await llm.extract(raw_item.raw_text, raw_item.source_type)

    # Stage 3: Noise filter
    preferences = await db.get_preferences(workspace_id)
    rules = await db.get_filter_rules(workspace_id)
    email_rules = await db.get_email_filters(workspace_id, raw_item.account) if raw_item.source_type == "email" else []
    relevance, confidence = await llm.score_relevance(extracted, preferences, rules + email_rules)

    if relevance >= thresholds.include and confidence >= thresholds.confidence:
        action = "auto_include"
    elif relevance < thresholds.drop and confidence >= thresholds.confidence:
        action = "auto_drop"
    else:
        action = "triage"

    # Stage 4: Context enrichment (skip for auto_drop)
    enrichment = EnrichmentResult(context={}, calls_made=0, time_ms=0)
    if action != "auto_drop":
        enricher = registry.get_enricher(workspace_config.enricher)
        enrichment = await enricher.enrich(extracted, depth, budget)
        await db.log_enrichment_trace(workspace_id, enrichment)

    # Stage 5: Triage card or auto-action
    if action == "auto_include":
        item = await db.create_item(workspace_id, extracted, priority=inferred_priority)
        await db.log_to_raw_log(workspace_id, extracted)
    elif action == "auto_drop":
        await db.log_to_raw_log(workspace_id, extracted, filtered=True)
    else:  # triage
        card = await llm.generate_triage_card(extracted, enrichment.context, raw_item.source_type)
        await messenger.send(user_identifier, card.render())
        await db.create_triage_card(workspace_id, card)
        await db.log_to_raw_log(workspace_id, extracted)
```

## Extraction (extraction.py)

Wraps the LLM Provider's `extract()` with:
- Input validation (reject empty or too-short text)
- Output validation (ensure extracted items have at minimum a summary)
- Error handling (LLM timeout, rate limit → retry with backoff)
- Logging (input length, output item count, latency)

## Filter (filter.py)

### `score_and_decide(workspace_id, extracted_item) → (action, relevance, confidence)`

1. Load workspace preferences from DB
2. Load global filter rules from DB
3. If source is email, also load email-specific filter rules for the account
4. Call `llm.score_relevance()` with all context
5. Apply thresholds from workspace config
6. Return action ("auto_include", "auto_drop", "triage") with scores

### `apply_triage_response(workspace_id, triage_card_id, response)`

Called when the user responds to a triage card via Messenger:

1. Parse the response to identify the chosen option
2. Execute the action:
   - `add_todo`: create item in DB with specified priority
   - `skip`: mark triage card as responded, no item created
   - `mute_sender`: create email filter rule for the sender
   - `mute_pattern`: create filter rule for the pattern
   - `accept_all`: create items for all action items in the card
   - `adjust_priority`: create items with user-specified priority
   - `add_plan`: trigger plan creation
3. Log to interaction log (full triage card + response)
4. If "mute" action, create the filter rule and link to interaction

## Enrichment (enrichment.py)

### `enrich_item(workspace_id, extracted_item) → EnrichmentResult`

1. Read enrichment depth and budget from workspace config
2. Call `enricher.enrich(item, depth, budget)`
3. Enforce budget limits:
   - Track API calls (abort if exceeding `max_api_calls_per_item`)
   - Track wall time (abort if exceeding `max_seconds_per_item`)
4. Log trace to `enrichment_trace` table
5. Return result

## Triage Card Generation (triage.py)

### `generate_and_send(workspace_id, extracted_item, enrichment_result)`

1. Call `llm.generate_triage_card(item, enrichment, source_type)`
2. Store card in `triage_cards` table
3. Send card via Messenger
4. Return card ID

### `check_responses(workspace_id)`

Called by the scheduler periodically:

1. Get the workspace's Messenger provider
2. Call `messenger.read_since(since=last_check_time)`
3. For each message, try to match to a pending triage card (by message ID or content matching)
4. Call `filter.apply_triage_response()` for each matched response
5. Update the triage card record with response and timestamp

## Preference Synthesis (preferences.py)

### `generate_digest(workspace_id) → PreferenceDigest`

1. Get current cursor position from `preferences` table
2. Query `interaction_log` for entries with ID > cursor
3. Compute:
   - Total and new interaction counts
   - Response distribution (how often each action is chosen)
   - Top included/dropped patterns
   - Recent interactions (last 20) for LLM context
4. Return `PreferenceDigest`

### `update_preferences(workspace_id)`

1. Call `generate_digest()`
2. If no new interactions, skip
3. Load current preference summary
4. Call `llm.synthesize_preferences(digest)` with current summary as context
5. Save updated summary and new cursor position

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `process_raw_input()` with meeting notes text → item created in DB with correct priority
2. `process_raw_input()` with low-relevance content → auto-dropped, logged with `[filtered]`
3. `process_raw_input()` with ambiguous content → triage card sent via Messenger
4. `poll_sources()` → calls each enabled adapter, skips already-processed items
5. Triage response "add todo P1" → item created in DB with P1 priority
6. Triage response "never surface from this sender" → email filter rule created
7. Enrichment respects budget: stops at `max_api_calls` even if enricher wants more
8. Enrichment trace logged to DB with correct metrics
9. `update_preferences()` reads only new interactions (cursor-based)
10. `update_preferences()` with no new interactions → no-op
11. End-to-end: raw text in → extraction → filter → enrich → triage card out

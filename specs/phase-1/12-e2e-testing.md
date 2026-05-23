# Step 12: End-to-End Testing

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: all previous steps

## Goal

Comprehensive test suite covering unit tests, integration tests, and end-to-end tests. Verify that the entire system works from input to triage to item creation.

## Files to Create

```
tests/
  conftest.py                -- shared fixtures (test DB, test client, mock providers)
  unit/
    test_filter.py           -- noise filter scoring and threshold logic
    test_preferences.py      -- preference digest and synthesis
    test_enrichment.py       -- enrichment budget enforcement
    test_doc_sections.py     -- markdown section parsing
    test_auth.py             -- password hashing, token generation
  integration/
    test_api_auth.py         -- registration, login, token flow
    test_api_workspaces.py   -- workspace CRUD and membership
    test_api_items.py        -- item CRUD with workspace isolation
    test_api_triage.py       -- triage card creation and response
    test_api_plans.py        -- plan CRUD
    test_api_sources.py      -- source adapter management
    test_api_filter_rules.py -- filter rule CRUD
    test_pipeline.py         -- pipeline stages with mock LLM
  e2e/
    test_full_flow.py        -- raw input to triage to item creation
    test_multi_workspace.py  -- data isolation between workspaces
    test_scheduler.py        -- scheduler fires and processes items
    test_mcp.py              -- MCP tool calls through the full stack
  providers/
    test_gmail_adapter.py    -- Gmail adapter (integration, requires credentials)
    test_google_docs.py      -- Google Docs reader (integration)
    test_llm_claude.py       -- Claude provider (integration, requires API key)
```

## Test Infrastructure

### conftest.py

- **Test database**: Use a separate PostgreSQL database (`workbench_test`). Create and drop per test session.
- **Test client**: `httpx.AsyncClient` with the FastAPI `TestClient`.
- **Mock providers**: In-memory implementations of all provider interfaces:
  - `MockLLMProvider`: returns deterministic extracted items, scores, and triage cards
  - `MockMessenger`: records sent messages in a list, simulates responses
  - `MockSourceAdapter`: returns configurable lists of raw items
  - `MockEnricher`: returns configurable context dicts
- **Factory fixtures**: `create_user()`, `create_workspace()`, `create_item()`, `create_triage_card()` for test setup

### Update requirements.txt (dev)

```
pytest>=8.0
pytest-asyncio>=0.24
httpx>=0.27
factory-boy>=3.3
```

## Key Test Scenarios

### Unit Tests

**test_filter.py**
- Score above include threshold → auto_include
- Score below drop threshold → auto_drop
- Score in between → triage
- Custom thresholds from workspace config are respected
- Email-specific pre-filter rules are applied before global rules
- Filter rules with "always" action bypass scoring

**test_preferences.py**
- Empty interaction log → empty digest
- Digest reads only entries after cursor
- Digest correctly computes response distribution
- Synthesis prompt includes recent interactions

**test_enrichment.py**
- Budget max_api_calls enforced: enricher is cut off at limit
- Budget max_seconds enforced: enricher times out
- Trace is logged with correct metrics
- Shallow depth calls enricher once, deep depth follows chain

### Integration Tests

**test_pipeline.py**
- Raw meeting notes → extraction produces action items
- Extracted item with high relevance → auto-included, item created in DB
- Extracted item with low relevance → auto-dropped, logged
- Extracted item with mid relevance → triage card sent via MockMessenger
- Triage response "add todo P1" → item created with P1
- Triage response "never" → filter rule created
- Dedup: processing same source_id twice → second is skipped

**test_api_workspaces.py**
- Create workspace → defaults created (preferences, config)
- List workspaces → only shows user's workspaces
- Access other user's workspace → 403
- Add member → member can access workspace
- Remove member → member loses access
- Cascading delete → all workspace data removed

**test_multi_workspace.py**
- Items in workspace A are not visible in workspace B
- Filter rules in workspace A don't affect workspace B
- Preferences are independent per workspace

### End-to-End Tests

**test_full_flow.py**
1. Create user and workspace
2. Configure MockMessenger and MockLLMProvider
3. Submit meeting notes via `POST /process`
4. Verify triage card sent to MockMessenger
5. Respond with "Accept all as P1"
6. Verify items created in DB with P1 priority
7. Verify interaction log entry created
8. Submit a second similar item → dedup prevents duplicate

**test_scheduler.py**
1. Create workspace with MockSourceAdapter that returns 2 items
2. Trigger source poller manually
3. Verify 2 triage cards created
4. Trigger again → no new cards (dedup)
5. MockSourceAdapter returns 1 new item → 1 new card

**test_mcp.py**
1. Connect to MCP server
2. Call `workbench_process` tool → verify pipeline runs
3. Call `workbench_items` → verify items returned
4. Call `workbench_triage_pending` → verify pending cards
5. Call `workbench_triage_respond` → verify response processed

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `pytest tests/unit/` — all unit tests pass
2. `pytest tests/integration/` — all integration tests pass (requires running PostgreSQL)
3. `pytest tests/e2e/` — all e2e tests pass (requires full docker-compose stack)
4. No test depends on external services (Gmail, Google Docs, Claude API) — those are in `tests/providers/` and run separately with credentials
5. Test coverage for pipeline stages ≥ 80%
6. Test coverage for API endpoints ≥ 90%
7. Multi-workspace isolation is verified
8. All mock providers follow the same interface as real providers

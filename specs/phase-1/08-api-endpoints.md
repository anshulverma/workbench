# Step 8: API Endpoints

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [04-workspaces.md](04-workspaces.md), [07-pipeline.md](07-pipeline.md)

## Goal

All remaining API endpoints: items, triage, plans, preferences, filter rules, interactions, enrichment, sources, export, config. Each endpoint is workspace-scoped and uses the workspace access middleware.

## Files to Create

```
server/
  api/
    items.py
    triage.py
    plans.py
    preferences.py
    filter_rules.py
    interactions.py
    enrichment.py
    sources.py
    export.py
    config.py
  schemas/
    items.py
    triage.py
    plans.py
    preferences.py
    filter_rules.py
    interactions.py
    enrichment.py
    sources.py
    export.py
    config.py
```

## Update main.py

Mount all routers under the FastAPI app.

## Endpoints

All endpoints below are prefixed with `/workspaces/{workspace_id}` and require authentication + workspace membership.

### Processing

**POST /workspaces/{id}/process**

Submit raw content for processing. Triggers the full pipeline.

Request:
```json
{
  "content": "Meeting notes text or document URL",
  "source_type": "meeting"  // optional, auto-detected if omitted
}
```

Response (202):
```json
{
  "job_id": "uuid",
  "status": "processing"
}
```

The pipeline runs asynchronously. The client can poll or receive results via Messenger.

### Items

**GET /workspaces/{id}/items**

Query params: `priority` (P0-P3), `status` (active/completed/archived), `source_type`, `limit`, `offset`

Response: paginated list of items.

**PATCH /workspaces/{id}/items/{item_id}**

Request:
```json
{
  "priority": "P1",         // optional
  "status": "completed"     // optional
}
```

**DELETE /workspaces/{id}/items/{item_id}**

Archives the item (soft delete — sets status to "archived").

### Triage

**GET /workspaces/{id}/triage/pending**

Returns triage cards that have not been responded to.

Response:
```json
[
  {
    "id": "uuid",
    "card_content": { ... },
    "options": ["Add todo P1", "Skip", "Never surface from this sender"],
    "sent_at": "2026-05-22T..."
  }
]
```

**POST /workspaces/{id}/triage/respond**

Request:
```json
{
  "triage_card_id": "uuid",
  "option_chosen": "Add todo P1",
  "details": {                    // optional, depends on the action
    "priority": "P1",
    "due_date": "2026-05-29"
  }
}
```

Response (200): the created item (if applicable) or confirmation.

### Plans

**POST /workspaces/{id}/plans**

Request:
```json
{
  "title": "Project X Migration",
  "content": "## Context\n...",
  "sources": ["meeting-123", "task-456"]
}
```

**GET /workspaces/{id}/plans**

Query params: `status` (draft/reviewed/finalized)

**PATCH /workspaces/{id}/plans/{plan_id}**

Request:
```json
{
  "status": "reviewed",     // optional
  "content": "updated..."   // optional
}
```

### Preferences

**GET /workspaces/{id}/preferences**

Response:
```json
{
  "content": "# Preferences\n...",
  "cursor_position": 42,
  "updated_at": "2026-05-22T..."
}
```

**GET /workspaces/{id}/preferences/digest**

Returns the incremental digest since last cursor.

Response: `PreferenceDigest` JSON.

### Filter Rules

**GET /workspaces/{id}/filter-rules**

Returns all global filter rules for the workspace.

**POST /workspaces/{id}/filter-rules**

Request:
```json
{
  "pattern": "CI bot comments on code reviews",
  "action": "drop",
  "priority": null
}
```

**GET /workspaces/{id}/filter-rules/email/{account}**

Returns email-specific filter rules for the given email account.

### Interaction Log

**GET /workspaces/{id}/interactions**

Query params: `cursor` (UUID, return entries after this ID), `limit` (default 50)

Response: list of interaction log entries with cursor-based pagination.

### Enrichment

**GET /workspaces/{id}/enrichment/trace**

Query params: `item_id` (optional), `limit`, `offset`

Response: enrichment trace entries.

### Sources

**GET /workspaces/{id}/sources**

List all configured source adapters for the workspace.

Response:
```json
[
  {
    "id": "uuid",
    "adapter_type": "email",
    "config": {"account": "user@gmail.com"},
    "schedule": "*/30 * * * *",
    "enabled": true,
    "created_at": "..."
  }
]
```

**POST /workspaces/{id}/sources**

Request:
```json
{
  "adapter_type": "email",
  "config": {"account": "user@gmail.com"},
  "credentials": {"oauth_refresh_token": "..."},
  "schedule": "*/30 * * * *"
}
```

Credentials are encrypted before storage.

**PATCH /workspaces/{id}/sources/{source_id}**

Update config, schedule, or enabled status.

**DELETE /workspaces/{id}/sources/{source_id}**

### Export

**POST /workspaces/{id}/export**

Request:
```json
{
  "target": "google_docs",      // or "notion"
  "config": {"folder_id": "..."}
}
```

Triggers an export of the current Dashboard to the specified target.

### Config

**GET /workspaces/{id}/config**

Returns all workspace config key-value pairs.

**PATCH /workspaces/{id}/config**

Request:
```json
{
  "enrichment_depth": "deep",
  "enrichment_max_api_calls_per_item": 15,
  "llm_provider": "openai"
}
```

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. All endpoints return correct status codes (200, 201, 202, 204, 400, 401, 403, 404)
2. All endpoints enforce workspace membership
3. `POST /process` triggers the pipeline asynchronously
4. `GET /items` supports filtering by priority, status, source_type
5. `POST /triage/respond` creates items and filter rules correctly
6. `GET /interactions` supports cursor-based pagination
7. `POST /sources` encrypts credentials before storage
8. `PATCH /config` validates config keys and value types
9. `POST /export` triggers export to the correct provider
10. All endpoints have Pydantic request/response schemas with validation

# Step 4: Workspace Management Endpoints

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [03-auth.md](03-auth.md)

## Goal

CRUD for workspaces and workspace membership. Creating a workspace also creates a default preference record and workspace config with sensible defaults.

## Files to Create

```
server/
  api/
    workspaces.py        -- workspace CRUD and member management
  schemas/
    workspaces.py        -- Pydantic models
  middleware/
    workspace_access.py  -- verify user has access to the requested workspace
```

## Endpoints

All endpoints require authentication.

### POST /workspaces

Create a new workspace. The authenticated user becomes the owner.

Request:
```json
{
  "name": "Work"
}
```

Response (201):
```json
{
  "id": "uuid",
  "name": "Work",
  "role": "owner",
  "created_at": "2026-05-22T..."
}
```

Side effects:
- Creates a `workspace_members` row with role "owner"
- Creates a `preferences` row with empty content and cursor_position 0
- Creates default `workspace_config` entries:
  - `enrichment_depth`: `"shallow"`
  - `enrichment_max_api_calls_per_item`: `3`
  - `enrichment_max_seconds_per_item`: `10`
  - `enrichment_max_deep_items_per_run`: `50`
  - `filter_relevance_include_threshold`: `70`
  - `filter_relevance_drop_threshold`: `30`
  - `filter_confidence_threshold`: `70`
  - `llm_provider`: `"claude"`
  - `messenger_provider`: `null` (must be configured)

### GET /workspaces

List all workspaces the authenticated user belongs to.

Response (200):
```json
[
  {
    "id": "uuid",
    "name": "Work",
    "role": "owner",
    "created_at": "..."
  },
  {
    "id": "uuid",
    "name": "Side Project",
    "role": "member",
    "created_at": "..."
  }
]
```

### GET /workspaces/{id}

Get workspace details including member list and source count.

Response (200):
```json
{
  "id": "uuid",
  "name": "Work",
  "role": "owner",
  "created_at": "...",
  "members": [
    {"user_id": "uuid", "name": "Anshul Verma", "role": "owner"},
    {"user_id": "uuid", "name": "Alice", "role": "member"}
  ],
  "source_count": 3,
  "item_count": 42,
  "pending_triage_count": 5
}
```

Errors:
- 403 if user is not a member
- 404 if workspace does not exist

### PATCH /workspaces/{id}

Update workspace name. Owner only.

Request:
```json
{
  "name": "Work - Main"
}
```

Response (200): updated workspace object.

Errors:
- 403 if user is not the owner

### POST /workspaces/{id}/members

Add a member to the workspace. Owner only.

Request:
```json
{
  "user_id": "uuid",
  "role": "member"
}
```

Response (201): member object.

Errors:
- 403 if requester is not the owner
- 404 if user_id does not exist
- 409 if user is already a member

### DELETE /workspaces/{id}/members/{user_id}

Remove a member. Owner only. Cannot remove self (owner).

Response (204): no content.

Errors:
- 403 if requester is not the owner
- 400 if trying to remove the owner

## Workspace Access Middleware

A reusable dependency that verifies the authenticated user has access to the workspace in the URL:

```python
async def get_workspace_member(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkspaceMember:
    """Return the WorkspaceMember or raise 403."""
```

An `owner_required` variant raises 403 if the user's role is not "owner".

All subsequent workspace-scoped endpoints use this dependency.

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. Create a workspace — returns 201, user is owner, defaults created
2. List workspaces — shows only workspaces the user belongs to
3. Get workspace details — includes member list and counts
4. Update workspace name — works for owner, 403 for member
5. Add a member — works for owner, 403 for member, 409 for duplicate
6. Remove a member — works for owner, 400 for self-removal
7. Access another user's workspace — returns 403
8. Default workspace config entries are created automatically
9. Default empty preferences record is created automatically

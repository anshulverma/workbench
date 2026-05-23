# Step 9: Server-Side Scheduler

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [07-pipeline.md](07-pipeline.md), [08-api-endpoints.md](08-api-endpoints.md)

## Goal

A background scheduler running inside the server process that handles periodic source polling, triage response checking, and daily cleanup — replacing the Claude Code cron approach.

## Files to Create

```
server/
  pipeline/
    scheduler.py           -- scheduler setup and job definitions
    cleanup.py             -- daily cleanup logic
```

## Scheduler Framework

Use APScheduler 4.x (async-compatible) running in-process with the FastAPI server. Jobs persist to PostgreSQL so they survive restarts.

### Update requirements.txt

Add:
```
apscheduler>=4.0
```

## Jobs

### Source Poller

- **Default schedule**: every 30 minutes (configurable per-workspace per-source)
- **Per-workspace**: one logical job per enabled source adapter
- **Logic**:
  1. For each workspace with enabled sources:
  2. For each enabled source in that workspace:
  3. Call `pipeline.engine.poll_sources(workspace_id)` for that source
  4. Update last_poll_time in source_configs

### Triage Response Checker

- **Default schedule**: every 10 minutes
- **Per-workspace**: one logical job per workspace with a configured Messenger
- **Logic**:
  1. For each workspace with a configured Messenger:
  2. Call `pipeline.triage.check_responses(workspace_id)`
  3. Process any matched responses

### Daily Cleanup

- **Schedule**: once daily (default 06:47 UTC, configurable per-workspace)
- **Logic** (see cleanup.py below):
  1. Archive completed items (status = "completed" for >24h)
  2. Flag stale items (active items older than 14 days with no update)
  3. Re-sort Dashboard items by priority
  4. Regenerate preference summary
  5. Export Dashboard to configured doc provider (if configured)

### Job Registration

On server startup:
1. Query all workspaces
2. For each workspace, register jobs based on its source configs and settings
3. When a workspace's source config changes (via API), dynamically add/remove/reschedule jobs

## cleanup.py

### `run_daily_cleanup(workspace_id)`

```python
async def run_daily_cleanup(workspace_id):
    # 1. Archive completed items
    completed = await db.get_items(workspace_id, status="completed", older_than=timedelta(hours=24))
    for item in completed:
        await db.update_item(item.id, status="archived")

    # 2. Flag stale items
    stale = await db.get_items(workspace_id, status="active", older_than=timedelta(days=14))
    for item in stale:
        # Send a Messenger reminder asking if still relevant
        await messenger.send(user, f"Stale item: {item.summary}. Still relevant? (yes/no)")

    # 3. Regenerate preferences
    await pipeline.preferences.update_preferences(workspace_id)

    # 4. Export Dashboard (if configured)
    export_target = await db.get_config(workspace_id, "export_target")
    if export_target:
        dashboard_content = await render_dashboard(workspace_id)
        exporter = registry.get_doc_exporter(export_target)
        await exporter.export_dashboard(workspace_id, dashboard_content)
```

### `render_dashboard(workspace_id) → str`

Generates the Dashboard markdown from current DB state:
1. Query all active items grouped by priority
2. Query pending triage cards
3. Query meetings to schedule
4. Query plans with status
5. Render as the markdown template from the spec

## Error Handling

- Each job runs in its own try/except — one workspace's failure doesn't block others
- Errors are logged with workspace_id context
- After 3 consecutive failures for a job, it's paused and an alert is sent via Messenger
- `/workspaces/{id}/status` endpoint reflects scheduler health per-job

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. Server starts with scheduler running — no separate process needed
2. Source poller fires on schedule and calls the pipeline for each enabled source
3. Triage response checker finds and processes Messenger replies
4. Daily cleanup archives old completed items
5. Daily cleanup sends stale-item reminders via Messenger
6. Daily cleanup regenerates preferences from interaction log
7. Adding a new source via API → job is dynamically registered
8. Disabling a source via API → job is paused
9. Deleting a workspace → all its jobs are removed
10. One workspace's scheduler failure doesn't affect other workspaces

# Step 11: Claude Code Plugin (Thin Client)

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [08-api-endpoints.md](08-api-endpoints.md), [10-mcp-server.md](10-mcp-server.md)

## Goal

A Claude Code plugin that provides slash commands for interacting with the Workbench server. The plugin is a thin client — all logic runs on the server.

## Files to Create

```
plugin/
  .claude-plugin/
    plugin.json
  commands/
    process.md             -- /process <text or doc link>
    setup.md               -- /workbench:setup
    status.md              -- /workbench:status
    triage.md              -- /workbench:triage
    sources.md             -- /workbench:sources
  config/
    config.json            -- server URL, API token, default workspace ID
```

## plugin.json

```json
{
  "name": "workbench",
  "version": "0.1.0",
  "description": "Personal intelligence feed — triage meetings, emails, tasks, and code reviews from one dashboard.",
  "commands": [
    {"name": "process", "path": "commands/process.md"},
    {"name": "setup", "path": "commands/setup.md"},
    {"name": "status", "path": "commands/status.md"},
    {"name": "triage", "path": "commands/triage.md"},
    {"name": "sources", "path": "commands/sources.md"}
  ]
}
```

## Commands

### /process (commands/process.md)

```yaml
---
name: process
description: "Process meeting notes, emails, or any text through the Workbench pipeline"
argument-hint: "<pasted text, Google Doc URL, or Notion URL>"
---
```

Instructions:
1. Read `config/config.json` to get server URL, API token, and default workspace ID
2. Detect if `$ARGUMENTS` is a URL or raw text
3. Call `POST /workspaces/{id}/process` with the content
4. Report the result to the user (how many items extracted, what triage cards were sent)

### /workbench:setup (commands/setup.md)

```yaml
---
name: setup
description: "Set up Workbench: start containers, create account, configure workspace"
---
```

Instructions:
1. Check if Docker/Podman is available
2. Check if containers are already running (`docker-compose ps`)
3. If not running, start them (`docker-compose up -d` from the project's `server/` directory)
4. Wait for health check (`curl http://localhost:8000/health`)
5. If no config exists, prompt the user for:
   - Email and name (for registration)
   - Workspace name
6. Register user via `POST /auth/register`
7. Login via `POST /auth/login`
8. Generate API token via `POST /auth/token`
9. Create workspace via `POST /workspaces`
10. Save server URL, API token, and workspace ID to `config/config.json`
11. Ask user to configure a Messenger provider (WhatsApp, Discord, or Google Chat)
12. Send a test message via the configured Messenger
13. Print the workspace ID and confirm setup is complete

### /workbench:status (commands/status.md)

```yaml
---
name: status
description: "Show Workbench health: server, scheduler, sources, pending items"
---
```

Instructions:
1. Read config
2. Call `GET /health` — report server and DB status
3. Call `GET /workspaces/{id}` — report item counts, pending triage, source count
4. Call `GET /workspaces/{id}/sources` — list sources with enabled/disabled status
5. Format as a concise status report

### /workbench:triage (commands/triage.md)

```yaml
---
name: triage
description: "Triage pending items directly in the CLI"
---
```

Instructions:
1. Read config
2. Call `GET /workspaces/{id}/triage/pending`
3. If no pending items, report "Nothing to triage"
4. For each pending triage card:
   - Display the card content (summary, context, options)
   - Ask the user which option to choose (using AskUserQuestion or natural conversation)
   - Call `POST /workspaces/{id}/triage/respond` with their choice
   - Report the result (item created, rule added, etc.)
5. After all cards processed, report summary

### /workbench:sources (commands/sources.md)

```yaml
---
name: sources
description: "Manage input sources: list, add, enable, disable"
---
```

Instructions:
1. Read config
2. Call `GET /workspaces/{id}/sources` — list current sources
3. Ask user what they want to do (list, add, enable/disable, remove)
4. For "add": ask for adapter type, credentials, schedule
5. Call the appropriate API endpoint
6. Report result

## config/config.json

```json
{
  "server_url": "http://localhost:8000",
  "api_token": "wb_...",
  "default_workspace_id": "uuid"
}
```

Created by `/workbench:setup`, read by all other commands.

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `/workbench:setup` starts containers, creates user/workspace, saves config
2. `/process` with pasted text calls the server and reports results
3. `/process` with a Google Doc URL calls the server and reports results
4. `/workbench:status` shows server health, item counts, source status
5. `/workbench:triage` presents pending cards and processes responses interactively
6. `/workbench:sources` lists, adds, and toggles sources via API
7. All commands fail gracefully if the server is not running (clear error message)
8. All commands fail gracefully if config.json is missing (suggest running setup)

# Step 10: MCP Server

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [08-api-endpoints.md](08-api-endpoints.md)

## Goal

An MCP (Model Context Protocol) server that exposes Workbench functionality as tools, so any MCP-compatible client (Claude Code, Claude Desktop, etc.) can interact with Workbench natively through tool calls.

## Files to Create

```
server/
  mcp/
    __init__.py
    server.py              -- MCP server setup and transport
    tools.py               -- MCP tool definitions
    config.py              -- MCP-specific configuration
```

## Update requirements.txt

Add:
```
mcp>=1.0
```

## MCP Server Setup (server.py)

The MCP server runs as part of the FastAPI application, exposed via SSE (Server-Sent Events) transport at `/mcp`. This allows remote MCP connections without running a separate process.

Alternatively, the MCP server can run as a standalone stdio process for local Claude Code usage:

```bash
workbench-mcp --server-url http://localhost:8000 --api-token wb_...
```

Both modes use the same tool definitions.

## MCP Tools (tools.py)

### workbench_process

Submit content for processing through the pipeline.

```json
{
  "name": "workbench_process",
  "description": "Process raw text or a document URL through the Workbench pipeline. Extracts action items, filters noise, and sends triage cards.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {"type": "string", "description": "Raw text or document URL to process"},
      "source_type": {"type": "string", "enum": ["meeting", "email", "social", "task", "code_review"], "description": "Type of source (auto-detected if omitted)"},
      "workspace_id": {"type": "string", "description": "Workspace ID (uses default if omitted)"}
    },
    "required": ["content"]
  }
}
```

### workbench_items

List and filter items in the dashboard.

```json
{
  "name": "workbench_items",
  "description": "List action items in the Workbench dashboard, filtered by priority, status, or source.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
      "status": {"type": "string", "enum": ["active", "completed", "archived"]},
      "source_type": {"type": "string"},
      "limit": {"type": "integer", "default": 20},
      "workspace_id": {"type": "string"}
    }
  }
}
```

### workbench_triage_pending

List items awaiting triage response.

```json
{
  "name": "workbench_triage_pending",
  "description": "List triage cards that haven't been responded to yet.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "workspace_id": {"type": "string"}
    }
  }
}
```

### workbench_triage_respond

Respond to a pending triage card.

```json
{
  "name": "workbench_triage_respond",
  "description": "Respond to a triage card with a chosen action.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "triage_card_id": {"type": "string", "description": "ID of the triage card"},
      "option_chosen": {"type": "string", "description": "The chosen action (e.g., 'Add todo P1', 'Skip', 'Never surface from this sender')"},
      "details": {"type": "object", "description": "Additional details for the chosen action"}
    },
    "required": ["triage_card_id", "option_chosen"]
  }
}
```

### workbench_status

Get workspace status and health.

```json
{
  "name": "workbench_status",
  "description": "Get the current status of a Workbench workspace: item counts, pending triage, source health, scheduler status.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "workspace_id": {"type": "string"}
    }
  }
}
```

### workbench_plans

List, create, or update plans.

```json
{
  "name": "workbench_plans",
  "description": "Manage draft plans. List plans by status, create new plans, or update existing ones.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["list", "create", "update"]},
      "plan_id": {"type": "string", "description": "Required for update"},
      "title": {"type": "string", "description": "Required for create"},
      "content": {"type": "string"},
      "status": {"type": "string", "enum": ["draft", "reviewed", "finalized"]},
      "workspace_id": {"type": "string"}
    },
    "required": ["action"]
  }
}
```

### workbench_sources

Manage source adapters.

```json
{
  "name": "workbench_sources",
  "description": "List, add, update, or remove source adapters for a workspace.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["list", "add", "update", "remove"]},
      "source_id": {"type": "string"},
      "adapter_type": {"type": "string", "enum": ["email", "meeting", "social", "task", "code_review"]},
      "config": {"type": "object"},
      "credentials": {"type": "object"},
      "schedule": {"type": "string"},
      "enabled": {"type": "boolean"},
      "workspace_id": {"type": "string"}
    },
    "required": ["action"]
  }
}
```

## Authentication

The MCP server authenticates via the API token stored in its config:

- **SSE mode**: token passed as a query parameter or header on the SSE connection
- **stdio mode**: token read from `--api-token` flag or `WORKBENCH_API_TOKEN` env var

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. MCP server starts alongside the FastAPI server (SSE transport at `/mcp`)
2. `workbench_process` tool processes text and returns confirmation
3. `workbench_items` tool returns filtered items from the database
4. `workbench_triage_pending` tool returns pending triage cards
5. `workbench_triage_respond` tool processes a response and creates items/rules
6. `workbench_status` tool returns workspace health metrics
7. Claude Code can connect to the MCP server and use all tools
8. Authentication works via API token
9. Invalid/missing token returns auth error
10. All tools respect workspace scoping — users only see their workspace data

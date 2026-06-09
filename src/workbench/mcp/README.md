# mcp

**Purpose:** the MCP (Model Context Protocol) server — tool access to Workbench
from any MCP-compatible client. Like the plugin, it is a thin HTTP client to the
API and holds no business logic or direct storage access.

**What belongs here:** the MCP server entrypoint (`__init__.py`) and tool
definitions (`tools.py`) that wrap REST API calls.

**What does NOT belong here:** business logic, storage access, or pipeline
stages — MCP tools call the HTTP API, never the internals directly.

**Update this README when** you add a new KIND of code here (a new tool surface
or transport) — not for every new tool definition.

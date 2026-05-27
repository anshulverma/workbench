# /workbench:status

Show the Workbench dashboard — active items grouped by priority, pending triage count, and system health.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. Call `GET {server_url}/health` with header `Authorization: Bearer {api_token}` to verify the server is running.
3. Call `GET {server_url}/api/items?status=active` with the same auth header to get all active items.
4. Call `GET {server_url}/api/triage/pending` with the same auth header to get pending triage cards.
5. Format the response as a dashboard:
   - Show server health status at the top.
   - Group active items by priority (P0, P1, P2, P3). For each item show: summary, source type, and creation date.
   - Show the count of pending triage cards.
   - Example output:
     ```
     Workbench Status
     Server: healthy

     P0 — Today (2)
       - Review auth middleware [diff] (2h ago)
       - SEV followup action items [sev] (4h ago)

     P1 — This Week (1)
       - Write design doc for migration [meeting] (1d ago)

     P2 — Backlog (3)
       - Update oncall runbook [email] (2d ago)
       - Review team RFC [doc] (3d ago)
       - Clean up test fixtures [diff] (5d ago)

     Pending Triage: 2 items
     Run /workbench:triage to review them.
     ```
6. If there are no active items and no pending triage, display: "All clear! No active items or pending triage."
7. If the server is unreachable, display an error and suggest running `/workbench:setup`.

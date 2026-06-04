# /workbench:actions

View and manage pending action items grouped by category.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. Call `GET {server_url}/api/actions` with header `Authorization: Bearer {api_token}` to get all pending action items.
3. If no action items are returned (total is 0), display: "No pending actions. You're all caught up!"
4. Format the response as a categorized list:
   - Show the total count at the top.
   - For each category, show the category name and item count.
   - For each item, show: priority badge, summary, parent item (if any), and age.
   - Example output:
     ```
     Action Items (4)

     Delegation (2):
       [P1] Assign auth migration to bob — from Review auth middleware  (2h ago)
       [P2] Forward RFC to infra team — from Design doc review  (1d ago)

     Review (1):
       [P1] Review alice's API changes  (4h ago)

     Communication (1):
       [P2] Follow up with team about timeline  (3d ago)
     ```
5. After displaying items, present action options:
   - Ask: "Enter an item number to act on it, or press Enter to exit."
   - Number items 1-N across all categories in display order.
6. When the user picks an item number, present actions:
   ```
   [P1] Assign auth migration to bob

   What do you want to do?
   1. Mark done
   2. Change priority
   3. Snooze (4h)
   4. Back to list
   ```
7. Execute the chosen action:
   - **Mark done**: Call `POST {server_url}/api/actions/{item_id}/done` with auth header. Display: "Marked as done."
   - **Change priority**: Ask which priority (P0/P1/P2/P3). Call `POST {server_url}/api/actions/{item_id}/priority` with `{"priority": "P1"}`. Display: "Priority changed to P1."
   - **Snooze**: Call `POST {server_url}/api/actions/{item_id}/snooze` with `{"hours": 4}`. Display: "Snoozed for 4 hours."
8. After each action, refresh and redisplay the list.
9. Support a `--category` flag to filter by category:
   - `/workbench:actions --category delegation` shows only delegation items.
   - Call `GET {server_url}/api/actions?category=delegation` with auth header.
10. If the server is unreachable, display an error and suggest running `/workbench:setup`.

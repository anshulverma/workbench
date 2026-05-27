# /workbench:triage

Interactive CLI triage — review pending items one by one and choose an action for each.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. Call `GET {server_url}/api/triage/pending` with header `Authorization: Bearer {api_token}` to get all pending triage cards.
3. If no cards are pending, display: "No items pending triage. You're all caught up!"
4. For each pending card, display it and ask the user to choose:
   - Show the card number and total (e.g., "Item 1 of 3")
   - Show the source type and summary from `card_content`
   - Show enrichment context if present in `card_content.enrichment`
   - List the numbered options from the card's `options` array
   - Add a "Skip all remaining" option at the end
   - Example:
     ```
     Item 1 of 3

     [diff] Review auth middleware changes in D12345
     Context: PR has 3 files changed, authored by alice

     What do you want to do?
     1. Add todo (P1)
     2. Add todo (P2)
     3. Skip
     4. Never surface diffs like this
     5. Skip all remaining
     ```
5. When the user picks a number, call `POST {server_url}/api/triage/respond` with the same auth header and JSON body:
   ```json
   {
     "card_id": "<card.id>",
     "choice": <number>,
     "raw_text": "<user's choice label>"
   }
   ```
6. After each response, show a brief confirmation:
   - "Added as P1 todo" / "Added as P2 todo" / "Skipped" / "Mute pattern created"
7. If "Skip all remaining" is chosen, call the respond endpoint for each remaining card with `choice: 0` and `raw_text: "skip all"`, then display: "Skipped N remaining items."
8. After all cards are processed, display a summary: "Triage complete. N items processed."

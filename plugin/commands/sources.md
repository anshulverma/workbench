# /workbench:sources

Manage source adapters — list, add, update, enable/disable, and remove data sources that feed the Workbench pipeline.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. If no subcommand is given, list all sources:
   - Call `GET {server_url}/api/sources` with header `Authorization: Bearer {api_token}`.
   - Display each source with: adapter type, schedule, enabled status, and config summary.
   - Example:
     ```
     Sources (2 configured)

     1. diff (Phabricator)
        Schedule: */15 * * * *
        Status: enabled
        Config: user_phid=PHID-USER-abc123

     2. email (Gmail)
        Schedule: */30 * * * *
        Status: disabled
        Config: google_api_script=server/lib/google_api.py
     ```

3. To add a source, ask the user for:
   - **Adapter type**: One of `diff`, `email`, or other supported types.
   - **Config**: Key-value pairs specific to the adapter type (e.g., `user_phid` for diff).
   - **Schedule**: Cron expression for polling frequency (default: `*/15 * * * *`).
   - Call `POST {server_url}/api/sources` with the same auth header and JSON body:
     ```json
     {
       "adapter_type": "<type>",
       "config": { "<key>": "<value>" },
       "schedule": "<cron>",
       "enabled": true
     }
     ```
   - Display: "Source added: {adapter_type} ({source_id})"

4. To update a source, ask which source (by number from the list) and what to change:
   - Call `PATCH {server_url}/api/sources/{source_id}` with the updated fields.
   - Display: "Source updated: {source_id}"

5. To enable/disable a source:
   - Call `PATCH {server_url}/api/sources/{source_id}` with `{"enabled": true/false}`.
   - Display: "Source {enabled/disabled}: {adapter_type} ({source_id})"

6. To remove a source:
   - Confirm with the user before deleting.
   - Call `DELETE {server_url}/api/sources/{source_id}` with the same auth header.
   - Display: "Source removed: {adapter_type} ({source_id})"

# /workbench:sources

List and manage source adapters that feed the Workbench pipeline.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. List all sources:
   - Call `GET {server_url}/api/sources` with header `Authorization: Bearer {api_token}`.
   - Display each source with: adapter type, schedule, enabled status, and config summary.
   - Example:
     ```
     Sources (1 configured)

     1. github (GitHubSourceAdapter)
        Schedule: */15 * * * *
        Status: enabled
        Config: repos=["owner/repo"]
     ```

3. To update a source (enable/disable, change schedule):
   - Ask which source (by number from the list) and what to change.
   - Call `PATCH {server_url}/api/sources/{source_id}` with the updated fields.
   - Display: "Source updated: {source_id}"

Note: Sources are configured in `config.yml`. To add or remove sources, edit the `sources:` section in your config file and restart the server.

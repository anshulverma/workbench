# /workbench:setup

Configure the Workbench plugin by setting the server URL and API token. Writes settings to `plugin/config/config.json`.

## Instructions

1. Read the current config from `plugin/config/config.json` if it exists. Show the current values (mask the token, showing only the last 4 characters).
2. Ask the user for:
   - **Server URL**: The base URL of the Workbench server (e.g., `http://devgpu004.lla1.facebook.com:8421`). If the user presses enter, keep the current value.
   - **API token**: The bearer token for authentication. If the user presses enter, keep the current value.
3. Write the updated config to `plugin/config/config.json`:
   ```json
   {
     "server_url": "<server_url>",
     "api_token": "<api_token>"
   }
   ```
4. Verify connectivity by calling `GET {server_url}/health` with header `Authorization: Bearer {api_token}`.
5. Display the result:
   - **If successful**: "Connected to Workbench server at {server_url}. Status: ok"
   - **If failed**: "Could not connect to {server_url}: {error}. Check the URL and token."

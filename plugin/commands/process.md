# /process

Submit text or a document link for processing through the Workbench pipeline. The server extracts actionable items, scores them for relevance, and either auto-includes, auto-drops, or queues them for triage.

## Instructions

1. Read the server URL and API token from `plugin/config/config.json`.
2. Accept the user's input. It can be:
   - Raw text (meeting notes, email content, etc.)
   - A document URL (Google Doc, etc.)
3. If the input looks like a URL, set `source_type` to `"doc"`. Otherwise, infer from context or default to `"manual"`.
4. Call `POST {server_url}/api/process` with header `Authorization: Bearer {api_token}` and JSON body:
   ```json
   {
     "text": "<the user's input text or URL>",
     "source_type": "<source_type>"
   }
   ```
5. The response contains a job object with `job_id` and `status`.
6. Poll `GET {server_url}/api/jobs/{job_id}` with the same auth header until `status` is `"completed"` or `"failed"` (check every 2 seconds, up to 30 seconds).
7. Display the result:
   - **If completed**: Show items extracted, items included, items sent to triage, and items dropped.
   - **If failed**: Show the error message.
   - Example output:
     ```
     Processing complete (job abc123):
       Items extracted: 3
       Auto-included:   1
       Sent to triage:  1
       Dropped:         1
     ```
8. If items were sent to triage, suggest running `/workbench:triage` to review them.

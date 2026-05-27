# ADR 0003: Pipeline Processing is Async with Job Tracking

`POST /workspaces/{id}/process` returns a job ID immediately and runs the pipeline in the background. Job status is queryable via `GET /workspaces/{id}/jobs/{job_id}`. Each item in a batch is committed independently — partial failures don't roll back already-processed items.

We chose async over sync because a single raw input can produce multiple items, each requiring 2-3 LLM calls at 1-2s each. A synchronous endpoint would block for minutes on long meeting notes or batch poll runs. The job model also gives observability into pipeline throughput and failure rates.

**Consequence:** A new `jobs` table tracks pipeline work. The `/process` response is `{job_id, status: "pending"}`, not the processed items themselves. Clients poll or use the CLI to check results.

# Step 6: Provider Implementations

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [05-provider-interfaces.md](05-provider-interfaces.md)

## Goal

Concrete implementations for all provider interfaces. One real implementation per type where possible, stubs for the rest.

## Files to Create

```
server/
  providers/
    llm/
      claude.py              -- Anthropic Claude API
      openai.py              -- OpenAI API
      ollama.py              -- Local Ollama
    doc_reader/
      google_docs.py         -- Google Docs API
      notion.py              -- Notion API
      raw_url.py             -- fetch any URL, extract text
    doc_export/
      google_docs.py         -- export to Google Docs
      notion.py              -- export to Notion
    messenger/
      whatsapp.py            -- WhatsApp Business API
      discord.py             -- Discord Bot API
      google_chat.py         -- Google Chat API
    source/
      email_gmail.py         -- Gmail API (full implementation)
      meetings_stub.py       -- stub
      social_stub.py         -- stub
      tasks_stub.py          -- stub
      code_review_stub.py    -- stub
    enrichment/
      stub.py                -- returns empty context
```

## Update requirements.txt

Add:
```
anthropic>=0.40
openai>=1.50
httpx>=0.27
google-auth>=2.0
google-api-python-client>=2.0
```

## LLM Providers

### ClaudeProvider

- Uses `anthropic` Python SDK
- Config: `api_key`, `model` (default: `claude-sonnet-4-20250514`)
- `extract()`: sends raw text with a system prompt instructing structured extraction, parses response into `ExtractedItem`
- `score_relevance()`: sends item + preferences + rules, asks for (relevance, confidence) scores as JSON
- `generate_triage_card()`: sends item + enrichment + source_type, generates the card with source-specific options
- `synthesize_preferences()`: sends digest, asks for markdown preference summary

### OpenAIProvider

- Uses `openai` Python SDK
- Config: `api_key`, `model` (default: `gpt-4o`)
- Same method signatures, different SDK calls

### OllamaProvider

- Uses HTTP calls to local Ollama API (`http://localhost:11434`)
- Config: `base_url`, `model`
- Same method signatures, HTTP-based

## DocReader Implementations

### GoogleDocsReader

- `can_handle()`: returns True for URLs matching `docs.google.com/document/d/`
- `read()`: extracts doc ID from URL, calls Google Docs API `documents.get`, converts to markdown
- Config: Google service account credentials JSON

### NotionReader

- `can_handle()`: returns True for URLs matching `notion.so/` or `notion.site/`
- `read()`: extracts page ID from URL, calls Notion API to get blocks, converts to markdown
- Config: Notion integration token

### RawURLReader

- `can_handle()`: returns True for any `http://` or `https://` URL (lowest priority)
- `read()`: fetches URL with `httpx`, extracts text content (strip HTML tags if HTML)

## DocExporter Implementations

### GoogleDocsExporter

- `export_dashboard()`: creates or updates a Google Doc with the dashboard markdown
- `create_plan_doc()`: creates a new Google Doc with the plan content, returns URL
- Config: Google service account credentials, folder ID

### NotionExporter

- `export_dashboard()`: creates or updates a Notion page
- `create_plan_doc()`: creates a new Notion page, returns URL
- Config: Notion integration token, parent page/database ID

## Messenger Implementations

### WhatsAppMessenger

- Uses WhatsApp Business API (Cloud API)
- `send()`: POST to `graph.facebook.com/v21.0/{phone_number_id}/messages`
- `read_since()`: uses webhook-received messages stored in DB (webhook handler needed in server)
- Config: phone_number_id, access_token, webhook_verify_token

### DiscordMessenger

- Uses Discord Bot API via `httpx`
- `send()`: POST to `/channels/{channel_id}/messages`
- `read_since()`: GET `/channels/{channel_id}/messages?after={snowflake}`
- Config: bot_token, channel_id (DM channel with the user)

### GoogleChatMessenger

- Uses Google Chat API
- `send()`: `spaces.messages.create`
- `read_since()`: `spaces.messages.list` with filter
- Config: Google service account credentials, space name

## Source Adapter Implementations

### EmailGmailAdapter

Full implementation:

- `adapter_type()`: returns `"email"`
- `poll()`:
  1. Authenticate with Gmail API using stored OAuth credentials
  2. List messages since last poll (or `since` parameter)
  3. For each message: fetch full content, extract sender, subject, to/cc, body
  4. Return as `RawItem` list with `id=message_id`, `source_type="email"`, `source_label="{sender} — {subject}"`, `raw_text=body`
- Config: OAuth client credentials, refresh token, email account address

### Stub Adapters

Each stub implements the interface and returns an empty list:

```python
class MeetingsStubAdapter(SourceAdapter):
    async def poll(self, config, since=None) -> list[RawItem]:
        return []

    def adapter_type(self) -> str:
        return "meeting"
```

Stubs log a warning: "No implementation for {type} source adapter. Implement {class_name} to enable this source."

## ContextEnricher Implementation

### StubEnricher

Returns empty context:

```python
class StubEnricher(ContextEnricher):
    async def enrich(self, item, depth, budget) -> EnrichmentResult:
        return EnrichmentResult(context={}, calls_made=0, time_ms=0)
```

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `ClaudeProvider.extract()` returns valid `ExtractedItem` from sample meeting notes
2. `GoogleDocsReader.read()` fetches a real Google Doc (integration test with test doc)
3. `RawURLReader.read()` fetches a public URL and returns text
4. `EmailGmailAdapter.poll()` fetches emails from a test Gmail account (integration test)
5. All stub adapters return empty lists without errors
6. `StubEnricher` returns empty context with 0 calls and 0 time
7. `ProviderRegistry` can resolve all implementations by name
8. All providers are configurable via their config dicts (no hardcoded credentials)
9. Missing API keys raise clear configuration errors, not cryptic crashes

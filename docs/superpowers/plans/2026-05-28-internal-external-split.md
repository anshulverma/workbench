# Internal/External Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Workbench into a public GitHub repo (`workbench`) with generic providers and a private internal overlay (`workbench-meta`) with Meta-specific providers. Push the clean public repo to GitHub.

**Architecture:** Two repos, one package namespace. Public repo has the framework + AnthropicLLM (direct API) + ConsoleMessenger (stdout) + GitHubSourceAdapter (gh CLI). Private repo has MetaAnthropicLLM (Plugboard + x509) + GoogleChatMessenger (DCAT) + PhabricatorAdapter (arc conduit). Private repo overlays via pip install + YAML config layering.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, OmegaConf, Anthropic SDK, gh CLI

**Spec:** `docs/superpowers/specs/2026-05-28-internal-external-split.md`

---

## File Structure

### Public repo (`workbench`) — new/modified files

```
src/workbench/
├── providers/
│   ├── llm/
│   │   └── anthropic.py         # NEW: AnthropicLLM (direct API, no certs)
│   ├── messenger/
│   │   └── console.py           # NEW: ConsoleMessenger (stdout)
│   ├── source/
│   │   ├── base.py              # MODIFIED: remove config param from poll()
│   │   └── github.py            # NEW: GitHubSourceAdapter (gh CLI)
│   └── queue_scorer/
│       └── llm.py               # MODIFIED: strip certs, use direct API
├── cli.py                       # NEW: workbench triage command
config.example.yml               # MODIFIED: external defaults
pyproject.toml                   # MODIFIED: remove unused deps
CLAUDE.md                        # MODIFIED: genericized
CONTEXT.md                       # MODIFIED: genericized
README.md                        # NEW
LICENSE                           # NEW
```

### Files deleted from public repo

```
src/workbench/providers/llm/claude.py          # → workbench-meta
src/workbench/providers/messenger/google_chat.py # → workbench-meta
src/workbench/providers/source/phabricator.py    # → workbench-meta
src/workbench/providers/source/email_gmail.py    # → workbench-meta
src/workbench/lib/google_api.py                  # → workbench-meta
docs/memory/                                     # already in Claude project memory
docs/specs/                                      # → workbench-meta/docs/original/
docs/adr/                                        # → workbench-meta/docs/original/
docs/superpowers/specs/                          # → workbench-meta/docs/original/
docs/plans/                                      # → workbench-meta/docs/original/
```

### Private repo (`workbench-meta`) — new structure

```
~/workspace/workbench-meta/
├── pyproject.toml
├── docker-compose.override.yml
├── config.meta.yml
├── workbench_meta/
│   ├── __init__.py
│   ├── providers/
│   │   ├── llm/meta_anthropic.py
│   │   ├── messenger/gchat.py
│   │   ├── source/phabricator.py
│   │   ├── source/gmail.py
│   │   ├── enrichment/meta.py
│   │   └── queue_scorer/meta_scorer.py
│   └── lib/google_api.py
├── docs/original/                # preserved pre-genericization docs
└── tests/
```

---

## Task 1: Create workbench-meta repo + move Meta providers

**Goal:** Create the `~/workspace/workbench-meta` directory with all Meta-specific provider code moved from workbench.

**Files:**
- Create: `~/workspace/workbench-meta/pyproject.toml`
- Create: `~/workspace/workbench-meta/workbench_meta/__init__.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/llm/meta_anthropic.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/queue_scorer/meta_scorer.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/messenger/gchat.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/source/phabricator.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/source/gmail.py`
- Create: `~/workspace/workbench-meta/workbench_meta/providers/enrichment/meta.py`
- Create: `~/workspace/workbench-meta/workbench_meta/lib/google_api.py`
- Create: `~/workspace/workbench-meta/config.meta.yml`
- Create: `~/workspace/workbench-meta/docker-compose.override.yml`
- Create: all `__init__.py` files for the package hierarchy

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p ~/workspace/workbench-meta/workbench_meta/{providers/{llm,messenger,source,enrichment,queue_scorer},lib}
mkdir -p ~/workspace/workbench-meta/{docs/original,tests}
```

- [ ] **Step 2: Create pyproject.toml**

```toml
# ~/workspace/workbench-meta/pyproject.toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "workbench-meta"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "workbench",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["workbench_meta*"]
```

- [ ] **Step 3: Create all `__init__.py` files**

```bash
touch ~/workspace/workbench-meta/workbench_meta/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/llm/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/messenger/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/source/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/enrichment/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/providers/queue_scorer/__init__.py
touch ~/workspace/workbench-meta/workbench_meta/lib/__init__.py
```

- [ ] **Step 4: Create MetaAnthropicLLM**

This inherits from the public `AnthropicLLM` (which will be created in Task 2) and adds mTLS cert logic:

```python
# ~/workspace/workbench-meta/workbench_meta/providers/llm/meta_anthropic.py
import os
import ssl

import httpx
from workbench.providers.llm.anthropic import AnthropicLLM


class MetaAnthropicLLM(AnthropicLLM):
    class ProviderConfig(AnthropicLLM.ProviderConfig):
        base_url: str = "https://plugboard.x2p.facebook.net"

    def __init__(self, config: ProviderConfig):
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            config = self.ProviderConfig(
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
                http_client=httpx.AsyncClient(verify=ssl_ctx),
            )
        super().__init__(config)
```

- [ ] **Step 5: Create MetaQueueScorer**

```python
# ~/workspace/workbench-meta/workbench_meta/providers/queue_scorer/meta_scorer.py
import os
import ssl

import httpx
from workbench.providers.queue_scorer.llm import LLMQueueScorer


class MetaQueueScorer(LLMQueueScorer):
    class ProviderConfig(LLMQueueScorer.ProviderConfig):
        base_url: str = "https://plugboard.x2p.facebook.net"

    def __init__(self, config: ProviderConfig):
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            config = self.ProviderConfig(
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
                http_client=httpx.AsyncClient(verify=ssl_ctx),
            )
        super().__init__(config)
```

- [ ] **Step 6: Copy GoogleChatMessenger**

```bash
cp src/workbench/providers/messenger/google_chat.py \
   ~/workspace/workbench-meta/workbench_meta/providers/messenger/gchat.py
```

Update the import in the copied file: change `from workbench.providers.messenger.base import Messenger` (this import stays correct since workbench is a dependency).

- [ ] **Step 7: Copy PhabricatorAdapter and GmailAdapter**

```bash
cp src/workbench/providers/source/phabricator.py \
   ~/workspace/workbench-meta/workbench_meta/providers/source/phabricator.py
cp src/workbench/providers/source/email_gmail.py \
   ~/workspace/workbench-meta/workbench_meta/providers/source/gmail.py
```

Update PhabricatorAdapter's `poll` signature to remove the `config: dict` param (the ABC cleanup happens in Task 3, but the meta copy should already use the new signature):

In `phabricator.py`, change:
```python
async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
```
to:
```python
async def poll(self, since: datetime | None = None) -> list[RawItem]:
```
And remove `user_phid = self.user_phid or config.get("user_phid", "")` — just use `self.user_phid`.

Do the same for `gmail.py`.

- [ ] **Step 8: Create stub MetaEnricher**

```python
# ~/workspace/workbench-meta/workbench_meta/providers/enrichment/meta.py
from pydantic import BaseModel
from workbench.providers.enrichment.base import ContextEnricher
from workbench.models import ExtractedItem, EnrichmentBudget


class MetaEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget) -> dict:
        return {"calls_made": 0, "time_ms": 0, "context": {}}
```

- [ ] **Step 9: Copy google_api.py**

```bash
cp src/workbench/lib/google_api.py ~/workspace/workbench-meta/workbench_meta/lib/google_api.py
```

- [ ] **Step 10: Create config.meta.yml**

```yaml
# ~/workspace/workbench-meta/config.meta.yml
llm:
  class: workbench_meta.providers.llm.meta_anthropic.MetaAnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: https://plugboard.x2p.facebook.net

queue:
  scorer:
    class: workbench_meta.providers.queue_scorer.meta_scorer.MetaQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY}
    base_url: https://plugboard.x2p.facebook.net
    model: claude-haiku-4-5-20251001

messenger:
  class: workbench_meta.providers.messenger.gchat.GoogleChatMessenger
  space_id: ${oc.env:GCHAT_SPACE_ID}
  google_api_script: ${oc.env:GOOGLE_API_SCRIPT,workbench_meta/lib/google_api.py}

sources:
  - class: workbench_meta.providers.source.phabricator.PhabricatorAdapter
    user_phid: ${oc.env:PHABRICATOR_USER_PHID}
```

- [ ] **Step 11: Create docker-compose.override.yml**

```yaml
# ~/workspace/workbench-meta/docker-compose.override.yml
services:
  workbench:
    volumes:
      - ~/workspace/workbench-meta:/opt/workbench-meta:ro
      - ~/workspace/workbench-meta/config.meta.yml:/app/config.override.yml:ro
    command: >
      sh -c "pip install -e /opt/workbench-meta &&
             workbench serve --config /app/config.yml --override /app/config.override.yml"
```

- [ ] **Step 12: Copy original docs for reference**

```bash
cp -r docs/specs ~/workspace/workbench-meta/docs/original/specs
cp -r docs/adr ~/workspace/workbench-meta/docs/original/adr
cp CONTEXT.md ~/workspace/workbench-meta/docs/original/CONTEXT.md
```

- [ ] **Step 13: Init git in workbench-meta and commit**

```bash
cd ~/workspace/workbench-meta
git init
git add -A
git commit -m "Initial workbench-meta: Meta-specific providers for Workbench

MetaAnthropicLLM (Plugboard + x509), MetaQueueScorer, GoogleChatMessenger
(DCAT), PhabricatorAdapter (arc conduit), GmailAdapter. Overlays the public
workbench package via pip install + YAML config layering."
cd ~/workspace/workbench
```

---

## Task 2: Create AnthropicLLM (public, generic)

**Goal:** Create the generic `AnthropicLLM` that has all the business logic from `ClaudeProvider` but no Meta cert/proxy code.

**Files:**
- Create: `src/workbench/providers/llm/anthropic.py`

- [ ] **Step 1: Create AnthropicLLM**

This is ClaudeProvider with the cert logic removed and an optional `http_client` param for subclass injection:

```python
# src/workbench/providers/llm/anthropic.py
import json
import asyncio
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact

EXTRACT_PROMPT = """Extract actionable items from the following content. For each item, provide:
- summary: what needs to be done or noted
- category: one of "action_item", "meeting", "plan_seed", "informational"
- source_context: relevant surrounding context

Return a JSON array of objects with these fields. Return [] if nothing actionable.

Content type: {source_type}
Content:
{raw_text}"""

SCORE_PROMPT = """Score this item for relevance and confidence (0-100 each).

Item: {summary}
Source: {source_type}

User preferences:
{preferences}

Filter rules:
{rules}

Return JSON: {{"relevance": <0-100>, "confidence": <0-100>}}"""


class AnthropicLLM(LLMProvider):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-sonnet-4-20250514"
        http_client: Any = None

        class Config:
            arbitrary_types_allowed = True

    def __init__(self, config: ProviderConfig):
        self._http_client = config.http_client
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )
        self.model = config.model

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]:
        raw_item = RawItem(id="", source_type=source_type, source_label="", raw_text=raw_text)
        response = await self._call_with_retry(
            EXTRACT_PROMPT.format(source_type=source_type, raw_text=raw_text[:10000])
        )
        try:
            items_data = json.loads(self._extract_json(response))
            return [
                ExtractedItem(
                    summary=d["summary"],
                    category=ItemCategory(d.get("category", "action_item")),
                    source_context=d.get("source_context", ""),
                    raw_item=raw_item,
                )
                for d in items_data
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]:
        prefs_text = "\n".join(f"- {f.content}" for f in preference_facts) if preference_facts else "No preferences yet."
        rules_text = "\n".join(f"- {r.pattern} → {r.action}" for r in rules) if rules else "No rules yet."
        response = await self._call_with_retry(
            SCORE_PROMPT.format(
                summary=item.summary,
                source_type=item.raw_item.source_type,
                preferences=prefs_text,
                rules=rules_text,
            )
        )
        try:
            scores = json.loads(self._extract_json(response))
            return int(scores["relevance"]), int(scores["confidence"])
        except (json.JSONDecodeError, KeyError):
            return 50, 30

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
        summary = item.summary
        options = self._template_options(source_type)
        return TriageCard(
            card_content={"summary": summary, "source_type": source_type, "enrichment": enrichment_context},
            options=options,
        )

    def _template_options(self, source_type: str) -> list[TriageOption]:
        base = [
            TriageOption(label="Add todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Add todo (P2)", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
        ]
        if source_type == "diff":
            base.append(TriageOption(label="Never surface diffs like this", action="mute_pattern"))
        elif source_type == "email":
            base.append(TriageOption(label="Never surface emails like this", action="mute_pattern"))
        else:
            base.append(TriageOption(label="Never surface items like this", action="mute_pattern"))
        return base

    async def _call_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    def _extract_json(self, text: str) -> str:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()
```

- [ ] **Step 2: Verify**

```bash
grep -c 'facebook\|plugboard\|rootcanal\|cert_path\|ca_path' src/workbench/providers/llm/anthropic.py
# Expected: 0
grep -c 'class AnthropicLLM' src/workbench/providers/llm/anthropic.py
# Expected: 1
```

- [ ] **Step 3: Commit**

```bash
git add src/workbench/providers/llm/anthropic.py
git commit -m "Add AnthropicLLM: generic LLM provider with direct Anthropic API"
```

---

## Task 3: Clean up SourceAdapter ABC + create external providers

**Goal:** Remove redundant `config` param from `SourceAdapter.poll()`. Create `ConsoleMessenger` and `GitHubSourceAdapter`. Genericize `LLMQueueScorer`.

**Files:**
- Modify: `src/workbench/providers/source/base.py`
- Create: `src/workbench/providers/messenger/console.py`
- Create: `src/workbench/providers/source/github.py`
- Modify: `src/workbench/providers/queue_scorer/llm.py`

- [ ] **Step 1: Update SourceAdapter ABC**

```python
# src/workbench/providers/source/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from workbench.models import RawItem


class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, since: datetime | None = None) -> list[RawItem]: ...
    @abstractmethod
    def adapter_type(self) -> str: ...

    async def close(self) -> None:
        pass
```

- [ ] **Step 2: Create ConsoleMessenger**

```python
# src/workbench/providers/messenger/console.py
from uuid import uuid4

from pydantic import BaseModel

from workbench.providers.messenger.base import Messenger


class ConsoleMessenger(Messenger):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def send_card(self, card_text: str) -> str:
        msg_id = f"console-{uuid4()}"
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}")
        print(f"Respond via: workbench triage")
        print(f"  or: curl -X POST http://localhost:8421/api/triage/respond -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' -d '{{\"card_id\": \"...\", \"choice\": 1}}'")
        return msg_id

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        return []
```

- [ ] **Step 3: Create GitHubSourceAdapter**

```python
# src/workbench/providers/source/github.py
import asyncio
import json
from datetime import datetime

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter


class GitHubSourceAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        repos: list[str] = []

    def __init__(self, config: ProviderConfig):
        self.repos = config.repos

    def adapter_type(self) -> str:
        return "github"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        items = []
        for repo in self.repos:
            prs = await self._gh_json("pr", "list", "--repo", repo,
                                       "--json", "number,title,updatedAt,url,author")
            for pr in prs:
                items.append(RawItem(
                    id=f"gh-pr-{repo}-{pr['number']}",
                    source_type="github",
                    source_label=f"PR #{pr['number']} — {pr['title']}",
                    raw_text=json.dumps(pr),
                    urgency_signals={"type": "pull_request"},
                ))

            issues = await self._gh_json("issue", "list", "--repo", repo,
                                          "--json", "number,title,updatedAt,url,author")
            for issue in issues:
                items.append(RawItem(
                    id=f"gh-issue-{repo}-{issue['number']}",
                    source_type="github",
                    source_label=f"Issue #{issue['number']} — {issue['title']}",
                    raw_text=json.dumps(issue),
                    urgency_signals={"type": "issue"},
                ))
        return items

    async def _gh_json(self, *args) -> list[dict]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return []
            return json.loads(stdout.decode())
        except Exception:
            return []
```

- [ ] **Step 4: Genericize LLMQueueScorer**

Rewrite `src/workbench/providers/queue_scorer/llm.py` — strip cert logic, add optional `http_client`:

```python
# src/workbench/providers/queue_scorer/llm.py
import json
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers.queue_scorer.base import QueueScorer

URGENCY_PROMPT = """Rate the urgency of processing this content on a scale of 0-100.
Higher = more urgent (needs immediate attention).
Lower = can wait (informational, low priority).

Consider these signals from the source system:
{signals}

Content (first 2000 chars):
{content}

Return only a JSON object: {{"urgency": <0-100>}}"""


class LLMQueueScorer(QueueScorer):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-haiku-4-5-20251001"
        http_client: Any = None

        class Config:
            arbitrary_types_allowed = True

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        self._http_client = config.http_client
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )

    async def score_urgency(self, raw_text: str, urgency_signals: dict) -> int:
        signals_text = json.dumps(urgency_signals, indent=2) if urgency_signals else "None"
        prompt = URGENCY_PROMPT.format(signals=signals_text, content=raw_text[:2000])
        try:
            response = await self.client.messages.create(
                model=self.model, max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            return max(0, min(100, int(data["urgency"])))
        except Exception:
            return 50

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
```

- [ ] **Step 5: Verify no Meta references in new/modified files**

```bash
grep -c 'facebook\|plugboard\|rootcanal\|cert_path\|dcat' \
  src/workbench/providers/source/github.py \
  src/workbench/providers/messenger/console.py \
  src/workbench/providers/queue_scorer/llm.py \
  src/workbench/providers/source/base.py
# Expected: all 0
```

- [ ] **Step 6: Commit**

```bash
git add src/workbench/providers/source/base.py \
  src/workbench/providers/messenger/console.py \
  src/workbench/providers/source/github.py \
  src/workbench/providers/queue_scorer/llm.py
git commit -m "Add ConsoleMessenger, GitHubSourceAdapter, genericize LLMQueueScorer, clean up SourceAdapter ABC"
```

---

## Task 4: Create `workbench triage` CLI command

**Goal:** Add an interactive CLI triage command that reads from stdin.

**Files:**
- Create: `src/workbench/cli.py`
- Modify: `pyproject.toml` (entry point)

- [ ] **Step 1: Create cli.py**

```python
# src/workbench/cli.py
import argparse
import json
import sys

import httpx


def triage(server_url: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = httpx.get(f"{server_url}/api/triage/pending", headers=headers)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text}")
        return

    cards = resp.json()
    if not cards:
        print("No pending triage cards.")
        return

    print(f"\n{len(cards)} card(s) pending triage.\n")

    for i, card in enumerate(cards):
        content = card.get("card_content", {})
        options = card.get("options", [])
        source = content.get("source_type", "unknown")
        summary = content.get("summary", "Unknown item")

        print(f"--- Card {i + 1}/{len(cards)} ---")
        print(f"[{source}] {summary}")
        print()
        for j, opt in enumerate(options, 1):
            print(f"  {j}. {opt['label']}")
        print(f"  s. Skip remaining")
        print()

        choice = input("Your choice: ").strip().lower()
        if choice == "s":
            print("Skipped remaining cards.")
            break

        try:
            choice_num = int(choice)
            if 1 <= choice_num <= len(options):
                resp = httpx.post(
                    f"{server_url}/api/triage/respond",
                    headers=headers,
                    json={"card_id": card["id"], "choice": choice_num},
                )
                if resp.status_code == 200:
                    action = resp.json().get("action", "unknown")
                    print(f"  → {action}\n")
                else:
                    print(f"  Error: {resp.status_code}\n")
            else:
                print(f"  Invalid choice. Skipping.\n")
        except ValueError:
            print(f"  Invalid input. Skipping.\n")


def serve():
    import uvicorn
    from workbench.config import load_config
    import os
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    config = load_config(config_path, override_path)
    uvicorn.run("workbench.main:app", host="0.0.0.0", port=config.server.port,
                reload=config.server.debug)


def main():
    parser = argparse.ArgumentParser(prog="workbench", description="Workbench Intelligence Feed")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the server")

    triage_parser = subparsers.add_parser("triage", help="Interactive triage from stdin")
    triage_parser.add_argument("--server", default="http://localhost:8421", help="Server URL")
    triage_parser.add_argument("--token", default=None, help="API token (or set WORKBENCH_API_TOKEN)")

    args = parser.parse_args()

    if args.command == "serve":
        serve()
    elif args.command == "triage":
        import os
        token = args.token or os.environ.get("WORKBENCH_API_TOKEN", "")
        if not token:
            print("Error: --token or WORKBENCH_API_TOKEN required", file=sys.stderr)
            sys.exit(1)
        triage(args.server, token)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update pyproject.toml entry point**

Change the `[project.scripts]` section:

```toml
[project.scripts]
workbench = "workbench.cli:main"
```

- [ ] **Step 3: Commit**

```bash
git add src/workbench/cli.py pyproject.toml
git commit -m "Add workbench CLI: serve and interactive triage commands"
```

---

## Task 5: Delete Meta-specific files from workbench

**Goal:** Remove all Meta-internal code from the public repo. These files now live in workbench-meta.

**Files:**
- Delete: `src/workbench/providers/llm/claude.py`
- Delete: `src/workbench/providers/messenger/google_chat.py`
- Delete: `src/workbench/providers/source/phabricator.py`
- Delete: `src/workbench/providers/source/email_gmail.py`
- Delete: `src/workbench/lib/google_api.py`
- Delete: `docs/memory/` (already in Claude project memory)

- [ ] **Step 1: Delete files**

```bash
rm src/workbench/providers/llm/claude.py
rm src/workbench/providers/messenger/google_chat.py
rm src/workbench/providers/source/phabricator.py
rm src/workbench/providers/source/email_gmail.py
rm -rf src/workbench/lib/
rm -rf docs/memory/
```

- [ ] **Step 2: Verify no Meta references remain in src/**

```bash
grep -rn -i -E '(facebook|plugboard|x2p|dcat|/var/facebook|rootcanal|devgpu|\.lla[0-9])' \
  --include='*.py' src/ | grep -v '__pycache__/'
# Expected: 0 results
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "Remove Meta-specific providers and files (moved to workbench-meta)"
```

---

## Task 6: Update config.example.yml with external defaults

**Goal:** Replace Meta-specific defaults in config.example.yml with external defaults.

**Files:**
- Modify: `config.example.yml`

- [ ] **Step 1: Rewrite config.example.yml**

```yaml
# config.example.yml — copy to config.yml and edit
version: "0.1.0"

server:
  port: 8421
  debug: false
  api_token: ${oc.env:WORKBENCH_API_TOKEN,change-me}

storage:
  postgres_dsn: ${oc.env:WORKBENCH_POSTGRES_DSN,postgres://workbench:workbench@localhost:5432/workbench}

llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  model: claude-sonnet-4-20250514

queue:
  scorer:
    class: workbench.providers.queue_scorer.llm.LLMQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY}
    model: claude-haiku-4-5-20251001
  worker_concurrency: 2
  max_attempts: 3
  base_delay_seconds: 5

triage:
  daily_cap: 20
  expiry_days: 7
  timeout_minutes: 30

pipeline:
  include_threshold: 70
  drop_threshold: 30
  confidence_threshold: 70

scheduler:
  poll_interval_minutes: 15
  morning_briefing_hour: 9

messenger:
  class: workbench.providers.messenger.console.ConsoleMessenger

sources: []
# Example GitHub source:
# sources:
#   - class: workbench.providers.source.github.GitHubSourceAdapter
#     repos:
#       - "owner/repo"

enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher

memory:
  class: workbench.memory.noop.NoopMemoryLayer
```

- [ ] **Step 2: Verify no Meta references**

```bash
grep -i 'plugboard\|facebook\|gchat\|phabricator\|devgpu' config.example.yml
# Expected: 0 results
```

- [ ] **Step 3: Update pyproject.toml — remove unused deps**

Remove `pydantic-settings` and `aiosqlite` from dependencies (they're no longer used):

```bash
# Edit pyproject.toml: remove these two lines from dependencies:
#     "pydantic-settings>=2.0",
#     "aiosqlite>=0.20",
```

- [ ] **Step 4: Commit**

```bash
git add config.example.yml pyproject.toml
git commit -m "Update config for external defaults, remove unused deps"
```

---

## Task 7: Genericize docs + add LICENSE + README

**Goal:** Strip Meta-internal references from CLAUDE.md and CONTEXT.md. Write README.md for OSS audience. Add MIT LICENSE.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CONTEXT.md`
- Create: `README.md`
- Create: `LICENSE`
- Delete: `docs/specs/`, `docs/adr/`, `docs/superpowers/`, `docs/plans/` (moved to workbench-meta/docs/original/)

- [ ] **Step 1: Move internal docs to workbench-meta**

```bash
cp -r docs/specs ~/workspace/workbench-meta/docs/original/
cp -r docs/adr ~/workspace/workbench-meta/docs/original/
cp -r docs/superpowers ~/workspace/workbench-meta/docs/original/
cp -r docs/plans ~/workspace/workbench-meta/docs/original/
rm -rf docs/specs docs/adr docs/superpowers docs/plans
```

- [ ] **Step 2: Rewrite CLAUDE.md**

Replace the entire file with a genericized version. Remove all references to: Plugboard, devgpu, Podman-specific deployment, Zep, Google Chat, Phabricator, Meta Tasks, Workplace, SEVs, Oncall. Keep the project structure, development commands, and design decisions that are framework-level.

The genericized CLAUDE.md should describe Workbench as a "personal intelligence feed" without Meta-specific sources or deployment context. This is a substantial rewrite — read the current CLAUDE.md and produce a clean version focused on the OSS user experience.

- [ ] **Step 3: Rewrite CONTEXT.md**

Replace Meta-specific terms:
- "Google Chat" → "the configured messenger"
- "Card V2" references → remove
- "Meta Tasks" ambiguity → remove
- Phabricator/SEV/Workplace examples → GitHub PR/issue examples
- XDB/devserver → remove
- Keep all framework concepts (Item, Triage Card, Pipeline Job, etc.)

- [ ] **Step 4: Create LICENSE**

```
MIT License

Copyright (c) 2026 Anshul Verma

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: Create README.md**

Write a concise README for the OSS audience covering: what Workbench is, quickstart (pip install, config, podman compose up, curl /health), architecture overview, provider system, configuration, CLI usage.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Genericize docs, add MIT LICENSE and README"
```

---

## Task 8: Fix tests and update main.py references

**Goal:** Update any test files and main.py references that point to deleted Meta providers. Ensure all tests pass.

**Files:**
- Modify: `tests/test_claude_provider.py` → rename/update for AnthropicLLM
- Modify: `tests/test_google_chat.py` → delete (provider moved to meta)
- Modify: `tests/test_api.py` → fix for new config system
- Modify: `src/workbench/main.py` — verify no references to deleted files

- [ ] **Step 1: Rename test_claude_provider.py to test_anthropic_llm.py**

Update imports from `ClaudeProvider` to `AnthropicLLM`, update constructor to use `ProviderConfig`.

- [ ] **Step 2: Delete test_google_chat.py**

```bash
rm tests/test_google_chat.py
```

- [ ] **Step 3: Rewrite test_api.py for new config system**

The current test_api.py imports `Settings` (old pydantic-settings) and `ClaudeProvider`. Rewrite it to work with the new config system — set `WORKBENCH_CONFIG` env var to a test config file.

- [ ] **Step 4: Run all tests**

```bash
WORKBENCH_CONFIG=config.example.yml ANTHROPIC_API_KEY=test-key \
  /tmp/workbench-venv/bin/python3 -m pytest tests/ -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Update tests for generic providers, fix test_api for new config"
```

---

## Task 9: Security scan + git history rewrite

**Goal:** Ensure zero Meta-internal references in the repo. Rewrite git history to clean commit messages.

**Files:**
- No files changed — git operations only

- [ ] **Step 1: Run security scan**

```bash
grep -rn -i -E '(facebook|meta\.com|fbsource|plugboard|x2p|dcat|/var/facebook|rootcanal|devgpu|\.lla[0-9]|\.prn[0-9]|\.ftw[0-9]|\.scu[0-9]|conduit|phabricator|workplace|intern\.fb)' \
  --include='*.py' --include='*.yml' --include='*.yaml' --include='*.md' \
  --include='*.txt' --include='*.toml' --include='*.json' --include='*.cfg' \
  --include='*.ini' --include='*.sh' \
  . | grep -v '.git/' | grep -v '__pycache__/' | grep -v '.venv/'
```

Expected: zero results. If any hits, fix them before proceeding.

- [ ] **Step 2: Rewrite git history**

Use interactive rebase to clean all commit messages:

```bash
git rebase -i --root
```

For each commit, clean the message:
- Remove Meta Task numbers (T273284990, etc.)
- Remove plugboard URLs
- Remove devgpu hostnames
- Remove "ADR 0005/0006/0007/0008" references (these ADRs won't exist in the public repo)
- Keep the commit structure and logical descriptions

- [ ] **Step 3: Re-run security scan after rebase**

Same grep as Step 1. Must return zero results.

- [ ] **Step 4: Verify tests still pass after rebase**

```bash
/tmp/workbench-venv/bin/python3 -m pytest tests/ -v --tb=short
```

---

## Task 10: Push to GitHub + verify on devvm

**Goal:** Create the GitHub repo, push, clone on the new devvm, verify it works.

- [ ] **Step 1: Create GitHub repo**

```bash
gh repo create anshulverma/workbench --public --description "Personal intelligence feed — ingests from sources, filters noise adaptively, triages via interactive cards"
```

- [ ] **Step 2: Push**

```bash
git remote add origin git@github.com:anshulverma/workbench.git
git push -u origin main
```

- [ ] **Step 3: Verify on devvm — clone and install**

On devvm14884:

```bash
git clone git@github.com:anshulverma/workbench.git ~/workspace/workbench
cd ~/workspace/workbench
pip install -e ".[dev]"
```

- [ ] **Step 4: Verify — start PG and run migrations**

```bash
cp config.example.yml config.yml
# Edit config.yml: set ANTHROPIC_API_KEY
podman compose up -d postgres
sleep 5
alembic upgrade head
```

- [ ] **Step 5: Verify — run tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Verify — start server**

```bash
workbench serve
# In another terminal:
curl http://localhost:8421/health
```

Expected: `{"status":"ok","version":"0.1.0","queue":{...}}`

- [ ] **Step 7: Verify — interactive triage**

```bash
# Submit content for processing
curl -X POST http://localhost:8421/api/process \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "Review PR #42 — auth middleware refactor", "source_type": "github"}'

# Run interactive triage
workbench triage --token <token>
```

- [ ] **Step 8: Commit workbench-meta and set up dotsync2**

```bash
cd ~/workspace/workbench-meta
git add -A
git commit -m "Update after public repo split"
# Set up dotsync2 sync for ~/workspace/workbench-meta
```

---

## What's Next

After the split is verified:
- **Phase 1b**: Stand up Zep, implement `ZepMemoryLayer`, wire preferences
- **Discord messenger**: Add `DiscordMessenger` to the public repo for richer external experience
- **GitHub Actions CI**: Lint + type check + test (Python 3.11-3.13 matrix)

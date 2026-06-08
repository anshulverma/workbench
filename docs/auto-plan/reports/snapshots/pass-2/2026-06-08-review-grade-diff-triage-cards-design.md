# Review-Grade Diff Triage Cards — Design Spec

## Context

Today the workbench-meta Phabricator Source Adapter runs `meta phabricator.diff list` and writes only metadata (number, title, updated, status, author) into `RawItem.raw_text`; there is no diff body and no `source_type=="diff"` Composite Enricher branch, so a diff Triage Card shows a generic LLM summary with no code. The foundational pipeline renders every Triage Card through `llm.generate_triage_card()` into an untyped `TriageCard.card_content` dict and flattens it with `format_card_for_chat()`, so there is no place to carry structured, code-bearing sections and no way for a source to control its own card treatment. This feature introduces a source-pluggable presentation layer (Card Presenter), a typed Card Content Schema, a Diff Enricher that lazily fetches and curates Diff Hunks, and a Triage Card Detail View — implementing Phabricator (`source_type="diff"`) first while leaving every other source a clean plug-in path, optimized for FAST triage rather than rebuilding Phabricator.

## Goals

1. **Pluggable** — Introduce a `CardPresenter` ABC with a `CompositeCardPresenter` that routes by `item.source_type` and falls back to `PlainCardPresenter`, built from a `presentation.providers` config list.
2. **Typed** — Define a source-agnostic `DiffCardContent` Card Content Schema (discriminator `content_schema="diff.v1"`) nested under `TriageCard.card_content['sections']` with no Alembic migration.
3. **Separated** — Keep content generation (LLM, memory) in a registered `CardContentGenerator` and make `CardPresenter` a pure deterministic renderer producing a transport-neutral `CardMessage`.
4. **Contextual** — Add a Meta Diff Enricher that lazily fetches the diff in deep mode, applies Path Pre-skip then LLM curation, and emits `curated_hunks`, `entity_refs`, metadata, and `diff_url` as Enrichment context.
5. **Two-surface** — Render rich chat server-side (cardsV2 + threaded hunks) via `GoogleChatMessenger` and render client-side in a Triage Card Detail View from the raw structured `card_content` JSON served by a new detail API.
6. **Safe** — Degrade to `PlainCardPresenter` and summary-only cards on any fetch, generation, validation, or presenter failure, never blocking triage, with no data migration (forward-only).

## Architecture

```
                          FOUNDATIONAL (workbench)                          META OVERLAY (workbench_meta)
                                                                            
  Ingestion Queue                                                           PhabricatorSource.poll()  (metadata only, fetch-only)
        |                                                                          |
        v                                                                          v
  Pipeline Job ----> CompositeEnricher.enrich(source_type) ----------------> DiffEnricher (deep mode)
        |                  (default StubEnricher)                              1. fetch diff (lazy)
        |                                                                      2. Path Pre-skip
        |                                                                      3. LLM curate hunks
        |                                                                      -> enrichment context {metadata, entity_refs,
        |                                                                          curated_hunks, skipped_files, truncated, revision_id}
        v
  generate_card(llm, item, enrichment, source_type, memory)
        |  gather memory_context (entity 5 / preference 20 / relationship 10)
        |  dispatch CardContentGenerator by source_type ----------------------> DiffCardContentGenerator (Opus 4.8, single
        |  (default = llm.generate_triage_card)                                  json_schema call -> 5 sections, DiffCardContent)
        v
  TriageCard.card_content = {content_schema:"diff.v1", sections:{...}, card_body, summary}
        |
        v
  CompositeCardPresenter.render(card, item) ---------------------------------> DiffCardPresenter (deterministic, no LLM/memory)
        |  default PlainCardPresenter (wraps format_card_for_chat)             -> CardMessage{header, sections, links,
        |  per-delegate try/except -> presenter_failure -> Plain fallback          options, thread_hunks}
        v
  scheduler._manage_triage_queue_inner: messenger.send_card(CardMessage)
        |                                                                      GoogleChatMessenger.send_card overrides:
  base Messenger.render_to_text(CardMessage) (console fallback) <-------------- translate CardMessage -> cardsV2 + threadKey,
        |                                                                       post parent + <=3 hunk replies
        v
  poll_responses (thread polling) -> numbered text reply -> Triage Response

  API: GET /api/triage/cards/{card_id} -> full TriageCard JSON (sections raw)
  UI: HashRouter #/triage/:cardId -> TriageDetail (CSS-only +/- diff, expand defaults)
```

The Diff Enricher fetches and curates code lazily during deep-mode Enrichment so `poll()` stays metadata-only; the registered Diff Card Content Generator turns curated hunks plus memory context into typed `DiffCardContent` in one structured LLM call; the `DiffCardPresenter` deterministically renders that into a transport-neutral `CardMessage` that `GoogleChatMessenger` translates to cardsV2 with threaded hunks, while the UI Detail View renders the same raw sections client-side.

## Card Presenter Abstraction (foundational)

The `CardPresenter` ABC defines a single deterministic render contract; the `CompositeCardPresenter` routes by `item.source_type` against a dict of delegates built from the `presentation.providers` config list, with `PlainCardPresenter` as the universal default. It lives in `src/workbench/pipeline/presenter.py` and is built from config (NOT a Provider Registry entry point), mirroring how `CompositeEnricher` is built from `enrichment.providers` (d1).

A `CardPresenter` is a pure, deterministic renderer: it performs no LLM calls and no Memory Layer queries. It reads the already-generated typed sections from `TriageCard.card_content['sections']` and emits a transport-neutral `CardMessage`. `PlainCardPresenter` wraps the legacy `format_card_for_chat()` output as a single-section `CardMessage` and is the fallback whenever structured sections are absent or invalid (d2).

```python
# src/workbench/pipeline/presenter.py
from abc import ABC, abstractmethod
from workbench.models import TriageCard, ExtractedItem, CardMessage

class CardPresenter(ABC):
    @abstractmethod
    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage: ...

class PlainCardPresenter(CardPresenter):
    """Universal fallback. Wraps legacy format_card_for_chat output."""
    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage: ...

class CompositeCardPresenter(CardPresenter):
    def __init__(self, by_source_type: dict[str, CardPresenter], default: CardPresenter):
        self._by_source_type = by_source_type
        self._default = default  # PlainCardPresenter

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        delegate = self._by_source_type.get(item.source_type, self._default)
        try:
            return delegate.render(card, item)
        except Exception as exc:
            logger.warning("presenter_failure", source_type=item.source_type,
                           presenter=type(delegate).__name__, item_id=item.id, exc=str(exc))
            return self._default.render(card, item)
```

Failure and fallback rules:

| Condition | Behavior | Log event |
| --- | --- | --- |
| `source_type` not in `presentation.providers` | route to `PlainCardPresenter` | `presenter_fallback` |
| `card_content['sections']` missing / `content_schema` absent | `PlainCardPresenter` via `card_body`/`summary` | `presenter_fallback` |
| section validation against schema fails | `PlainCardPresenter` via `card_body`/`summary` | `presenter_content_invalid` |
| in-flight cards generated before this feature | no `sections` -> `PlainCardPresenter` | `presenter_fallback` |
| delegate `render()` raises | per-delegate try/except -> `PlainCardPresenter` | `presenter_failure` |
| `presentation` section absent in config | `CompositeCardPresenter` empty -> all `source_type` -> `PlainCardPresenter` | none (steady state) |

All structured-section access is null-safe; a missing `presentation` section yields an empty `CompositeCardPresenter` mapping so every `source_type` resolves to `PlainCardPresenter` (d6, d41, d42).

## Card Content Schema (foundational)

The Card Content Schema is a typed pydantic shape persisted under the existing untyped `TriageCard.card_content` dict column — no Alembic migration. The generator writes `card_content['content_schema'] = "diff.v1"` as the discriminator and `card_content['sections']` as the serialized `DiffCardContent`, while keeping legacy `card_body` and `summary` keys for the plain fallback path (d3).

```python
# src/workbench/models.py  (DiffCardContent is source-agnostic, populated by Meta)
class DiffMetadata(BaseModel):
    author: str
    team: str | None = None      # derived from author entity via memory; omit line if None (d45)
    status: str

class DiffRisk(BaseModel):
    factors: list[str] = Field(default_factory=list)
    watch_outs: list[str] = Field(default_factory=list)

class DiffHunkSection(BaseModel):
    file: str
    header: str          # e.g. "@@ -10,7 +10,9 @@"
    code: str            # unified-diff text, +/- prefixed lines
    annotation: str      # one-line LLM note on what this hunk does
    expandable: bool = True
    rank: int            # per-hunk rank; chat slices top 3, UI shows full set (d21)

class DiffCardContent(BaseModel):
    metadata: DiffMetadata
    summary: str
    risk: DiffRisk
    why_care: str
    hunks: list[DiffHunkSection] = Field(default_factory=list)
```

`card_content` envelope shape persisted on `TriageCard`:

```json
{
  "content_schema": "diff.v1",
  "sections": { "metadata": {...}, "summary": "...", "risk": {...}, "why_care": "...", "hunks": [...] },
  "card_body": "...legacy flattened text for plain fallback...",
  "summary": "...legacy short summary for plain fallback..."
}
```

The schema lives FOUNDATIONAL because the shape is source-agnostic; Meta only populates it. Validation failures route to the plain path via `card_body`/`summary` (d3, d4, d6).

## Card Content Generator (foundational interface, Meta diff generator)

Content generation is a registered `CardContentGenerator` selected by `source_type` via dynamic import, exactly like enrichers. The foundational `generate_card()` dispatches to the registered generator without ever naming `"diff"`; when no generator is registered for a `source_type`, the default generator is `llm.generate_triage_card`, preserving today's behavior (d14).

```python
# src/workbench/pipeline/content_generator.py  (foundational interface)
from abc import ABC, abstractmethod

class CardContentGenerator(ABC):
    @abstractmethod
    async def generate(self, llm, item: ExtractedItem, enrichment_context: dict,
                       memory_context: dict | None) -> dict:
        """Return a card_content envelope dict (content_schema + sections + card_body + summary)."""
```

The Meta `DiffCardContentGenerator` makes a single structured LLM call (Anthropic `json_schema` output) producing all five sections (`metadata`, `summary`, `risk`, `why_care`, `hunks`) in one request to preserve cross-section grounding, with `max_tokens=8000`, on model `claude-opus-4-8` (Opus 4.8); the Queue Scorer stays on Haiku (d15, d16).

Personalization reuses the existing `memory_context` already gathered in `generate_card` (entity facts cap 5, preference facts cap 20, relationships cap 10) — no new Memory Layer queries. Empty memory yields a generic summary through the same code path (no separate branch) (d17).

Hunk token bounding is a documented contract between enricher and generator: the Diff Enricher owns budget-controlled selection (Path Pre-skip + caps), and the generator trusts the pre-bounded `curated_hunks` but counts defensively via `messages.count_tokens` before the call (d18).

Risk-hallucination mitigation: the system instruction states "cite only changes present in the provided hunks"; the `json_schema` output enforces shape; on refusal or parse failure the generator returns a summary-only envelope (sections omitted -> plain path) (d19).

Re-score reuse: on re-scoring an existing card, reuse the already-generated content and re-score relevance only. Regenerate content only when the diff revision changed, keyed by the revision id stored on the card from enrichment (d20, d46).

## Diff Enricher (workbench-meta)

The Meta `DiffEnricher` is registered for `source_type="diff"` in `enrichment.providers` and runs inside `CompositeEnricher.enrich()`. Diff fetch is LAZY and happens only in deep mode here, never in `poll()`; the Phabricator Source Adapter stays metadata-only and fetch-only (d7). The fetched diff is produced as Enrichment context and never written to `RawItem.raw_text`, avoiding the `raw_text[:10000]` truncation — no RawItem schema change (d8).

Fetch command (d9): the recommended command is `meta phabricator.diff get <number> --output json`; the fallback is a raw unified-diff fetch and parse. The exact JSON schema of `meta phabricator.diff get` is UNCONFIRMED, so the implementation plan carries a verification task to confirm it before wiring the parser; this spec states the recommended approach plus fallback, not a guessed schema.

Fetch execution and failure handling (d12): use `asyncio.create_subprocess_exec` with a 30s timeout. On timeout, nonzero exit, or missing THRIFT_TLS cert, degrade to shallow context (metadata + entity_refs only) and never raise.

Noise pre-filtering is split (d11): a cheap **Path Pre-skip** drops lockfiles, `__generated__` paths, and vendored directories — recorded in `skipped_files` with a reason — **before** the LLM curates the remainder. Path Pre-skip is a token-budget guard distinct from the LLM noise filter (which is LLM judgment, not regex).

Budget caps (d13): max files curated default 40, max payload ~200KB; past the cap, truncate and set `truncated=true`. Caps are configurable via the Enrichment budget controls.

Enrichment context shape (d10):

```python
{
  "metadata": {"author": "...", "team": "...", "status": "...",
               "repo": "...", "base_rev": "...", "diff_url": "https://.../D12345"},
  "entity_refs": [
    (EntityType.PERSON, "phabricator:<phid>"),   # attrs: platform_uid, username, name
    (EntityType.REPO,   "phabricator:<callsign>")  # attrs: repo callsign
  ],
  "curated_hunks": [ {"file": "...", "header": "@@ ...", "code": "...", "rank": 1} ],
  "skipped_files": [ {"path": "yarn.lock", "reason": "lockfile"} ],
  "truncated": false,
  "revision_id": "<phabricator revision id>"   # staleness key for regeneration (d46)
}
```

`DiffMetadata.team` is derived from the author Entity Ref via the org chart through memory/enrichment; if unavailable, the team line is omitted from the card (d45). The `diff_url` captured here flows into `card_content` for the prominent "View in Phabricator" link (d33).

## Messenger Interface and cardsV2 Rendering (foundational interface, Meta GChat)

The `Messenger.send_card` signature changes to accept a structured `CardMessage` and return a `message_id`. The base `Messenger` provides a default `render_to_text(CardMessage) -> str` for console and other non-rich messengers; `GoogleChatMessenger` overrides `send_card` to translate to cardsV2 with threads (d22).

```python
# src/workbench/models.py
class CardLink(BaseModel):
    label: str
    url: str

class CardSection(BaseModel):
    title: str
    body: str          # plain or monospace-marked text; presenter decides
    monospace: bool = False

class ThreadHunk(BaseModel):
    file: str
    header: str
    code: str          # +/- prefixed unified diff
    rank: int

class CardMessage(BaseModel):
    header: str
    sections: list[CardSection] = Field(default_factory=list)
    links: list[CardLink] = Field(default_factory=list)        # e.g. View in Phabricator (d33)
    options: list[TriageOption] = Field(default_factory=list)  # numbered text reply options
    thread_hunks: list[ThreadHunk] = Field(default_factory=list)

# src/workbench/providers/messenger/base.py
class Messenger(ABC):
    @abstractmethod
    async def send_card(self, card: CardMessage) -> str: ...
    @abstractmethod
    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]: ...
    def render_to_text(self, card: CardMessage) -> str:
        """Default flatten for console / non-rich transports."""
        ...
```

The presenter builds a transport-neutral `CardMessage`; `GoogleChatMessenger` is the only place that knows cardsV2 wire JSON — it translates `CardMessage` into cardsV2 widgets (transport-only concern) (d23).

Triage interaction (d24): numbered text replies stay the source of truth. cardsV2 carries link buttons (dashboard, Phabricator) only — NOT interactive triage buttons (those would require event ingress). Replies are captured by `poll_responses` thread polling.

Threading (d25): post the parent message with a client-generated `thread.threadKey` using `REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`; capture `message.name` and `thread.name`. Post up to 3 hunk replies into the same `threadKey`. Hunks render as monospace cardsV2 widgets, NOT markdown triple-backtick fences.

Chat size caps (d26): summary <= 800 chars; risk and why-care <= 600 each; each hunk reply <= 1500 chars truncated with `...(full diff in dashboard)`; max 3 hunks (chat slices the top 3 by rank, d21).

Response polling (d27): store the parent `message_id` and `threadKey`; poll the thread; capture replies to the parent or to any hunk. No matching-logic change beyond polling the thread.

Thread-reply resilience (d28): hunk replies are best-effort — the parent is the source of truth, so on failure log and continue. A fast reply is captured by polling; sequential awaits plus the 3-hunk cap keep posts under quota; a 429 skips the remaining hunk replies.

## Detail API (foundational)

A new authenticated endpoint serves the full structured card for the UI.

```
GET /api/triage/cards/{card_id}
-> 200 TriageCard{ id, item_id, card_content, options, relevance_score, confidence_score, status }
-> 404 when card_id not found
```

This is an id lookup, so ADR 0016 (read-API empty-state contract governing collections) does not apply; a miss returns 404. Bearer auth applies as on all endpoints except `/health` (d29).

## Triage Card Detail View (foundational UI)

A new `#/triage/:cardId` HashRouter param route renders a `TriageDetail` page. The Triage list cards gain a "Review" link to it; the route is a drill-down and is NOT added to the sidebar (d30).

The page renders Diff Hunks client-side from the raw structured `card_content` JSON with CSS-only `+`/`-` line coloring inside `<pre>`, driven by server-provided structured lines — no syntax-highlight or diff library is added (d31).

Expand defaults (d32): metadata and summary always visible; risk and why-care expanded by default; hunks collapsed per-file with an expand control, auto-expanding the highest-severity (or first) hunk; memory context collapsed.

Phabricator linking (d33): the captured `diff_url` renders as one prominent top-level "View in Phabricator" link; per-file anchors are deferred (anchor scheme unconfirmed).

UI shows the full curated hunk set (cap ~15), configurable via `presentation` `max_hunks`, while chat shows the top 3 (d21).

Data flow (d34): a `useTriageCard(id)` hook calls `apiGet`, reuses the five-state pattern, and does not poll. The detail page reuses the existing `useTriage` respond/confirm mutations through a shared action component, invalidates both the card and pending queries on respond, and renders read-only when the card is `responded` or `expired`.

Type generation (d35): regenerate `ui/src/lib/api-types.ts` via `npm run gen:api` against the running server using the standalone /tmp Node v20 toolchain; the `useTriageCard` hook consumes the generated `TriageCard` type.

## Presentation Config (foundational)

A new top-level `presentation` section maps `source_type` to a presenter class plus per-source config; `CompositeCardPresenter` is built from this list with `PlainCardPresenter` as default (d36).

```yaml
# config.yml
presentation:
  providers:
    - source_type: diff
      class: workbench_meta.presentation.diff_presenter.DiffCardPresenter
      config:
        enabled: true
        max_hunks: 15          # UI cap; chat always slices top 3
        sections: [metadata, summary, risk, why_care, hunks]  # ordered allowlist
        expand_default: [risk, why_care]
```

Per-source UX controls v1 (d37): each presenter config supports `enabled`, `max_hunks`, `sections` (ordered allowlist), and `expand_default`, all in YAML (not hardcoded); unknown keys are ignored.

Hot-reload (d38): presentation is restart-only for v1 and is NOT on the ADR 0013 hot-reload path (which covers sources + messenger only); a future hot-reload extension is documented but out of scope.

Config behavior edge cases:

| Condition | Behavior |
| --- | --- |
| `presentation` absent | `CompositeCardPresenter` empty -> all `source_type` -> `PlainCardPresenter`; structured-section access null-safe (d41) |
| presenter class string not importable | hard error at startup (d43) |
| `source_type` in `presentation` but not in `enrichment` | render available sections, empty-state hunks (d43) |
| unrelated hot-reload event | does not touch presentation (d43) |

Config File version bumps a minor version because `presentation` is a backward-compatible optional section (d40).

## Repo Split (d39)

| Concern | Repo |
| --- | --- |
| `CardPresenter` ABC, `CompositeCardPresenter`, `PlainCardPresenter` | foundational |
| `DiffCardContent` Card Content Schema | foundational |
| `CardContentGenerator` interface + dispatch | foundational |
| `CardMessage` model + `Messenger.send_card(CardMessage)` + `render_to_text` default | foundational |
| cardsV2 transport translation | workbench-meta (`GoogleChatMessenger`) |
| Detail API + Triage Card Detail View + type-gen | foundational |
| Phabricator diff fetch, `DiffEnricher`, `DiffCardPresenter`, `DiffCardContentGenerator`, WIB-GChat specifics | workbench-meta |

## File Changes

### Foundational (`~/workspace/workbench`)

New files:

| File | Purpose |
| --- | --- |
| `src/workbench/pipeline/presenter.py` | `CardPresenter` ABC, `CompositeCardPresenter`, `PlainCardPresenter`, build-from-config |
| `src/workbench/pipeline/content_generator.py` | `CardContentGenerator` ABC + registry dispatch by `source_type` |
| `ui/src/pages/TriageDetail.tsx` | Triage Card Detail View page |
| `ui/src/hooks/useTriageCard.ts` | `useTriageCard(id)` hook (apiGet, five-state, no poll) |
| `ui/src/components/DiffHunks.tsx` | CSS-only `+`/`-` diff renderer + per-file expand |

ADRs already written (one decision area each): `docs/adr/0022-typed-card-content-in-dict.md`, `0023-presenter-renders-chat-ui-renders-json.md`, `0024-diff-fetch-lazy-in-enricher.md`, `0025-per-source-card-content-generator.md`, `0026-cardmessage-structured-messenger-interface.md`, `0027-triage-interaction-stays-text-replies.md`, `0028-css-only-hunk-rendering.md`, `0029-presentation-config-restart-only-v1.md`. (Numbered 0022–0029 because `0021-stable-source-id` was created concurrently.)

Modified files:

| File | Change |
| --- | --- |
| `src/workbench/models.py` | add `DiffMetadata`, `DiffRisk`, `DiffHunkSection`, `DiffCardContent`, `CardLink`, `CardSection`, `ThreadHunk`, `CardMessage` |
| `src/workbench/pipeline/triage.py` | dispatch `CardContentGenerator` by `source_type`; write `content_schema`/`sections`; doc memory caps 5/20/10 |
| `src/workbench/providers/messenger/base.py` | `send_card(CardMessage)`; default `render_to_text(CardMessage)` |
| `src/workbench/providers/messenger/console.py` | use `render_to_text` |
| `src/workbench/pipeline/scheduler.py` | `_manage_triage_queue_inner`: presenter -> `CardMessage` -> `send_card` |
| `src/workbench/config.py` | add `presentation` section; bump Config File minor version |
| `src/workbench/api/triage.py` | add `GET /api/triage/cards/{card_id}` (404 on miss, bearer) |
| `src/workbench/main.py` | build `CompositeCardPresenter` + content generators from `presentation`, attach to `app.state`, pass into scheduler/engine |
| `src/workbench/pipeline/engine.py` | pass content generators into `generate_card` |
| `ui/src/App.tsx` (router) | add `#/triage/:cardId` route |
| `ui/src/pages/Triage.tsx` | add "Review" link per card |
| `ui/src/lib/api-types.ts` | regenerate via `npm run gen:api` |
| `config.example.yml` | document `presentation` section |
| `docs/CONTEXT.md` | add new terms; correct memory caps "without caps" -> 5/20/10 (d44) |

### Meta overlay (`~/workspace/workbench-meta`)

New files:

| File | Purpose |
| --- | --- |
| `workbench_meta/providers/enrichment/diff_enricher.py` | `DiffEnricher` (lazy fetch, Path Pre-skip, LLM curation, budget) |
| `workbench_meta/providers/content/diff_generator.py` | `DiffCardContentGenerator` (Opus 4.8 single json_schema call) |
| `workbench_meta/providers/presentation/diff_presenter.py` | `DiffCardPresenter` (deterministic -> `CardMessage`) |

Modified files:

| File | Change |
| --- | --- |
| `workbench_meta/providers/messenger/gchat.py` | override `send_card`: cardsV2 + thread parent (capture `data.thread`) + <=3 hunk replies via `send_card_message(thread_name=)`; thread polling |
| `workbench_meta/providers/source/phabricator.py` | confirm `poll()` stays metadata-only (no diff fetch) |
| `config.meta.yml` (Meta overlay) | wire `presentation.providers` diff entry; register `diff` enricher (composite form) + content generator |

## Verification

1. With `presentation` absent from config, every Triage Card renders via `PlainCardPresenter` and chat output is byte-identical to today's `format_card_for_chat`.
2. A `presentation` entry whose `class` is not importable causes a hard error at server startup.
3. `DiffEnricher` deep-mode fetch uses `asyncio.create_subprocess_exec` with a 30s timeout; on simulated timeout/nonzero/missing-cert the enrichment context contains only metadata + entity_refs and no exception propagates.
4. Phabricator `poll()` produces a `RawItem` with no diff body in `raw_text`; the diff appears only in enrichment context.
5. Path Pre-skip records `yarn.lock`, `__generated__/*`, and a vendored path in `skipped_files` with reasons before any LLM curation call is made.
6. A diff exceeding 40 files or ~200KB yields `truncated=true` and at most 40 curated hunks.
7. `generate_card` for `source_type="diff"` calls `DiffCardContentGenerator` (one `claude-opus-4-8` `json_schema` call, `max_tokens=8000`) and writes `card_content['content_schema']=="diff.v1"` with all five sections.
8. With empty Memory Layer, the diff card still generates a non-empty `summary` through the same code path (no separate branch).
9. A generator refusal or parse failure produces a summary-only envelope (no `sections`), and the card renders via `PlainCardPresenter`.
10. Re-scoring a card with an unchanged `revision_id` reuses stored content; a changed `revision_id` triggers regeneration.
11. `Messenger.send_card` accepts a `CardMessage`; `ConsoleMessenger` renders via the base `render_to_text` default.
12. `GoogleChatMessenger` posts a parent cardsV2 message with a client-generated `threadKey` plus up to 3 monospace hunk replies in the same thread; a forced 429 on a hunk reply is logged and skipped while the parent succeeds.
13. Chat summary <= 800 chars, risk/why-care <= 600 each, each hunk reply <= 1500 chars truncated with `...(full diff in dashboard)`, max 3 hunks.
14. cardsV2 contains link buttons (dashboard, View in Phabricator) and no interactive triage buttons; a numbered text reply in the thread is captured by `poll_responses`.
15. `GET /api/triage/cards/{card_id}` returns the full `TriageCard` (including `card_content.sections`) with bearer auth and 404 on an unknown id.
16. Navigating to `#/triage/:cardId` renders `TriageDetail`: metadata+summary visible, risk+why-care expanded, hunks collapsed per-file with the highest-severity/first hunk auto-expanded, memory context collapsed.
17. The UI diff renderer colors `+`/`-` lines via CSS only, shows up to `max_hunks` (~15), and adds no syntax-highlight/diff dependency to `package.json`.
18. The Detail View reuses `useTriage` respond/confirm, invalidates card+pending queries on respond, and is read-only when status is `responded`/`expired`.
19. `npm run gen:api` regenerates `ui/src/lib/api-types.ts` with the `cards/{card_id}` shape and `useTriageCard` consumes the generated type.
20. The Config File version is bumped a minor version and the server loads with the new `presentation` section.

## Resolved Questions

1. **Presentation abstraction:** `CardPresenter` ABC + `CompositeCardPresenter` routing by `item.source_type`, default `PlainCardPresenter`, in `src/workbench/pipeline/presenter.py`, built from `presentation.providers`. Built from config (not Provider Registry entry points) to mirror `CompositeEnricher` and keep presentation declarative. (d1)
2. **Responsibility split:** content generation does LLM+memory; `CardPresenter` is a pure deterministic renderer producing a `CardMessage`; `PlainCardPresenter` wraps legacy `format_card_for_chat`. Keeps rendering testable and transport-neutral. (d2)
3. **Card content storage:** keep the `TriageCard.card_content` dict column; nest typed sections under `card_content['sections']` with a `content_schema` discriminator (`"diff.v1"`); no Alembic migration. Reuses the existing column to avoid a migration. (d3)
4. **Diff content schema:** `DiffCardContent{metadata, summary, risk, why_care, hunks}` lives foundational (source-agnostic), populated by Meta. The shape is reusable across sources. (d4)
5. **Two-surface rendering:** presenter renders chat server-side (cardsV2 + threaded hunks); UI renders client-side from raw structured `card_content`. Each surface controls its own affordances. (d5)
6. **Backward compat:** unregistered `source_type` / missing sections / in-flight cards -> `PlainCardPresenter`; log `presenter_fallback`/`presenter_content_invalid`; validation fail -> plain path; forward-only, no data migration. Guarantees safety for existing cards. (d6)
7. **Diff fetch location:** lazy in the Diff Enricher deep mode, never in `poll()`; `poll()` stays metadata-only fetch-only. Keeps ingestion cheap and Source Adapters fetch-only. (d7)
8. **Diff content storage in pipeline:** diff stays out of `raw_text` (avoids `raw_text[:10000]` truncation), produced as enrichment context; no RawItem schema change. Prevents truncation and schema churn. (d8)
9. **Fetch command:** recommended `meta phabricator.diff get <number> --output json`; fallback raw unified-diff fetch+parse; exact schema unconfirmed -> verification task in the plan. States approach honestly rather than guessing a schema. (d9)
10. **Diff enrichment context shape:** `{metadata, entity_refs[(PERSON, REPO)], curated_hunks, skipped_files, truncated, revision_id}` with documented Entity Ref attrs. Gives the generator everything it needs in one structure. (d10)
11. **Noise pre-filtering:** cheap Path Pre-skip (lockfiles, `__generated__`, vendored) recorded in `skipped_files`, then LLM curation of the remainder; Path Pre-skip is a token-budget guard distinct from the LLM noise filter. Saves tokens before invoking the LLM. (d11)
12. **Diff fetch failure:** `asyncio.create_subprocess_exec`, 30s timeout; timeout/nonzero/missing-cert -> degrade to shallow context, never raise. Triage must never break on fetch failure. (d12)
13. **Diff budget caps:** max files 40, max ~200KB; past cap truncate + `truncated=true`; configurable via Enrichment budget. Bounds cost and payload size. (d13)
14. **Content-gen placement:** registered `CardContentGenerator` by `source_type` (dynamic import like enrichers); foundational `generate_card` dispatches without naming `"diff"`; `llm.generate_triage_card` stays the default. Keeps the source-specific generator out of the foundational core. (d14)
15. **LLM call:** single structured `json_schema` call producing all 5 sections; `max_tokens` 8000; preserves cross-section grounding. One call keeps sections mutually consistent. (d15)
16. **Model:** Opus 4.8 (`claude-opus-4-8`) for rich generation; Queue Scorer stays Haiku. Matches quality to task. (d16)
17. **Personalization:** reuse existing `memory_context` (entity, relationships, preference facts); no new memory queries; empty memory -> generic summary, same code path. Avoids extra latency and code branches. (d17)
18. **Hunk token bounding ownership:** enricher applies budget-controlled selection (pre-skip + caps); generator trusts pre-bounded hunks, counts defensively via `messages.count_tokens`. Single owner of selection, defensive guard at the LLM boundary. (d18)
19. **Risk hallucination mitigation:** system instruction "cite only changes present in provided hunks"; structured output enforces shape; refusal/parse-fail -> summary-only card. Limits fabricated risk claims. (d19)
20. **Content reuse on re-score:** reuse generated content; re-score relevance only; regenerate only if the diff revision changed. Avoids redundant expensive generation. (d20)
21. **Chat vs UI hunk count:** generator produces the full curated set with per-hunk `rank`; chat presenter slices top 3; UI shows full set (cap ~15); configurable via `presentation` `max_hunks`. Right density per surface. (d21)
22. **Messenger interface:** `send_card(CardMessage) -> message_id`; base `render_to_text(CardMessage)` default for console/non-rich; `GoogleChatMessenger` overrides to cardsV2+threads. Transport-neutral core with a rich override. (d22)
23. **cardsV2 ownership:** presenter builds transport-neutral `CardMessage`; `GoogleChatMessenger` translates to cardsV2 wire JSON (transport only). Keeps wire format isolated. (d23)
24. **Triage interaction:** numbered text replies remain source of truth; cardsV2 carries link buttons only, not interactive triage buttons (would need event ingress); replies captured by `poll_responses`. Avoids building an event ingress for v1. (d24)
25. **Threading:** parent posted with client-generated `thread.threadKey` (`REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`); capture `message.name` + `thread.name`; <=3 hunk replies in the same threadKey; hunks as monospace cardsV2 widgets, not markdown fences. Keeps hunks attached and readable. (d25)
26. **Chat size caps:** summary <= 800, risk/why-care <= 600 each, hunk reply <= 1500 truncated `...(full diff in dashboard)`, max 3 hunks. Stays within chat readability and quota. (d26)
27. **Response polling:** store parent `message_id` + `threadKey`; poll the thread; replies to parent or hunk captured; no matching-logic change beyond polling the thread. Minimal change to capture threaded replies. (d27)
28. **Thread reply failure / fast reply / rate limit:** hunk replies best-effort (parent is source of truth; log+continue); fast reply captured by polling; sequential awaits + 3-hunk cap stay under quota; 429 -> skip. Resilient without blocking. (d28)
29. **Detail API:** `GET /api/triage/cards/{card_id}` returns the full `TriageCard`; 404 on miss (ADR 0016 governs collections, not id lookups); bearer auth. Standard id-lookup semantics. (d29)
30. **UI route:** HashRouter `#/triage/:cardId` -> `TriageDetail`; Triage list cards get a Review link; not in the sidebar (drill-down). Keeps navigation focused. (d30)
31. **Hunk rendering UI:** CSS-only `+`/`-` line coloring in `<pre>` from server-provided structured lines; no syntax-highlight/diff lib. Avoids a heavy dependency for fast triage. (d31)
32. **UI expand defaults:** metadata+summary always visible; risk+why-care expanded by default; hunks collapsed per-file with expand, auto-expand highest-severity/first hunk; memory context collapsed. Optimizes for fast scanning. (d32)
33. **Phabricator links:** `diff_url` captured by the enricher -> `card_content`; one prominent "View in Phabricator" top-level link; per-file anchors deferred (unconfirmed scheme). One reliable jump-out, defer the rest. (d33)
34. **UI data flow:** `useTriageCard(id)` via `apiGet`, reuse five-state pattern, no polling; detail page reuses `useTriage` respond/confirm via a shared action component; invalidate card+pending on respond; read-only when responded/expired. Reuses existing hooks and patterns. (d34)
35. **OpenAPI type-gen:** regenerate `ui/src/lib/api-types.ts` via `npm run gen:api` against the running server (/tmp Node v20); hook consumes the generated type. Keeps types server-derived. (d35)
36. **Presentation YAML:** top-level `presentation:` with `providers:` list (source_type -> presenter class + per-source config); `CompositeCardPresenter` from the list; default `PlainCardPresenter`. Declarative, matches enrichment config style. (d36)
37. **Per-source UX controls v1:** per-presenter `enabled`, `max_hunks`, `sections` (ordered allowlist), `expand_default`; in YAML not hardcoded; ignore unknown keys. Tunable without code changes. (d37)
38. **Presentation hot-reload:** restart-only for v1 (not the ADR 0013 path); documented future extension. Limits scope; presentation rarely changes. (d38)
39. **Repo split:** foundational owns `CardPresenter` ABC, `CompositeCardPresenter`, diff content schema, content-gen interface, cardsV2 transport in `GoogleChatMessenger`, API, UI, `PlainCardPresenter`; workbench-meta owns Phabricator diff fetch, Diff Enricher, concrete diff presenter + generator wiring, WIB-GChat specifics. Keeps Meta-internal logic in the overlay. (d39)
40. **Config version bump:** minor (backward-compatible optional section). Semver-correct for an additive optional section. (d40)
41. **Default-when-absent:** `presentation` absent -> `CompositeCardPresenter` empty -> all source_types -> `PlainCardPresenter`; structured-section access null-safe. Safe no-config default. (d41)
42. **Presenter failure:** `CompositeCardPresenter` try/except per delegate, log `presenter_failure` (source_type, class, item id, exc), fall back to `PlainCardPresenter`; never block triage. Isolates delegate faults. (d42)
43. **Presentation edge cases:** unknown class -> hard error at startup; `source_type` in presentation but not enrichment -> render available sections, empty-state hunks; unrelated hot-reload doesn't touch presentation. Fail fast on config errors, degrade gracefully on data gaps. (d43)
44. **Memory caps doc drift:** CONTEXT.md says memory "without caps" but code caps entity 5 / preference 20 / relationship 10; document the caps as the real contract. Aligns docs with code. (d44)
45. **DiffMetadata team:** derived from the author Entity Ref (org chart) via memory/enrichment; if unavailable, omit the team line. Avoids guessing team membership. (d45)
46. **Regeneration staleness key:** store the diff `revision_id` on the card; regenerate when the fetched revision is newer than the stored one. Cheap, deterministic staleness check. (d46)

## Out of Scope

- Interactive triage buttons in cardsV2 and any Google Chat event ingress (numbered text replies remain source of truth).
- Hot-reload of the `presentation` section (restart-only for v1).
- Per-file Phabricator deep-link anchors (anchor scheme unconfirmed).
- Syntax-highlight or diff rendering libraries in the UI (CSS-only coloring only).
- Diff content schema versions beyond `diff.v1`.
- Non-Phabricator concrete presenters/generators/enrichers (the abstraction is built; only `diff` is implemented).
- Any Alembic migration or RawItem/TriageCard column schema change.
- Confirming the exact `meta phabricator.diff get` JSON schema (carried as a plan verification task, not resolved here).

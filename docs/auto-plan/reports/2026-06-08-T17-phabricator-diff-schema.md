# T17 RESULT — `meta phabricator.diff` schema (verified in cert container, 2026-06-08)

Verified live (cert env present; real diffs returned). **The plan/spec/ADR assumption `meta phabricator.diff get` is WRONG — there is no `get` action.** Use the commands below in the workbench-meta pass-2 tasks (T18/T23/T24) and update ADR 0032 / the spec accordingly.

## Metadata + change-detection signals (poll() + ChangeDetector) — `phabricator.diff list`
```
meta phabricator.diff list --author-is-me --reviewers-include-me --include-only-open \
  --columns number,status,version,line_count,file_count,comment_count,updated,url -o json
```
JSON objects, keys (all string-valued):
- `number` — e.g. `"D107906277"`. The STABLE id is this verbatim (`stable_id` = the `D<number>` string; strip nothing — it already starts with `D`). Replaces legacy `{number}_{updated}`.
- **`version`** — e.g. `"391103237"`. **This IS `diff_version`** — the active code-diff version id. Changes when new code is uploaded. Opaque; equality-compare old vs new. → `change_type="code_updated"` (ADR 0032). No proxy needed.
- `status` — e.g. `"Unpublished"`, `"Needs Review"`, `"Accepted"`, `"Committed"`, `"Closed"`, `"Abandoned"`. Drives `status_changed` + terminal (`Committed`/`Closed`/`Abandoned` → terminal; the existing adapter uses `--include-only-open` so landed/abandoned diffs disappear from poll → disappearance-archival path).
- `comment_count` — increase → `comment_added`.
- `line_count`, `file_count` — available (proxies / display).
- `updated` — ISO timestamp (do NOT use as a change signal; advances on any event).
Available `--columns`: number,title,status,author,repository,branch,created,updated,committed,published,line_count,comment_count,summary,file_count,ai_percentage,**version**,url.
Filters incl. `--review-stage-is='Action Required'` (review_stage is filterable; not in the column list — get via `describe` if needed).

## Hunk source (DiffEnricher deep fetch, T18) — `phabricator.diff raw-diff`
```
meta phabricator.diff raw-diff --number=D107906278 --no-truncate -o json
```
Returns `{raw_diff: "<unified diff>", truncated: bool, length: int}`. `raw_diff` is standard unified diff text: `diff --git a/… b/…`, `--- a/…`, `+++ b/…`, `@@ -a,b +c,d @@`, then `+`/`-`/context lines. Parse into per-file hunks. **Default output truncates — pass `--no-truncate`** (or read `length`/`truncated`). Budget-cap on our side (40 files / ~200KB per ADR 0032) before/after this call.

## Per-file summary (cheap, no code) — `phabricator.diff diff`
```
meta phabricator.diff diff --number=D107906278 -o json
```
List of `{filename, change_type ("Modified"/"Added"/…), old_filename, lines_added, lines_removed}`. Use for the file list + Path Pre-skip decisions + change_type without fetching the full patch. (`phabricator.diff files` is similar.)

## Comprehensive metadata + CI — `describe` / `ci-status` / signals
- `meta phabricator.diff describe --number=D<n> -o json` — comprehensive metadata (author phid, repo/callsign, review_stage, etc. for entity_refs + DiffMetadata).
- `meta phabricator.diff ci-status --number=D<n>` and `meta phabricator.diff.signals …` — CI status for `ci_changed` detection + critical CI-failure-on-authored-diff.

## Execution env
Subprocess pattern unchanged from existing phabricator.py: `asyncio.create_subprocess_exec`, 30s timeout, THRIFT_TLS cert env + `LD_LIBRARY_PATH=/usr/local/fbcode/platform010/lib` (cert confirmed working in this container).

## Pass-2 corrections to bake in
- PhabricatorChangeDetector (T23): material fields = `status` (any transition), `version` (→ code_updated), `comment_count` (increase), CI status (via ci-status/signals). Terminal: status Committed/Closed/Abandoned OR disappearance.
- Phabricator adapter (T24): `poll()` adds `--columns …,version,status,comment_count,line_count,file_count,updated`; persist `version` into raw_data; `stable_id(raw)=json.loads(raw_text)["number"]` (already `D<n>`); `supports_monitoring()=True`; `poll_returns_complete_set()` stays False (watermark/--include-only-open is partial → rely on terminal status + disappearance only when a full snapshot is polled).
- DiffEnricher (T18): deep fetch via `raw-diff --no-truncate -o json`; parse `raw_diff`; `describe` for metadata/entity_refs; capture `version` as `revision_id`/diff_version + `diff_url`.

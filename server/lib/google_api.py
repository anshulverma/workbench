#!/usr/bin/env python3
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""
Google Chat API script using Jellyfish GraphQL.

Usage:
    python3 google_api.py '{"action": "list_spaces"}'
    python3 google_api.py '{"action": "send_message", "space_id": "AAQA...", "text": "Hello!"}'
    python3 google_api.py '{"action": "send_message", "space_id": "AAQA...", "text": "Bot msg", "as_bot": true}'
    python3 google_api.py '{"action": "list_messages", "space_id": "AAQA..."}'
    python3 google_api.py '{"action": "search_spaces", "query": "customer = \"customers/my_customer\" AND space_type = \"SPACE\""}'
    python3 google_api.py '{"action": "update_message", "message_name": "spaces/X/messages/Y", "text": "edited"}'
    python3 google_api.py '{"action": "create_reaction", "message_name": "spaces/X/messages/Y", "emoji": "👍"}'
    python3 google_api.py '{"action": "add_member", "space_id": "AAQA...", "user_email": "user@meta.com"}'
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote, urlencode

_SANDBOX_HOST: str | None = None

_DCAT_TOKEN_LIFETIME_SECONDS: int = 60
_DCAT_TOKEN_REFRESH_MARGIN_SECONDS: int = 15
_cached_dcat_token: str | None = None
_cached_dcat_expiry: float = 0.0


def set_sandbox_host(host: str | None) -> None:
    """Set the sandbox host for ondemand environments."""
    global _SANDBOX_HOST
    _SANDBOX_HOST = host


def get_sandbox_host() -> str | None:
    """Get the sandbox host from global var or environment."""
    return _SANDBOX_HOST or os.environ.get("SANDBOX_HOST")


def get_dcat() -> str:
    """Get a DCAT token for Google API Proxy authentication.

    Caches the token and reuses it until it's within the refresh margin
    of expiry. The token has a 60-second lifetime; we refresh 15 seconds
    early to avoid using near-expiry tokens.
    """
    global _cached_dcat_token, _cached_dcat_expiry

    if _cached_dcat_token is not None and time.monotonic() < _cached_dcat_expiry:
        return _cached_dcat_token

    clicat_cmd = "corp_clicat" if shutil.which("corp_clicat") else "clicat"
    result = subprocess.run(
        [
            clicat_cmd,
            "create",
            "--verifier_type",
            "OTHER",
            "--verifier_id",
            "google_api_proxy",
            "--token_timeout_seconds",
            str(_DCAT_TOKEN_LIFETIME_SECONDS),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get dcat: {result.stderr}")

    _cached_dcat_token = result.stdout.strip()
    _cached_dcat_expiry = (
        time.monotonic()
        + _DCAT_TOKEN_LIFETIME_SECONDS
        - _DCAT_TOKEN_REFRESH_MARGIN_SECONDS
    )
    return _cached_dcat_token


def invalidate_dcat_cache() -> None:
    """Force the next get_dcat() call to fetch a fresh token."""
    global _cached_dcat_token, _cached_dcat_expiry
    _cached_dcat_token = None
    _cached_dcat_expiry = 0.0


_AUTH_ERROR_STATUSES = {401, 403}


_MAX_INLINE_VARIABLES_BYTES = 100_000  # ~98KB, margin below 128KB MAX_ARG_STRLEN


def _run_jf_graphql_cmd(
    query: str,
    variables: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    """Run jf graphql, using a temp file for large variable payloads."""
    cmd = ["jf"]
    sandbox_host = get_sandbox_host()
    if sandbox_host:
        cmd.extend(["--sandbox-host", sandbox_host])

    variables_json = json.dumps(variables)
    tmpfile_path = None
    try:
        if len(variables_json.encode("utf-8")) >= _MAX_INLINE_VARIABLES_BYTES:
            fd, tmpfile_path = tempfile.mkstemp(suffix=".json", prefix="jf_vars_")
            with os.fdopen(fd, "w") as f:
                f.write(variables_json)
            cmd.extend(["graphql", "--query", query, "--variables-file", tmpfile_path])
        else:
            cmd.extend(["graphql", "--query", query, "--variables", variables_json])
        return subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if tmpfile_path is not None:
            try:
                os.unlink(tmpfile_path)
            except OSError:
                pass


def call_google_api(
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    auth_token_class: str = "GoogleChatAuthTokenAsUser",
    _retried: bool = False,
) -> dict[str, Any]:
    """Call Google API via google-api-proxy CLI.

    Uses the google-api-proxy CLI directly instead of jf graphql, which
    eliminates the need for `jf auth` (24-hour TTL, requires interactive
    browser login). The CLI authenticates via x509 cert (3-day TTL,
    auto-renewed by chef-client).

    Falls back to jf graphql if google-api-proxy is not available.
    """
    if shutil.which("google-api-proxy"):
        result = _call_via_proxy_cli(method, endpoint, payload, auth_token_class)
        if result.get("success") or "timed out" not in str(result.get("error", "")):
            return result
        # Proxy timed out — fall back to jf graphql
    return _call_via_jf_graphql(method, endpoint, payload, auth_token_class, _retried)


def _call_via_proxy_cli(
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    auth_token_class: str = "GoogleChatAuthTokenAsUser",
) -> dict[str, Any]:
    """Call Google API via google-api-proxy CLI (no jf auth needed)."""
    cmd = [
        "google-api-proxy",
        "--json",
        "call",
        "--token-class",
        auth_token_class,
        method,
        endpoint,
    ]
    if payload:
        cmd.extend(["--data", json.dumps(payload)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "google-api-proxy timed out after 30s"}

    if result.returncode != 0:
        return {"success": False, "error": result.stderr or "google-api-proxy failed"}

    try:
        # The CLI outputs JSON with timing lines on stderr; stdout has the JSON
        # Find the JSON object in stdout (skip any non-JSON lines)
        stdout = result.stdout.strip()
        # Find the JSON start
        json_start = stdout.find("{")
        if json_start < 0:
            return {"success": False, "error": f"No JSON in output: {stdout[:200]}"}
        response = json.loads(stdout[json_start:])

        if response.get("success"):
            data = response.get("data")
            if isinstance(data, str):
                try:
                    return {"success": True, "data": json.loads(data)}
                except json.JSONDecodeError:
                    return {"success": True, "data": data}
            return {"success": True, "data": data}

        return {
            "success": False,
            "error": response.get("error") or f"API call failed: {stdout[:300]}",
            "http_status": response.get("http_status"),
        }
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Failed to parse response: {e}"}


def _call_via_jf_graphql(
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    auth_token_class: str = "GoogleChatAuthTokenAsUser",
    _retried: bool = False,
) -> dict[str, Any]:
    """Fallback: Call Google API via Jellyfish GraphQL (requires jf auth)."""
    dcat = get_dcat()

    query = """mutation GoogleApiProxy($dcat: SensitiveString, $endpoint: String!, $method: String!, $payload: String, $authTokenClass: String!) {
        xfb_google_api_proxy(input: {
            auth_token_class: $authTokenClass,
            method: $method,
            endpoint: $endpoint,
            payload: $payload,
            enforce_permitted_authors: false,
            follow_redirects: true,
            max_response_size: 104857600,
            dcat: $dcat
        }) {
            success
            http_status
            content_type
            response_body
            error_message
        }
    }"""

    variables = {
        "dcat": dcat,
        "endpoint": endpoint,
        "method": method,
        "payload": json.dumps(payload) if payload else None,
        "authTokenClass": auth_token_class,
    }

    result = _run_jf_graphql_cmd(query, variables)

    if result.returncode != 0:
        return {"success": False, "error": result.stderr}

    try:
        response = json.loads(result.stdout)
        data = response.get("xfb_google_api_proxy") or response.get("data", {}).get(
            "xfb_google_api_proxy", {}
        )
        if data.get("success"):
            body = data.get("response_body")
            if body:
                try:
                    return {"success": True, "data": json.loads(body)}
                except json.JSONDecodeError:
                    return {"success": True, "data": body}
            return {"success": True, "data": None}

        http_status = data.get("http_status")
        if not _retried and http_status in _AUTH_ERROR_STATUSES:
            invalidate_dcat_cache()
            return _call_via_jf_graphql(
                method, endpoint, payload, auth_token_class, _retried=True
            )

        return {
            "success": False,
            "error": data.get("error_message") or f"API call failed: {result.stdout}",
            "http_status": http_status,
        }
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Failed to parse response: {e}"}


_MAX_BATCH_SIZE = 100


def _build_graphql_request_list(batch_requests: list[dict[str, Any]]) -> str:
    """Convert a list of request dicts into a GraphQL literal string.

    GraphQL literals use unquoted keys and quoted string values, e.g.:
      [{method: "POST", endpoint: "https://...", payload: "..."}]

    This is necessary because the ``jf`` GraphQL client cannot pass complex
    input types (like ``[GoogleAPIProxyBatchRequestInput!]!``) as variables —
    only scalar types are supported.  The requests array must therefore be
    inlined directly in the query string.
    """
    items: list[str] = []
    for req in batch_requests:
        parts = [
            f'method: "{req["method"]}"',
            f'endpoint: "{req["endpoint"]}"',
        ]
        if "payload" in req:
            escaped = req["payload"].replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'payload: "{escaped}"')
        items.append("{" + ", ".join(parts) + "}")
    return "[" + ", ".join(items) + "]"


def batch_call_google_api(
    requests: list[dict[str, Any]],
    auth_token_class: str = "GoogleChatAuthTokenAsUser",
    timeout_ms: int | None = None,
    _retried: bool = False,
) -> dict[str, Any]:
    """Call multiple Google API endpoints in a single batch request.

    Each element in *requests* must be a dict with keys:
      - method (str): HTTP method (GET, POST, PUT, DELETE, PATCH).
      - endpoint (str): Full Google API URL.
      - payload (str | None): Optional JSON-encoded request body.

    The server supports up to 100 requests per batch. Larger lists are
    automatically chunked and the responses are concatenated in order.

    Returns {"success": True, "responses": [per-request results]} on
    success, where each per-request result mirrors the single-call
    return format.
    """
    if not requests:
        return {"success": True, "responses": []}

    all_responses: list[dict[str, Any]] = []
    for chunk_start in range(0, len(requests), _MAX_BATCH_SIZE):
        chunk = requests[chunk_start : chunk_start + _MAX_BATCH_SIZE]
        chunk_result = _batch_call_chunk(
            chunk, auth_token_class, timeout_ms, _retried=_retried
        )
        if not chunk_result.get("success"):
            return chunk_result
        all_responses.extend(chunk_result["responses"])

    return {"success": True, "responses": all_responses}


def _batch_call_chunk(
    requests: list[dict[str, Any]],
    auth_token_class: str,
    timeout_ms: int | None,
    _retried: bool = False,
) -> dict[str, Any]:
    """Execute a single batch chunk (up to 100 requests).

    Retries once with a fresh DCAT token when auth issues are detected:
    - Top-level batch failure: retries if the error message contains auth
      indicators (401, 403, unauthorized, forbidden).
    - Per-request failures: retries only when ALL failed responses have
      HTTP 401/403 status, indicating a token-level issue rather than
      per-resource permission errors.
    """
    dcat = get_dcat()

    batch_requests = []
    for req in requests:
        entry: dict[str, Any] = {
            "method": req["method"],
            "endpoint": req["endpoint"],
        }
        if req.get("payload"):
            entry["payload"] = (
                json.dumps(req["payload"])
                if isinstance(req["payload"], dict)
                else req["payload"]
            )
        batch_requests.append(entry)

    requests_literal = _build_graphql_request_list(batch_requests)

    timeout_fragment = ""
    if timeout_ms is not None:
        timeout_fragment = f", timeout_ms: {timeout_ms}"

    query = f"""mutation GoogleApiProxyBatch($dcat: SensitiveString, $authTokenClass: String!) {{
        xfb_google_api_proxy_batch(input: {{
            auth_token_class: $authTokenClass,
            requests: {requests_literal},
            dcat: $dcat{timeout_fragment}
        }}) {{
            success
            error_message
            responses {{
                success
                http_status
                content_type
                response_body
                error_message
            }}
        }}
    }}"""

    variables: dict[str, Any] = {
        "dcat": dcat,
        "authTokenClass": auth_token_class,
    }

    result = _run_jf_graphql_cmd(query, variables)

    if result.returncode != 0:
        return {"success": False, "error": result.stderr}

    try:
        response = json.loads(result.stdout)
        data = response.get("xfb_google_api_proxy_batch") or response.get(
            "data", {}
        ).get("xfb_google_api_proxy_batch", {})

        if not data.get("success"):
            error_msg = data.get("error_message", "")
            is_auth_error = any(
                hint in error_msg.lower()
                for hint in ("401", "403", "unauthorized", "forbidden", "auth")
            )
            if not _retried and is_auth_error:
                invalidate_dcat_cache()
                return _batch_call_chunk(
                    requests, auth_token_class, timeout_ms, _retried=True
                )
            return {
                "success": False,
                "error": error_msg or f"Batch call failed: {result.stdout}",
            }

        parsed_responses = []
        for resp in data.get("responses", []):
            if resp.get("success"):
                body = resp.get("response_body")
                if body:
                    try:
                        parsed_responses.append(
                            {"success": True, "data": json.loads(body)}
                        )
                    except json.JSONDecodeError:
                        parsed_responses.append({"success": True, "data": body})
                else:
                    parsed_responses.append({"success": True, "data": None})
            else:
                parsed_responses.append(
                    {
                        "success": False,
                        "error": resp.get("error_message", "Unknown error"),
                        "http_status": resp.get("http_status"),
                    }
                )

        failed_responses = [
            resp for resp in data.get("responses", []) if not resp.get("success")
        ]
        if (
            not _retried
            and failed_responses
            and all(
                resp.get("http_status") in _AUTH_ERROR_STATUSES
                for resp in failed_responses
            )
        ):
            invalidate_dcat_cache()
            return _batch_call_chunk(
                requests, auth_token_class, timeout_ms, _retried=True
            )

        return {"success": True, "responses": parsed_responses}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Failed to parse batch response: {e}"}


CHAT_API_BASE = "https://chat.googleapis.com/v1"


def normalize_space_id(space_id: str) -> str:
    """Ensure space_id has the 'spaces/' prefix.

    Handles DM space IDs (dm/XXX) by stripping the dm/ prefix first,
    since the Google Chat API uses spaces/XXX for all space types.
    """
    if space_id.startswith("dm/"):
        space_id = space_id[3:]
    if not space_id.startswith("spaces/"):
        return f"spaces/{space_id}"
    return space_id


def list_spaces(
    page_size: int = 20,
    page_token: str | None = None,
    filter_str: str | None = None,
) -> dict[str, Any]:
    """List spaces the user is a member of."""
    params: dict[str, str] = {"pageSize": str(page_size)}
    if page_token:
        params["pageToken"] = page_token
    if filter_str:
        params["filter"] = filter_str

    endpoint = f"{CHAT_API_BASE}/spaces?{urlencode(params)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    spaces = data.get("spaces", [])

    space_list = []
    for space in spaces:
        entry: dict[str, Any] = {
            "name": space.get("name", ""),
            "display_name": space.get("displayName", ""),
            "type": space.get("spaceType", ""),
        }
        if space.get("lastActiveTime"):
            entry["last_active_time"] = space["lastActiveTime"]
        space_list.append(entry)

    return {
        "success": True,
        "data": {
            "spaces": space_list,
            "count": len(space_list),
            "next_page_token": data.get("nextPageToken"),
        },
    }


def get_space(space_id: str) -> dict[str, Any]:
    """Get details about a specific space."""
    space_name = normalize_space_id(space_id)
    endpoint = f"{CHAT_API_BASE}/{space_name}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    space = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": space.get("name", ""),
            "display_name": space.get("displayName", ""),
            "type": space.get("spaceType", ""),
            "details": space.get("spaceDetails"),
        },
    }


def create_space(
    member_emails: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Create a new space with the specified members."""
    emails = [e.strip() for e in member_emails.split(",") if e.strip()]

    if not emails:
        return {"success": False, "error": "No valid email addresses provided"}

    memberships = []
    for email in emails:
        memberships.append({"member": {"name": f"users/{email}", "type": "HUMAN"}})

    if display_name:
        space_type = "SPACE"
    elif len(emails) == 1:
        space_type = "DIRECT_MESSAGE"
    else:
        space_type = "GROUP_CHAT"

    payload: dict[str, Any] = {
        "space": {
            "spaceType": space_type,
        },
        "memberships": memberships,
    }

    if display_name:
        payload["space"]["displayName"] = display_name

    endpoint = f"{CHAT_API_BASE}/spaces:setup"
    result = call_google_api("POST", endpoint, payload)

    if not result.get("success"):
        return result

    space = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": space.get("name", ""),
            "display_name": space.get("displayName", ""),
            "type": space.get("spaceType", ""),
        },
    }


def _enrich_text_with_links(text: str, annotations: list) -> str:
    """Inline hyperlink URLs from annotations into plain text."""
    if not text or not annotations:
        return text

    # Collect link annotations with their positions and URLs
    links = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        start = ann.get("startIndex")
        length = ann.get("length")
        if start is None or length is None:
            continue

        url = None
        rich_link = ann.get("richLinkMetadata")
        if rich_link:
            url = rich_link.get("uri")

        if url:
            links.append({"start": start, "length": length, "url": url})

    if not links:
        return text

    # Sort descending by start index so replacements don't shift earlier indices
    links.sort(key=lambda a: a["start"], reverse=True)

    result = text
    for link in links:
        s = link["start"]
        e = s + link["length"]
        display = result[s:e].strip()
        # Only add URL if it's not already the display text
        if display != link["url"]:
            result = result[:s] + f"{display} ({link['url']})" + result[e:]

    return result


def _parse_message_fields(msg: dict | str) -> dict[str, Any]:
    """Parse a message into standardized format with link enrichment.

    Handles both dict (full message) and str (resource name only, from batch proxy).
    """
    if isinstance(msg, str):
        return {
            "name": msg,
            "text": "",
            "sender": "",
            "sender_name": "",
            "sender_email": "",
            "sender_type": "",
            "create_time": "",
            "thread": "",
            "thread_reply": False,
            "attachment": [],
            "accessory_widgets": [],
        }
    annotations = msg.get("annotations", [])
    text = msg.get("text", "")
    # Extract quoted message resource name if present
    quoted_message_name = ""
    quoted_meta = msg.get("quotedMessageMetadata", {})
    if isinstance(quoted_meta, dict):
        quoted_message_name = quoted_meta.get("name", "")
    return {
        "name": msg.get("name", ""),
        "text": _enrich_text_with_links(text, annotations),
        "sender": msg.get("sender", {}).get("name", ""),
        "sender_name": msg.get("sender", {}).get("displayName", ""),
        "sender_email": msg.get("sender", {}).get("email", ""),
        "sender_type": msg.get("sender", {}).get("type", ""),
        "create_time": msg.get("createTime", ""),
        "thread": msg.get("thread", {}).get("name", ""),
        "thread_reply": msg.get("threadReply", False),
        "attachment": msg.get("attachment", []),
        "accessory_widgets": msg.get("accessoryWidgets", []),
        "quoted_message_name": quoted_message_name,
    }


def list_messages(
    space_id: str,
    page_size: int = 20,
    page_token: str | None = None,
    filter_str: str | None = None,
    order_by: str = "createTime DESC",
    show_deleted: bool = False,
) -> dict[str, Any]:
    """List messages in a space. Returns newest messages first by default."""
    space_name = normalize_space_id(space_id)

    params: dict[str, str] = {"pageSize": str(page_size)}
    if page_token:
        params["pageToken"] = page_token
    if filter_str:
        params["filter"] = filter_str
    if order_by:
        params["orderBy"] = order_by
    if show_deleted:
        params["showDeleted"] = "true"

    endpoint = f"{CHAT_API_BASE}/{space_name}/messages?{urlencode(params)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    messages = data.get("messages", [])

    message_list = []
    for msg in messages:
        message_list.append(_parse_message_fields(msg))

    return {
        "success": True,
        "data": {
            "messages": message_list,
            "count": len(message_list),
            "next_page_token": data.get("nextPageToken"),
        },
    }


def _extract_raw_messages_from_batch(data: Any) -> list[Any]:
    """Extract raw message list from batch response data.

    Handles different shapes the batch proxy may return:
    - list directly (batch may unwrap)
    - dict with "messages" key containing a list (standard)
    - dict with "messages" key containing index-keyed dict (serialization quirk)
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    msgs = data.get("messages", [])
    if isinstance(msgs, dict):
        # Index-keyed dict — extract values in key order
        return [msgs[k] for k in sorted(msgs.keys(), key=int)]
    return msgs


def _process_batch_list_response(resp: dict[str, Any], space_id: str) -> dict[str, Any]:
    """Process a single batch response item for list_messages_batch."""
    if not resp.get("success"):
        return {**resp, "space_id": space_id}

    data = resp.get("data", {})
    raw_messages = _extract_raw_messages_from_batch(data)
    message_list = [
        _parse_message_fields(msg)
        for msg in raw_messages
        if isinstance(msg, (dict, str))
    ]
    next_page_token = data.get("nextPageToken") if isinstance(data, dict) else None

    return {
        "success": True,
        "space_id": space_id,
        "data": {
            "messages": message_list,
            "count": len(message_list),
            "next_page_token": next_page_token,
        },
    }


def list_messages_batch(
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """List messages from multiple spaces in a single batch call.

    Each element in *messages* must be a dict with keys:
      - space_id (str): Space ID or full space name.
      - page_size (int, optional): Max messages per space (default 20).
      - filter (str | None, optional): Filter expression (e.g. createTime > "...").
      - order_by (str, optional): Defaults to "createTime DESC" (newest first).

    Returns {"success": True, "results": [per-space results]} where each
    result contains the message list or error for that specific space,
    with space_id included for correlation.
    """
    if not messages:
        return {"success": True, "results": []}

    requests = []
    for query in messages:
        space_name = normalize_space_id(query["space_id"])
        params: dict[str, str] = {"pageSize": str(query.get("page_size", 20))}
        if query.get("filter"):
            params["filter"] = query["filter"]
        order_by = query.get("order_by", "createTime DESC")
        params["orderBy"] = order_by

        endpoint = f"{CHAT_API_BASE}/{space_name}/messages?{urlencode(params)}"
        requests.append({"method": "GET", "endpoint": endpoint})

    batch_result = batch_call_google_api(requests)

    if not batch_result.get("success"):
        return batch_result

    results = []
    for i, resp in enumerate(batch_result["responses"]):
        space_id = messages[i]["space_id"]
        results.append(_process_batch_list_response(resp, space_id))

    return {"success": True, "results": results}


def get_message(message_id: str) -> dict[str, Any]:
    """Get a specific message by its resource name."""
    endpoint = f"{CHAT_API_BASE}/{message_id}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    msg = result.get("data", {})
    return {
        "success": True,
        "data": _parse_message_fields(msg),
    }


def send_message(
    space_id: str,
    text: str,
    thread_name: str | None = None,
    as_bot: bool = False,
) -> dict[str, Any]:
    """Send a message to a space. Use as_bot=True to send as Meta Bot."""
    space_name = normalize_space_id(space_id)
    auth_class = "GoogleChatAuthTokenAsBot" if as_bot else "GoogleChatAuthTokenAsUser"

    payload: dict[str, Any] = {"text": text}
    if thread_name:
        payload["thread"] = {"name": thread_name}

    params: dict[str, str] = {}
    if thread_name:
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    endpoint = f"{CHAT_API_BASE}/{space_name}/messages"
    if params:
        endpoint += f"?{urlencode(params)}"

    result = call_google_api("POST", endpoint, payload, auth_token_class=auth_class)

    if not result.get("success"):
        return result

    msg = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": msg.get("name", ""),
            "thread": msg.get("thread", {}).get("name", ""),
            "sender_type": msg.get("sender", {}).get("type", ""),
            "text": text,
        },
    }


def send_card_message(
    space_id: str,
    text: str,
    cards_v2: list[dict[str, Any]],
    thread_name: str | None = None,
    as_bot: bool = True,
) -> dict[str, Any]:
    """Send a card message to a space. Cards require bot auth by default."""
    space_name = normalize_space_id(space_id)
    auth_class = "GoogleChatAuthTokenAsBot" if as_bot else "GoogleChatAuthTokenAsUser"

    payload: dict[str, Any] = {"text": text, "cardsV2": cards_v2}
    if thread_name:
        payload["thread"] = {"name": thread_name}

    params: dict[str, str] = {}
    if thread_name:
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    endpoint = f"{CHAT_API_BASE}/{space_name}/messages"
    if params:
        endpoint += f"?{urlencode(params)}"

    result = call_google_api("POST", endpoint, payload, auth_token_class=auth_class)

    if not result.get("success"):
        return result

    msg = result.get("data", {})
    return {
        "success": True,
        "data": _parse_message_fields(msg),
    }


def send_messages_batch(
    messages: list[dict[str, Any]],
    as_bot: bool = False,
) -> dict[str, Any]:
    """Send multiple messages to different spaces in a single batch call.

    Each element in *messages* must be a dict with keys:
      - space_id (str): Target space ID or full space name.
      - text (str): Message text to send.
      - thread_name (str | None): Optional thread to reply to.

    Returns {"success": True, "results": [per-message results]} where each
    result contains the message data or error for that specific send.
    """
    if not messages:
        return {"success": True, "results": []}

    auth_class = "GoogleChatAuthTokenAsBot" if as_bot else "GoogleChatAuthTokenAsUser"

    requests = []
    for msg in messages:
        space_name = normalize_space_id(msg["space_id"])
        payload: dict[str, Any] = {"text": msg["text"]}
        thread_name = msg.get("thread_name")
        if thread_name:
            payload["thread"] = {"name": thread_name}

        params: dict[str, str] = {}
        if thread_name:
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        endpoint = f"{CHAT_API_BASE}/{space_name}/messages"
        if params:
            endpoint += f"?{urlencode(params)}"

        requests.append({"method": "POST", "endpoint": endpoint, "payload": payload})

    batch_result = batch_call_google_api(requests, auth_token_class=auth_class)

    if not batch_result.get("success"):
        return batch_result

    results = []
    for i, resp in enumerate(batch_result["responses"]):
        original_text = messages[i]["text"]
        if resp.get("success"):
            data = resp.get("data", {})
            results.append(
                {
                    "success": True,
                    "data": {
                        "name": data.get("name", ""),
                        "thread": data.get("thread", {}).get("name", ""),
                        "sender_type": data.get("sender", {}).get("type", ""),
                        "text": original_text,
                    },
                }
            )
        else:
            results.append(resp)

    return {"success": True, "results": results}


def update_message(
    message_name: str,
    text: str,
    as_bot: bool = False,
) -> dict[str, Any]:
    """Update a message's text content."""
    auth_class = "GoogleChatAuthTokenAsBot" if as_bot else "GoogleChatAuthTokenAsUser"
    payload: dict[str, Any] = {"text": text}
    endpoint = f"{CHAT_API_BASE}/{message_name}?updateMask=text"
    result = call_google_api("PUT", endpoint, payload, auth_token_class=auth_class)

    if not result.get("success"):
        return result

    msg = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": msg.get("name", ""),
            "text": msg.get("text", ""),
        },
    }


def update_space(
    space_id: str,
    display_name: str | None = None,
    description: str | None = None,
    guidelines: str | None = None,
) -> dict[str, Any]:
    """Update a space's display name, description, or guidelines."""
    space_name = normalize_space_id(space_id)

    payload: dict[str, Any] = {}
    update_fields: list[str] = []

    if display_name is not None:
        payload["displayName"] = display_name
        update_fields.append("display_name")

    if description is not None or guidelines is not None:
        details: dict[str, str] = {}
        if description is not None:
            details["description"] = description
        if guidelines is not None:
            details["guidelines"] = guidelines
        payload["spaceDetails"] = details
        update_fields.append("space_details")

    if not update_fields:
        return {"success": False, "error": "No fields to update"}

    endpoint = f"{CHAT_API_BASE}/{space_name}?updateMask={','.join(update_fields)}"
    result = call_google_api("PATCH", endpoint, payload)

    if not result.get("success"):
        return result

    space = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": space.get("name", ""),
            "display_name": space.get("displayName", ""),
            "type": space.get("spaceType", ""),
            "details": space.get("spaceDetails"),
        },
    }


def search_spaces(
    query: str,
    page_size: int = 100,
    page_token: str | None = None,
    order_by: str | None = None,
) -> dict[str, Any]:
    """Search for spaces (requires admin access)."""
    params: dict[str, str] = {
        "useAdminAccess": "true",
        "query": query,
        "pageSize": str(page_size),
    }
    if page_token:
        params["pageToken"] = page_token
    if order_by:
        params["orderBy"] = order_by

    endpoint = f"{CHAT_API_BASE}/spaces:search?{urlencode(params)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    spaces = data.get("spaces", [])

    space_list = []
    for space in spaces:
        space_list.append(
            {
                "name": space.get("name", ""),
                "display_name": space.get("displayName", ""),
                "type": space.get("spaceType", ""),
                "member_count": space.get("membershipCount", {}).get(
                    "joinedDirectHumanUserCount"
                ),
            }
        )

    return {
        "success": True,
        "data": {
            "spaces": space_list,
            "count": len(space_list),
            "next_page_token": data.get("nextPageToken"),
        },
    }


def add_member(
    space_id: str,
    user_email: str,
) -> dict[str, Any]:
    """Add a member to a space."""
    space_name = normalize_space_id(space_id)
    payload: dict[str, Any] = {
        "member": {
            "name": f"users/{user_email}",
            "type": "HUMAN",
        }
    }
    endpoint = f"{CHAT_API_BASE}/{space_name}/members"
    result = call_google_api("POST", endpoint, payload)

    if not result.get("success"):
        return result

    member = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": member.get("name", ""),
            "user": member.get("member", {}).get("name", ""),
            "role": member.get("role", ""),
            "state": member.get("state", ""),
        },
    }


def remove_member(
    member_name: str,
) -> dict[str, Any]:
    """Remove a member from a space. member_name format: spaces/SPACE_ID/members/MEMBER_ID"""
    endpoint = f"{CHAT_API_BASE}/{member_name}"
    result = call_google_api("DELETE", endpoint)

    if not result.get("success"):
        return result

    return {
        "success": True,
        "data": {"removed": member_name},
    }


def create_reaction(
    message_name: str,
    emoji: str,
) -> dict[str, Any]:
    """Add a reaction to a message."""
    payload: dict[str, Any] = {
        "emoji": {"unicode": emoji},
    }
    endpoint = f"{CHAT_API_BASE}/{message_name}/reactions"
    result = call_google_api("POST", endpoint, payload)

    if not result.get("success"):
        return result

    reaction = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": reaction.get("name", ""),
            "emoji": reaction.get("emoji", {}).get("unicode", ""),
        },
    }


def list_reactions(
    message_name: str,
    page_size: int = 25,
    page_token: str | None = None,
) -> dict[str, Any]:
    """List reactions on a message."""
    params: dict[str, str] = {"pageSize": str(page_size)}
    if page_token:
        params["pageToken"] = page_token

    endpoint = f"{CHAT_API_BASE}/{message_name}/reactions?{urlencode(params)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    reactions = data.get("reactions", [])

    reaction_list = []
    for r in reactions:
        reaction_list.append(
            {
                "name": r.get("name", ""),
                "emoji": r.get("emoji", {}).get("unicode", ""),
                "user": r.get("user", {}).get("name", ""),
            }
        )

    return {
        "success": True,
        "data": {
            "reactions": reaction_list,
            "count": len(reaction_list),
            "next_page_token": data.get("nextPageToken"),
        },
    }


def delete_reaction(
    reaction_name: str,
) -> dict[str, Any]:
    """Delete a reaction from a message."""
    endpoint = f"{CHAT_API_BASE}/{reaction_name}"
    result = call_google_api("DELETE", endpoint)

    if not result.get("success"):
        return result

    return {
        "success": True,
        "data": {"deleted": reaction_name},
    }


def list_members(
    space_id: str,
    page_size: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    """List members of a space."""
    space_name = normalize_space_id(space_id)

    params: dict[str, str] = {"pageSize": str(page_size)}
    if page_token:
        params["pageToken"] = page_token

    endpoint = f"{CHAT_API_BASE}/{space_name}/members?{urlencode(params)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    memberships = data.get("memberships", [])

    member_list = []
    for member in memberships:
        member_list.append(
            {
                "name": member.get("name", ""),
                "user": member.get("member", {}).get("name", ""),
                "display_name": member.get("member", {}).get("displayName", ""),
                "role": member.get("role", ""),
                "state": member.get("state", ""),
            }
        )

    return {
        "success": True,
        "data": {
            "members": member_list,
            "count": len(member_list),
            "next_page_token": data.get("nextPageToken"),
        },
    }


def find_dm_space(user_email: str) -> dict[str, Any]:
    """Find an existing DM space with a user by email."""
    user_resource = f"users/{user_email}"
    endpoint = f"{CHAT_API_BASE}/spaces:findDirectMessage?name={quote(user_resource)}"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    space = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": space.get("name", ""),
            "type": space.get("spaceType", ""),
            "user_email": user_email,
        },
    }


def delete_message(message_name: str) -> dict[str, Any]:
    """Delete a message by its resource name."""
    endpoint = f"{CHAT_API_BASE}/{message_name}"
    result = call_google_api("DELETE", endpoint)

    if not result.get("success"):
        return result

    return {
        "success": True,
        "data": {"deleted": message_name},
    }


def delete_space(space_id: str) -> dict[str, Any]:
    """Delete a space."""
    space_name = normalize_space_id(space_id)
    endpoint = f"{CHAT_API_BASE}/{space_name}"
    result = call_google_api("DELETE", endpoint)

    if not result.get("success"):
        return result

    return {
        "success": True,
        "data": {"deleted": space_name},
    }


def get_space_read_state(space_id: str) -> dict[str, Any]:
    """Get the read state of a space for the calling user."""
    space_name = normalize_space_id(space_id)
    endpoint = f"{CHAT_API_BASE}/users/me/{space_name}/spaceReadState"
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": data.get("name", ""),
            "last_read_time": data.get("lastReadTime", ""),
        },
    }


def update_space_read_state(space_id: str, last_read_time: str) -> dict[str, Any]:
    """Mark a space as read up to the given time.

    last_read_time is an RFC 3339 timestamp (e.g. "2026-02-23T00:00:00Z").
    To mark fully read, pass the current time or latest message time.
    """
    space_name = normalize_space_id(space_id)
    payload: dict[str, Any] = {"lastReadTime": last_read_time}
    endpoint = (
        f"{CHAT_API_BASE}/users/me/{space_name}/spaceReadState?updateMask=lastReadTime"
    )
    result = call_google_api("PATCH", endpoint, payload)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": data.get("name", ""),
            "last_read_time": data.get("lastReadTime", ""),
        },
    }


def get_thread_read_state(space_id: str, thread_id: str) -> dict[str, Any]:
    """Get the read state of a thread for the calling user."""
    space_name = normalize_space_id(space_id)
    endpoint = (
        f"{CHAT_API_BASE}/users/me/{space_name}/threads/{thread_id}/threadReadState"
    )
    result = call_google_api("GET", endpoint)

    if not result.get("success"):
        return result

    data = result.get("data", {})
    return {
        "success": True,
        "data": {
            "name": data.get("name", ""),
            "last_read_time": data.get("lastReadTime", ""),
        },
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "No input provided"}))
        sys.exit(1)

    try:
        if len(sys.argv) >= 3 and sys.argv[1] == "--input-file":
            with open(sys.argv[2]) as f:
                params = json.load(f)
        else:
            params = json.loads(sys.argv[1])
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    if params.get("sandbox_host"):
        set_sandbox_host(params["sandbox_host"])

    action = params.get("action")
    if not action:
        print(json.dumps({"success": False, "error": "No action specified"}))
        sys.exit(1)

    result: dict[str, Any]

    handlers: dict[str, tuple[list[str], Any]] = {
        "list_spaces": (
            [],
            lambda: list_spaces(
                page_size=params.get("page_size", 20),
                page_token=params.get("page_token"),
                filter_str=params.get("filter"),
            ),
        ),
        "get_space": (["space_id"], lambda: get_space(params["space_id"])),
        "create_space": (
            ["member_emails"],
            lambda: create_space(
                params["member_emails"],
                display_name=params.get("display_name"),
            ),
        ),
        "list_messages": (
            ["space_id"],
            lambda: list_messages(
                params["space_id"],
                page_size=params.get("page_size", 20),
                page_token=params.get("page_token"),
                filter_str=params.get("filter"),
                order_by=params.get("order_by"),
                show_deleted=params.get("show_deleted", False),
            ),
        ),
        "list_messages_batch": (
            ["messages"],
            lambda: list_messages_batch(
                params["messages"],
            ),
        ),
        "get_message": (["message_id"], lambda: get_message(params["message_id"])),
        "send_message": (
            ["space_id", "text"],
            lambda: send_message(
                params["space_id"],
                params["text"],
                thread_name=params.get("thread_name"),
                as_bot=params.get("as_bot", False),
            ),
        ),
        "send_card_message": (
            ["space_id", "text", "cards_v2"],
            lambda: send_card_message(
                params["space_id"],
                params["text"],
                params["cards_v2"],
                thread_name=params.get("thread_name"),
                as_bot=params.get("as_bot", True),
            ),
        ),
        "send_messages_batch": (
            ["messages"],
            lambda: send_messages_batch(
                params["messages"],
                as_bot=params.get("as_bot", False),
            ),
        ),
        "update_message": (
            ["message_name", "text"],
            lambda: update_message(
                params["message_name"],
                params["text"],
                as_bot=params.get("as_bot", False),
            ),
        ),
        "update_space": (
            ["space_id"],
            lambda: update_space(
                params["space_id"],
                display_name=params.get("display_name"),
                description=params.get("description"),
                guidelines=params.get("guidelines"),
            ),
        ),
        "search_spaces": (
            ["query"],
            lambda: search_spaces(
                params["query"],
                page_size=params.get("page_size", 100),
                page_token=params.get("page_token"),
                order_by=params.get("order_by"),
            ),
        ),
        "list_members": (
            ["space_id"],
            lambda: list_members(
                params["space_id"],
                page_size=params.get("page_size", 100),
                page_token=params.get("page_token"),
            ),
        ),
        "add_member": (
            ["space_id", "user_email"],
            lambda: add_member(
                params["space_id"],
                params["user_email"],
            ),
        ),
        "remove_member": (
            ["member_name"],
            lambda: remove_member(
                params["member_name"],
            ),
        ),
        "find_dm_space": (["user_email"], lambda: find_dm_space(params["user_email"])),
        "create_reaction": (
            ["message_name", "emoji"],
            lambda: create_reaction(
                params["message_name"],
                params["emoji"],
            ),
        ),
        "list_reactions": (
            ["message_name"],
            lambda: list_reactions(
                params["message_name"],
                page_size=params.get("page_size", 25),
                page_token=params.get("page_token"),
            ),
        ),
        "delete_reaction": (
            ["reaction_name"],
            lambda: delete_reaction(
                params["reaction_name"],
            ),
        ),
        "delete_message": (
            ["message_name"],
            lambda: delete_message(
                params["message_name"],
            ),
        ),
        "delete_space": (["space_id"], lambda: delete_space(params["space_id"])),
        "get_space_read_state": (
            ["space_id"],
            lambda: get_space_read_state(params["space_id"]),
        ),
        "update_space_read_state": (
            ["space_id", "last_read_time"],
            lambda: update_space_read_state(
                params["space_id"], params["last_read_time"]
            ),
        ),
        "get_thread_read_state": (
            ["space_id", "thread_id"],
            lambda: get_thread_read_state(params["space_id"], params["thread_id"]),
        ),
    }

    handler = handlers.get(action)
    if not handler:
        result = {"success": False, "error": f"Unknown action: {action}"}
    else:
        required_fields, fn = handler
        missing = [f for f in required_fields if f not in params]
        if missing:
            result = {
                "success": False,
                "error": f"{', '.join(missing)} required for {action}",
            }
        else:
            result = fn()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Key-name denylist regex (the Redaction Rule).
SECRET_PATTERN = re.compile(
    r"(token|key|secret|password|dsn|credential|service_account|auth|bearer)",
    re.IGNORECASE,
)

# Explicit field denylist (exact key names that must always be redacted).
FIELD_DENYLIST = {
    "service_account_key_path",
    "postgres_dsn",
    "api_token",
}


def _is_secret_key(key: str) -> bool:
    return key in FIELD_DENYLIST or bool(SECRET_PATTERN.search(key))


def redact_secrets(obj: Any, depth: int = 0) -> Any:
    """Recursively redact secret-bearing keys from config-derived data."""
    if depth > 10:
        return "..."
    if isinstance(obj, dict):
        return {
            k: REDACTED if _is_secret_key(str(k)) else redact_secrets(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(i, depth + 1) for i in obj]
    return obj

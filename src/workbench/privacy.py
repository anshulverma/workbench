from __future__ import annotations

import re
from typing import Any

from workbench.config import PrivacyConfig

EXCLUDED_KEYS = frozenset({"event", "level", "timestamp", "logger", "request_id"})


class SanitizingProcessor:
    """structlog processor that redacts PII patterns from log events."""

    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    PHONE_PATTERN = re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b')

    def __init__(
        self,
        config: PrivacyConfig,
        extra_patterns: list[tuple[re.Pattern, str]] | None = None,
    ):
        self._config = config
        self._patterns: list[tuple[re.Pattern, str]] = []
        if config.redact_emails:
            self._patterns.append((self.EMAIL_PATTERN, "[REDACTED:email]"))
        if config.redact_phones:
            self._patterns.append((self.PHONE_PATTERN, "[REDACTED:phone]"))
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def __call__(
        self, logger: Any, method_name: str, event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._config.sanitize_logs:
            return event_dict

        for key, value in event_dict.items():
            if key in EXCLUDED_KEYS:
                continue
            if not isinstance(value, str):
                continue
            if len(value) > self._config.max_content_in_logs:
                value = value[: self._config.max_content_in_logs] + "... [truncated]"
            for pattern, replacement in self._patterns:
                value = pattern.sub(replacement, value)
            event_dict[key] = value

        return event_dict

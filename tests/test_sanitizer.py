# tests/test_sanitizer.py

import pytest
from workbench.privacy import SanitizingProcessor, PrivacyConfig


def _process(processor, event_dict):
    return processor(None, "info", event_dict)


def test_redacts_email_addresses():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "sender": "alice@meta.com"})
    assert result["sender"] == "[REDACTED:email]"


def test_redacts_email_in_longer_text():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "msg": "From alice@meta.com to bob@example.org"})
    assert "alice@meta.com" not in result["msg"]
    assert "[REDACTED:email]" in result["msg"]


def test_redacts_phone_numbers():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "phone": "555-123-4567"})
    assert result["phone"] == "[REDACTED:phone]"


def test_truncates_long_content():
    proc = SanitizingProcessor(PrivacyConfig(max_content_in_logs=50))
    long_text = "a" * 200
    result = _process(proc, {"event": "test", "body": long_text})
    assert len(result["body"]) < 200
    assert "[truncated]" in result["body"]


def test_preserves_short_content():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "msg": "short message"})
    assert result["msg"] == "short message"


def test_skips_non_string_values():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "test", "count": 42, "items": [1, 2, 3]})
    assert result["count"] == 42
    assert result["items"] == [1, 2, 3]


def test_disabled_when_sanitize_logs_false():
    proc = SanitizingProcessor(PrivacyConfig(sanitize_logs=False))
    result = _process(proc, {"event": "test", "email": "alice@meta.com"})
    assert result["email"] == "alice@meta.com"


def test_extra_patterns():
    import re
    extra = [(re.compile(r'\bD\d{6,}\b'), '[REDACTED:phid]')]
    proc = SanitizingProcessor(PrivacyConfig(), extra_patterns=extra)
    result = _process(proc, {"event": "test", "diff": "D123456"})
    assert result["diff"] == "[REDACTED:phid]"


def test_skips_excluded_keys():
    proc = SanitizingProcessor(PrivacyConfig())
    result = _process(proc, {"event": "alice@meta.com", "level": "info", "timestamp": "2026-06-03"})
    assert result["event"] == "alice@meta.com"  # event key is excluded from sanitization

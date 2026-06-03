# ADR 0010: structlog with JSON Output over Glog Formatter

Phase 1d adds 6 source adapters (Gmail, Calendar, GChat, Meta Tasks, Workplace, Docs), each with its own enricher, plus identity resolution and LLM-generated triage cards. Debugging failures across these integrations requires structured, queryable log output — not plain-text glog lines that need manual parsing.

We chose structlog with JSON output in production and a human-readable console renderer in dev (Approach A) over keeping the glog formatter and adding ad-hoc structured fields (Approach B) or adding a full observability stack like Datadog/Loki first (Approach C).

structlog processes log events as dicts, which means: (1) contextual fields (request_id, adapter_name, source_type, item_id) are automatically attached via `bind_contextvars()` without changing call sites; (2) JSON output is parseable by any log aggregation tool without custom glog parsers; (3) the `SanitizingProcessor` for PII redaction operates on structured fields rather than regex-matching formatted strings, which is both more reliable and more surgical; (4) existing `logger.info("msg %s", arg)` calls still work via structlog's stdlib integration — no big-bang migration.

The trade-off is a new dependency (`structlog`) and a migration of the logging setup. The glog formatter is retired — its benefits (compact, familiar) are matched by structlog's console renderer, which adds color and key-value pairs. The `AgeRotatingFileHandler` is preserved since structlog doesn't replace file handling.

**Consequence:** `workbench/logging.py` is rewritten. `GlogFormatter` is removed. All new code uses structlog's native API (`structlog.get_logger()`). Old code using `logging.getLogger(__name__)` continues to work. The `SanitizingProcessor` is inserted into the structlog processing chain. workbench-meta inherits the setup and can add extra sanitizer patterns via the extension point.

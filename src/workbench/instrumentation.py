from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import structlog

from workbench.metrics import WorkbenchMetrics

logger = structlog.get_logger(__name__)


class InstrumentedSourceAdapter:
    """Decorator that wraps a SourceAdapter with metrics and structured logging."""

    def __init__(self, inner, adapter_name: str, metrics: WorkbenchMetrics):
        self._inner = inner
        self._name = adapter_name
        self._metrics = metrics

    async def poll(self, since: datetime | None = None):
        start = time.monotonic()
        try:
            items = await self._inner.poll(since)
            elapsed = time.monotonic() - start
            self._metrics.adapter_polls.labels(adapter=self._name, status="success").inc()
            self._metrics.adapter_poll_seconds.labels(adapter=self._name).observe(elapsed)
            for item in items:
                self._metrics.items_ingested.labels(
                    source_type=item.source_type, adapter=self._name,
                ).inc()
            logger.info("adapter_poll_complete",
                adapter=self._name, items=len(items), duration_ms=round(elapsed * 1000))
            return items
        except Exception as e:
            elapsed = time.monotonic() - start
            self._metrics.adapter_polls.labels(adapter=self._name, status="error").inc()
            self._metrics.adapter_poll_seconds.labels(adapter=self._name).observe(elapsed)
            logger.error("adapter_poll_failed",
                adapter=self._name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    def __getattr__(self, name):
        return getattr(self._inner, name)


class InstrumentedLLMProvider:
    """Decorator that wraps an LLMProvider with metrics and structured logging."""

    def __init__(self, inner, metrics: WorkbenchMetrics):
        self._inner = inner
        self._metrics = metrics

    async def _instrumented_call(self, method_name: str, coro):
        start = time.monotonic()
        try:
            result = await coro
            elapsed = time.monotonic() - start
            self._metrics.llm_calls.labels(method=method_name).inc()
            self._metrics.llm_call_seconds.labels(method=method_name).observe(elapsed)
            logger.info("llm_call_complete",
                method=method_name, duration_ms=round(elapsed * 1000))
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            self._metrics.llm_errors.labels(
                method=method_name, error_type=type(e).__name__,
            ).inc()
            logger.error("llm_call_failed",
                method=method_name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    async def extract_items(self, *args, **kwargs):
        return await self._instrumented_call(
            "extract", self._inner.extract_items(*args, **kwargs))

    async def score_relevance(self, *args, **kwargs):
        return await self._instrumented_call(
            "score_relevance", self._inner.score_relevance(*args, **kwargs))

    async def generate_triage_card(self, *args, **kwargs):
        return await self._instrumented_call(
            "generate_card", self._inner.generate_triage_card(*args, **kwargs))

    async def interpret_triage_response(self, *args, **kwargs):
        return await self._instrumented_call(
            "interpret_response", self._inner.interpret_triage_response(*args, **kwargs))

    async def describe_image(self, *args, **kwargs):
        return await self._instrumented_call(
            "describe_image", self._inner.describe_image(*args, **kwargs))

    async def evaluate_filter(self, *args, **kwargs):
        return await self._instrumented_call(
            "evaluate_filter", self._inner.evaluate_filter(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._inner, name)


class InstrumentedContextEnricher:
    """Decorator that wraps a ContextEnricher with metrics and structured logging."""

    def __init__(self, inner, enricher_name: str, metrics: WorkbenchMetrics):
        self._inner = inner
        self._name = enricher_name
        self._metrics = metrics

    async def enrich(self, *args, **kwargs):
        start = time.monotonic()
        try:
            result = await self._inner.enrich(*args, **kwargs)
            elapsed = time.monotonic() - start
            self._metrics.enrichment_seconds.labels(enricher=self._name).observe(elapsed)
            logger.info("enrichment_complete",
                enricher=self._name, duration_ms=round(elapsed * 1000))
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            self._metrics.enrichment_errors.labels(
                enricher=self._name, error_type=type(e).__name__,
            ).inc()
            logger.error("enrichment_failed",
                enricher=self._name, error=str(e), duration_ms=round(elapsed * 1000))
            raise

    def __getattr__(self, name):
        return getattr(self._inner, name)

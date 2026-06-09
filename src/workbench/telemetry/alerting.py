from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from workbench.config import AlertConfig, AlertConditions

logger = structlog.get_logger(__name__)


class AlertManager:
    def __init__(self, messenger, config: AlertConfig):
        self._messenger = messenger
        self._config = config
        self._last_fired: dict[str, datetime] = {}

    async def check_and_alert(self, health: dict[str, Any]) -> None:
        if not self._config.enabled or not self._messenger:
            return

        conditions = self._config.conditions
        now = datetime.now(timezone.utc)

        # Dead letters
        dl = health.get("dead_letter_count", 0)
        if dl >= conditions.dead_letter_threshold:
            await self._fire("dead_letters", f"⚠ {dl} dead letter entries need investigation", now)

        # Connection health
        for name, healthy in health.get("connections", {}).items():
            if not healthy:
                await self._fire(f"conn_{name}", f"⚠ Connection '{name}' is unhealthy", now)

        # Queue depth
        depth = health.get("ingestion_queue_depth", 0)
        if depth >= conditions.queue_depth_threshold:
            await self._fire("queue_depth", f"⚠ Ingestion queue depth is {depth}", now)

        # Adapter failures
        for name, failures in health.get("adapter_consecutive_failures", {}).items():
            if failures >= conditions.adapter_failure_threshold:
                await self._fire(f"adapter_{name}", f"⚠ Adapter '{name}' has {failures} consecutive failures", now)

    async def _fire(self, key: str, message: str, now: datetime) -> None:
        cooldown = timedelta(minutes=self._config.cooldown_minutes)
        last = self._last_fired.get(key)
        if last and (now - last) < cooldown:
            return

        try:
            await self._messenger.send_notification(message)
            self._last_fired[key] = now
            logger.info("alert_sent", alert_key=key, message=message)
        except Exception as e:
            logger.error("alert_send_failed", alert_key=key, error=str(e))

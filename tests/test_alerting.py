# tests/test_alerting.py

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.telemetry.alerting import AlertManager, AlertConfig, AlertConditions


@pytest.mark.asyncio
async def test_alert_on_dead_letters():
    messenger = AsyncMock()
    config = AlertConfig(conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 5}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_called_once()
    msg = messenger.send_notification.call_args[0][0]
    assert "dead letter" in msg.lower()


@pytest.mark.asyncio
async def test_alert_cooldown_prevents_duplicate():
    messenger = AsyncMock()
    config = AlertConfig(cooldown_minutes=60, conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 5}
    await mgr.check_and_alert(health)
    await mgr.check_and_alert(health)  # within cooldown

    assert messenger.send_notification.call_count == 1


@pytest.mark.asyncio
async def test_no_alert_below_threshold():
    messenger = AsyncMock()
    config = AlertConfig(conditions=AlertConditions(dead_letter_threshold=3))
    mgr = AlertManager(messenger, config)

    health = {"dead_letter_count": 2}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_connection_unhealthy_alert():
    messenger = AsyncMock()
    config = AlertConfig()
    mgr = AlertManager(messenger, config)

    health = {"connections": {"google": False}}
    await mgr.check_and_alert(health)

    messenger.send_notification.assert_called_once()
    msg = messenger.send_notification.call_args[0][0]
    assert "google" in msg.lower()

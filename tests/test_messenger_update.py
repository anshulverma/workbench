import pytest
from workbench.domain import CardMessage, CardSection
from workbench.providers.messenger.base import Messenger
from workbench.providers.messenger.console import ConsoleMessenger


class _Bare(Messenger):
    async def send_card(self, card):
        return "x"

    async def poll_responses(self, since_message_id=None):
        return []


@pytest.mark.asyncio
async def test_base_update_message_default_false():
    assert await _Bare().update_message("m1", CardMessage(header="h")) is False


@pytest.mark.asyncio
async def test_console_update_message_renders_card_returns_true(capsys):
    ok = await ConsoleMessenger().update_message(
        "m1", CardMessage(header="Diff D1", sections=[CardSection(title="t", body="b")])
    )
    assert ok is True
    out = capsys.readouterr().out
    assert "Diff D1" in out
    assert "[UPDATE m1]" in out

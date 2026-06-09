import pytest
from workbench.domain import CardMessage, CardSection, CardLink, TriageOption
from workbench.providers.messenger.base import Messenger
from workbench.providers.messenger.console import ConsoleMessenger


def test_render_to_text_flattens_header_sections_links_options():
    base = ConsoleMessenger()  # uses inherited default render_to_text
    msg = CardMessage(
        header="Diff D123 — add retry",
        sections=[
            CardSection(title="Summary", body="adds retry loop"),
            CardSection(title="Hunk", body="+ retry()", monospace=True),
        ],
        links=[CardLink(label="View in Phabricator", url="https://phab/D123")],
        options=[
            TriageOption(label="Add P1", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = base.render_to_text(msg)
    assert "Diff D123 — add retry" in text
    assert "Summary" in text
    assert "adds retry loop" in text
    assert "View in Phabricator" in text
    assert "https://phab/D123" in text
    assert "1. Add P1" in text
    assert "2. Skip" in text


@pytest.mark.asyncio
async def test_console_send_card_accepts_cardmessage_and_returns_id():
    base = ConsoleMessenger()
    msg = CardMessage(header="Hello", sections=[CardSection(title="t", body="b")])
    msg_id = await base.send_card(msg)
    assert isinstance(msg_id, str)
    assert msg_id.startswith("console-")


@pytest.mark.asyncio
async def test_console_send_card_accepts_plain_string_back_compat():
    base = ConsoleMessenger()
    msg_id = await base.send_card("Got it -- Add P1")
    assert isinstance(msg_id, str)
    assert msg_id.startswith("console-")

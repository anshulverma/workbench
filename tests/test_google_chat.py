import pytest
import json
from unittest.mock import patch, MagicMock
from server.providers.messenger.google_chat import GoogleChatMessenger


@pytest.fixture
def messenger():
    return GoogleChatMessenger(space_id="AAQA-RI-cA4", google_api_script="/fake/script.py")


@pytest.mark.asyncio
async def test_send_card(messenger):
    mock_result = MagicMock(returncode=0, stdout=json.dumps({"success": True, "data": {"name": "spaces/X/messages/Y"}}))
    with patch("subprocess.run", return_value=mock_result):
        msg_id = await messenger.send_card("test message")
        assert msg_id == "spaces/X/messages/Y"


@pytest.mark.asyncio
async def test_poll_responses_filters_human(messenger):
    messages = [
        {"name": "msg1", "sender_type": "BOT", "text": "card"},
        {"name": "msg2", "sender_type": "HUMAN", "text": "1"},
    ]
    mock_result = MagicMock(returncode=0, stdout=json.dumps({"success": True, "data": {"messages": messages}}))
    with patch("subprocess.run", return_value=mock_result):
        responses = await messenger.poll_responses()
        assert len(responses) == 1
        assert responses[0]["text"] == "1"

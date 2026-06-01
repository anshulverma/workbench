# tests/test_google_chat_messenger.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.providers.messenger.google_chat import GoogleChatMessenger


@pytest.fixture
def mock_http_client():
    return AsyncMock()


@pytest.fixture
def messenger(mock_http_client):
    config = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/AAQA-RI-cA4",
        service_account_key_path="/fake/key.json",
    )
    m = GoogleChatMessenger(config)
    m._client = mock_http_client
    m._credentials = MagicMock()
    m._credentials.valid = True
    m._credentials.token = "fake-token"
    return m


@pytest.mark.asyncio
async def test_send_card_posts_message(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"name": "spaces/AAQA-RI-cA4/messages/msg123"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    msg_id = await messenger.send_card("*Test Card*\n1. Add todo\n2. Skip")

    assert msg_id == "spaces/AAQA-RI-cA4/messages/msg123"
    mock_http_client.post.assert_called_once()
    call_kwargs = mock_http_client.post.call_args
    assert "text" in call_kwargs[1]["json"]


@pytest.mark.asyncio
async def test_send_card_raises_on_failure(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = Exception("API error")
    mock_http_client.post.return_value = mock_response

    with pytest.raises(Exception, match="API error"):
        await messenger.send_card("test")


@pytest.mark.asyncio
async def test_send_card_refreshes_expired_token(messenger, mock_http_client):
    messenger._credentials.valid = False

    mock_response = MagicMock()
    mock_response.json.return_value = {"name": "spaces/x/messages/msg1"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    await messenger.send_card("test")

    messenger._credentials.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_poll_responses_returns_messages_after_id(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg100", "sender": {"type": "BOT"}, "text": "card"},
            {"name": "spaces/x/messages/msg101", "sender": {"type": "HUMAN"}, "text": "1"},
            {"name": "spaces/x/messages/msg102", "sender": {"type": "HUMAN"}, "text": "skip all"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses("spaces/x/messages/msg100")

    assert len(responses) == 2
    assert responses[0]["text"] == "1"
    assert responses[1]["text"] == "skip all"
    # Verify chronological ordering is requested
    call_kwargs = mock_http_client.get.call_args
    assert call_kwargs[1]["params"]["orderBy"] == "createTime asc"


@pytest.mark.asyncio
async def test_poll_responses_filters_bot_messages(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg100", "sender": {"type": "BOT"}, "text": "card"},
            {"name": "spaces/x/messages/msg101", "sender": {"type": "BOT"}, "text": "Got it"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses("spaces/x/messages/msg100")
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_poll_responses_no_since_returns_all_human(messenger, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "messages": [
            {"name": "spaces/x/messages/msg1", "sender": {"type": "HUMAN"}, "text": "2"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    responses = await messenger.poll_responses(None)
    assert len(responses) == 1


@pytest.mark.asyncio
async def test_close_closes_http_client(messenger, mock_http_client):
    await messenger.close()
    mock_http_client.aclose.assert_called_once()


def test_provider_config_validation():
    config = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/ABC",
        service_account_key_path="/path/to/key.json",
    )
    assert config.space_id == "spaces/ABC"


def test_provider_config_timeout_default():
    config = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/ABC",
        service_account_key_path="/path/to/key.json",
    )
    assert config.timeout_seconds == 30

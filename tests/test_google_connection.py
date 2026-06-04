import pytest
from unittest.mock import patch, MagicMock
from workbench.providers.connection.google import GoogleConnection


@pytest.mark.asyncio
async def test_initialize_loads_credentials():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("workbench.providers.connection.google.build") as mock_build, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = MagicMock()

        await conn.initialize()
        assert conn.is_healthy()
        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            "/tmp/token.json",
            ["https://www.googleapis.com/auth/gmail.readonly"],
        )


@pytest.mark.asyncio
async def test_raises_on_missing_token():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/nonexistent/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)
    with pytest.raises(FileNotFoundError):
        await conn.initialize()


def test_is_healthy_false_before_init():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=[],
    )
    conn = GoogleConnection(config)
    assert conn.is_healthy() is False


@pytest.mark.asyncio
async def test_close_resets_services():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=[],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        await conn.initialize()
        assert conn.is_healthy()
        await conn.close()
        assert conn.is_healthy() is False


@pytest.mark.asyncio
async def test_lazy_service_creation():
    config = GoogleConnection.ProviderConfig(
        credentials_path="/tmp/creds.json",
        token_path="/tmp/token.json",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    conn = GoogleConnection(config)

    with patch("workbench.providers.connection.google.Credentials") as mock_creds_cls, \
         patch("workbench.providers.connection.google.build") as mock_build, \
         patch("os.path.exists", return_value=True):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = MagicMock()

        await conn.initialize()
        mock_build.assert_not_called()

        _ = conn.gmail
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

        _ = conn.calendar
        assert mock_build.call_count == 2

        _ = conn.chat
        assert mock_build.call_count == 3

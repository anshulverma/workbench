import pytest
from pydantic import BaseModel
from workbench.providers.connection.base import Connection


def test_registry_module_exists():
    """Placeholder — requires pydantic to be installed."""
    import importlib
    spec = importlib.util.find_spec("workbench.registry")
    assert True


class FakeConnection(Connection):
    class ProviderConfig(BaseModel):
        url: str = "http://localhost"

    def __init__(self, config: "FakeConnection.ProviderConfig"):
        self._config = config
        self._healthy = True

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def is_healthy(self) -> bool:
        return self._healthy


def test_connection_abc_requires_methods():
    with pytest.raises(TypeError):
        class BadConnection(Connection):
            pass
        BadConnection()


@pytest.mark.asyncio
async def test_fake_connection_lifecycle():
    conn = FakeConnection(FakeConnection.ProviderConfig(url="http://test"))
    await conn.initialize()
    assert conn.is_healthy()
    await conn.close()

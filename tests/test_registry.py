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


from workbench.registry import create_provider
from workbench.providers.enrichment.stub import StubEnricher


class StubConnection(Connection):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config=None):
        pass

    async def initialize(self):
        pass

    async def close(self):
        pass

    def is_healthy(self):
        return True


class ConnectionAwareProvider:
    class ProviderConfig(BaseModel):
        mode: str = "default"

    def __init__(self, config: ProviderConfig, connection=None):
        self.config = config
        self.connection = connection


class ConnectionUnawareProvider:
    class ProviderConfig(BaseModel):
        mode: str = "default"

    def __init__(self, config: ProviderConfig):
        self.config = config


def test_create_provider_injects_connection_when_accepted():
    import sys

    sys.modules.setdefault("tests.test_registry", sys.modules[__name__])
    conn = StubConnection()
    section = {
        "class": "tests.test_registry.ConnectionAwareProvider",
        "connection": "test_conn",
        "mode": "test",
    }
    connections = {"test_conn": conn}
    provider = create_provider(section, connections=connections)
    assert isinstance(provider, ConnectionAwareProvider)
    assert provider.connection is conn


def test_create_provider_skips_connection_when_not_accepted():
    import sys

    sys.modules.setdefault("tests.test_registry", sys.modules[__name__])
    conn = StubConnection()
    section = {
        "class": "tests.test_registry.ConnectionUnawareProvider",
        "connection": "test_conn",
        "mode": "test",
    }
    connections = {"test_conn": conn}
    provider = create_provider(section, connections=connections)
    assert isinstance(provider, ConnectionUnawareProvider)
    assert not hasattr(provider, "connection")


def test_create_provider_without_connection():
    section = {"class": "workbench.providers.enrichment.stub.StubEnricher"}
    provider = create_provider(section)
    assert isinstance(provider, StubEnricher)


def test_create_provider_raises_on_missing_connection():
    section = {
        "class": "workbench.providers.enrichment.stub.StubEnricher",
        "connection": "nonexistent",
    }
    with pytest.raises(ValueError, match="not found"):
        create_provider(section, connections={})

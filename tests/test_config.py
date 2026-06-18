import os
from workbench.config import EnrichmentConfig, load_config_from_string


def test_load_config_placeholder():
    """Placeholder — requires omegaconf to be installed."""
    assert True


def test_config_example_exists():
    assert os.path.exists("config.example.yml")


def test_alembic_ini_exists():
    assert os.path.exists("alembic.ini")


def test_triage_config_poll_interval_default():
    from workbench.config import TriageConfig

    config = TriageConfig()
    # Default raised 0.5s -> 5s (b585d2e): sub-second polling overran each tick
    # (the messenger poll takes seconds), flooding apscheduler skip warnings.
    assert config.triage_poll_interval_seconds == 5.0


def test_triage_config_poll_interval_custom():
    from workbench.config import TriageConfig

    config = TriageConfig(triage_poll_interval_seconds=1)
    assert config.triage_poll_interval_seconds == 1


def test_server_config_ssl_defaults_none():
    from workbench.config import ServerConfig

    # No TLS by default — base deployment serves plain HTTP behind an SSH tunnel.
    config = ServerConfig()
    assert config.ssl_certfile is None
    assert config.ssl_keyfile is None


def test_server_config_ssl_parsed():
    yaml_str = """
version: "0.3.0"
server:
  host: "::"
  port: 44201
  ssl_certfile: /etc/pki/tls/certs/host.crt
  ssl_keyfile: /etc/pki/tls/certs/host.key
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert config.server.port == 44201
    assert config.server.ssl_certfile == "/etc/pki/tls/certs/host.crt"
    assert config.server.ssl_keyfile == "/etc/pki/tls/certs/host.key"


def test_connections_section_parsed():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
connections:
  google:
    class: workbench.providers.connection.google.GoogleConnection
    credentials_path: /tmp/creds.json
"""
    config = load_config_from_string(yaml_str)
    assert "google" in config.connections
    assert (
        config.connections["google"]["class"]
        == "workbench.providers.connection.google.GoogleConnection"
    )


def test_connections_section_optional():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert config.connections == {}


def test_enrichment_config_new_shape():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
enrichment:
  providers:
    - class: workbench.providers.enrichment.stub.StubEnricher
      source_types: ["email"]
  default:
    class: workbench.providers.enrichment.stub.StubEnricher
"""
    config = load_config_from_string(yaml_str)
    assert isinstance(config.enrichment, EnrichmentConfig)
    assert len(config.enrichment.providers) == 1
    assert config.enrichment.providers[0]["source_types"] == ["email"]
    assert (
        config.enrichment.default["class"]
        == "workbench.providers.enrichment.stub.StubEnricher"
    )


def test_enrichment_config_defaults():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
"""
    config = load_config_from_string(yaml_str)
    assert isinstance(config.enrichment, EnrichmentConfig)
    assert config.enrichment.providers == []
    assert (
        config.enrichment.default["class"]
        == "workbench.providers.enrichment.stub.StubEnricher"
    )


def test_enrichment_backward_compat_dict():
    yaml_str = """
version: "0.3.0"
storage:
  postgres_dsn: postgres://localhost/workbench
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher
"""
    config = load_config_from_string(yaml_str)
    assert isinstance(config.enrichment, EnrichmentConfig)
    assert (
        config.enrichment.default["class"]
        == "workbench.providers.enrichment.stub.StubEnricher"
    )

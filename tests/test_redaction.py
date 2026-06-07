import pytest

from workbench.redaction import REDACTED, redact_secrets


@pytest.mark.parametrize(
    "key",
    [
        "api_token",
        "API_KEY",
        "client_secret",
        "db_password",
        "postgres_dsn",
        "google_credential",
        "service_account_key_path",
    ],
)
def test_redacts_secret_key_names(key):
    out = redact_secrets({key: "supersecret-value"})
    assert out[key] == REDACTED
    assert "supersecret-value" not in str(out)


def test_keeps_safe_keys():
    out = redact_secrets({"space_id": "spaces/AAA", "timeout_seconds": 5})
    assert out == {"space_id": "spaces/AAA", "timeout_seconds": 5}


def test_recurses_nested_dicts_and_lists():
    raw = {
        "server": {"api_token": "tok-AAA", "port": 8421},
        "sources": [{"adapter_type": "github", "config": {"token": "tok-XXX"}}],
    }
    out = redact_secrets(raw)
    assert out["server"]["api_token"] == REDACTED
    assert out["server"]["port"] == 8421
    assert out["sources"][0]["config"]["token"] == REDACTED
    assert out["sources"][0]["adapter_type"] == "github"
    assert "tok-AAA" not in str(out) and "tok-XXX" not in str(out)


def test_explicit_field_denylist():
    out = redact_secrets({"service_account_key_path": "/etc/sa.json"})
    assert out["service_account_key_path"] == REDACTED


def test_depth_guard_returns_marker():
    deep = cur = {}
    for _ in range(15):
        cur["nested"] = {}
        cur = cur["nested"]
    out = redact_secrets(deep)
    assert "..." in str(out)

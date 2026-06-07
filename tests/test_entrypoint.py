import importlib
from unittest.mock import patch

import workbench.__main__ as wm


def test_main_binds_config_server_host(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        'version: "0.1.0"\n'
        "server: {host: 1.2.3.4, port: 9999}\n"
        "storage: {postgres_dsn: postgres://x}\n"
        "llm: {class: workbench.providers.llm.anthropic.AnthropicLLM, api_key: k, model: m}\n"
    )
    monkeypatch.setenv("WORKBENCH_CONFIG", str(cfg))
    monkeypatch.delenv("WORKBENCH_CONFIG_OVERRIDE", raising=False)
    with patch("uvicorn.run") as run:
        wm.main()
    kwargs = run.call_args.kwargs
    assert kwargs["host"] == "1.2.3.4"
    assert kwargs["port"] == 9999

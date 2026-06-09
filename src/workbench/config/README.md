# config

Typed application config.

- `models.py` — pydantic config models (`ServerConfig` … `AppConfig`).
- `loader.py` — YAML + OmegaConf loader (`load_config`, `load_config_from_string`).
- `writer.py` — ruamel.yaml round-trip write-back for `sources:`/`messenger:` nodes (ADR 0013).

`workbench.config.load_config` is the public entry point. The package
`__init__` re-exports the full surface, so `from workbench.config import X`
continues to resolve every config model plus the loader functions.

from __future__ import annotations

import sys
from pathlib import Path

from omegaconf import OmegaConf

from workbench.config.models import AppConfig


def load_config(config_path: str, override_path: str | None = None) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print("Run 'cp config.example.yml config.yml' and edit it.", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)

    config = AppConfig(**resolved)

    major = int(config.version.split(".")[0])
    expected_major = 0
    if major != expected_major:
        print(
            f"Error: Config version {config.version} is incompatible (expected major {expected_major})",
            file=sys.stderr,
        )
        sys.exit(1)

    return config


def load_config_from_string(yaml_str: str) -> AppConfig:
    raw = OmegaConf.create(yaml_str)
    resolved = OmegaConf.to_container(raw, resolve=True)
    return AppConfig(**resolved)

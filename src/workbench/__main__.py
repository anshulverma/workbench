"""`python -m workbench` -- start the Workbench server (replaces `workbench serve`)."""

from __future__ import annotations

import os

import uvicorn

from workbench.config import load_config


def main() -> None:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    config = load_config(config_path, override_path)
    uvicorn.run(
        "workbench.runtime.app:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
    )


if __name__ == "__main__":
    main()

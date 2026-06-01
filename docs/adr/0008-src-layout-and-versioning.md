# ADR 0008: src/workbench/ Package Layout and Versioning

The codebase moves from `server/` to `src/workbench/` for proper Python packaging. The `workbench` package is the importable name — YAML config class paths use `workbench.providers.llm.claude.ClaudeProvider`, not `server.providers...`. This aligns with Python packaging conventions (`src` layout) and enables `pip install -e .` for development.

Two independent version numbers:

**App version** (`src/workbench/__init__.py` as `__version__ = "0.1.0"`): Semantic versioning of the Workbench server. Bumped on every feature, bugfix, or breaking change. Exposed in the `/health` endpoint response and docker image tags.

**Config version** (`version: 0.1.0` in `config.yml`): Semantic versioning of the config file format. Bumped only when the config schema changes (new required sections, renamed keys, removed options). Independent of the app version — config `0.1.0` may stay stable across app versions `0.1.0` through `0.5.0`. Server validates at startup: same major = compatible, different major = hard error with migration instructions, minor/patch mismatch = warn but proceed.

We chose independent versioning because tying them together would mean bumping the config version on every release, making it meaningless for its actual purpose: detecting config incompatibilities.

We chose the `src/` layout over flat `workbench/` at repo root because: (1) it prevents accidental imports of the local directory during development (a common Python packaging pitfall); (2) it's the layout recommended by setuptools and the Python packaging authority.

**Consequence:** All imports change from `server.X` to `workbench.X`. The Dockerfile copies from `src/` instead of `server/`. `pyproject.toml` (or `setup.cfg`) declares the `workbench` package with `package_dir = {"": "src"}`. The `/health` endpoint returns `{"status": "ok", "version": "0.1.0", ...}`. Alembic migrations live at `src/workbench/migrations/`.

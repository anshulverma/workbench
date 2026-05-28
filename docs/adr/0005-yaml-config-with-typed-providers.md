# ADR 0005: YAML Config with Typed Provider Registration

Provider selection and configuration is driven by YAML config files, not env vars or a central Settings class. Each provider declares a `ProviderConfig` pydantic model. The server resolves providers via `importlib.import_module` from dotted class paths in the YAML, validates config against the provider's model, and constructs the provider. OmegaConf handles env var interpolation for secrets. Config files are layered (base + override via deep merge).

We chose this over:

- **Pydantic-settings with env vars** (Approach B) — env vars don't compose well for nested provider-specific config. Would either require JSON blobs in env vars (ugly, untyped) or a single bloated Settings class that knows about every provider (violates provider agnosticism).
- **Hydra/OmegaConf for everything** (Approach C) — Hydra's `_target_` + `instantiate` handles provider construction well, but pulls in a heavy dependency and replaces pydantic's validation with OmegaConf's weaker type system. We use OmegaConf only for env var interpolation, keeping pydantic for validation.
- **Untyped dict config** (Approach D) — passing `dict[str, Any]` to providers sacrifices type safety. Errors surface at runtime deep in provider code instead of at startup during config validation.

The YAML + ProviderConfig pattern gives: (1) full type safety at startup via pydantic, (2) clean secrets handling via OmegaConf interpolation, (3) server stays completely provider-agnostic (never imports specific providers), (4) layered merge enables internal override configs without duplicating the base.

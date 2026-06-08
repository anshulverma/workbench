import pytest
from workbench.config import AppConfig, PresentationConfig
from workbench.pipeline.presenter import (
    build_composite_presenter,
    PlainCardPresenter,
    CompositeCardPresenter,
)


def _base_cfg(presentation=None):
    data = {
        "version": "0.4.0",
        "storage": {"postgres_dsn": "postgres://x/y"},
        "llm": {
            "class": "workbench.providers.llm.anthropic.AnthropicLLM",
            "api_key": "k",
        },
    }
    if presentation is not None:
        data["presentation"] = presentation
    return AppConfig(**data)


def test_presentation_absent_defaults_to_empty():
    cfg = _base_cfg()
    assert isinstance(cfg.presentation, PresentationConfig)
    assert cfg.presentation.providers == []


def test_build_presenter_absent_yields_empty_composite_with_plain_default():
    cfg = _base_cfg()
    presenter = build_composite_presenter(cfg.presentation)
    assert isinstance(presenter, CompositeCardPresenter)
    assert isinstance(presenter._default, PlainCardPresenter)
    assert presenter._by_source_type == {}


def test_build_presenter_unimportable_class_hard_errors():
    cfg = _base_cfg(
        {"providers": [{"source_type": "diff", "class": "workbench_meta.nope.Missing"}]}
    )
    with pytest.raises(ImportError):
        build_composite_presenter(cfg.presentation)


def test_config_version_is_minor_bumped():
    cfg = _base_cfg()
    assert cfg.version == "0.4.0"

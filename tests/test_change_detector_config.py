from workbench.pipeline.scheduler import build_change_detectors
from workbench.providers.change_detector.base import ChangeDetector

_DET = "workbench.providers.change_detector.fallback.AlwaysMaterialDetector"


def test_empty_sources_yields_empty_registry():
    assert build_change_detectors([]) == {}


def test_source_without_change_detector_is_skipped():
    registry = build_change_detectors([{"class": "some.Adapter"}])
    assert registry == {}


def test_configured_detector_registered_by_source_type():
    registry = build_change_detectors(
        [
            {
                "class": "some.Adapter",
                "change_detector": {"class": _DET, "source_type_name": "diff"},
            },
        ]
    )
    assert "diff" in registry
    assert isinstance(registry["diff"], ChangeDetector)
    assert registry["diff"].source_type() == "diff"


def test_unregistered_source_type_absent_from_registry():
    registry = build_change_detectors(
        [
            {
                "class": "some.Adapter",
                "change_detector": {"class": _DET, "source_type_name": "diff"},
            },
        ]
    )
    assert registry.get("task") is None

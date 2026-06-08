import pytest

from workbench.providers.change_detector.base import ChangeDetector, ChangeResult
from workbench.providers.change_detector.fallback import AlwaysMaterialDetector


def test_always_material_detects_difference():
    d = AlwaysMaterialDetector("diff")
    r = d.detect({"status": "needs_review"}, {"status": "accepted"})
    assert r.is_material is True
    assert r.is_terminal is False


def test_always_material_treats_equal_as_material():
    d = AlwaysMaterialDetector("diff")
    r = d.detect({"x": 1}, {"x": 1})
    assert r.is_material is True


def test_always_material_source_type():
    assert AlwaysMaterialDetector("diff").source_type() == "diff"


def test_change_result_is_critical_defaults_false():
    r = ChangeResult(is_material=True)
    assert r.is_critical is False


def test_change_result_is_terminal_defaults_false():
    r = ChangeResult(is_material=True)
    assert r.is_terminal is False


def test_change_detector_is_abstract():
    with pytest.raises(TypeError):
        ChangeDetector()  # cannot instantiate abstract base

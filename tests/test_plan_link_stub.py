"""Plan carries an item_paths stub field so the future creation site can call
record('plan', plan.id, plan.item_paths) in one line (no end-to-end wiring yet)."""

from workbench.domain.plans import Plan


def test_plan_has_item_paths_stub_default_empty():
    p = Plan(title="t")
    assert p.item_paths == []


def test_plan_accepts_item_paths():
    p = Plan(title="t", item_paths=["123", "123.1"])
    assert p.item_paths == ["123", "123.1"]

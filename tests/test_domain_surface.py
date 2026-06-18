"""Guard the cross-repo public surface of ``workbench.domain``.

These 12 symbols are what ``workbench-meta`` (diff presenter, gchat messenger,
adapters) imports. They must stay importable from ``workbench.domain``.
"""

import inspect


def test_cross_repo_symbols_importable() -> None:
    from workbench.domain import (
        CardLink,
        CardMessage,
        CardSection,
        ChangeContext,
        DiffCardContent,
        EnrichmentBudget,
        ExtractedItem,
        ItemCategory,
        RawItem,
        ThreadHunk,
        TriageCard,
        TriageOption,
    )

    symbols = [
        RawItem,
        ExtractedItem,
        EnrichmentBudget,
        ChangeContext,
        CardMessage,
        CardSection,
        CardLink,
        ThreadHunk,
        TriageOption,
        TriageCard,
        DiffCardContent,
        ItemCategory,
    ]
    assert len(symbols) == 12
    for sym in symbols:
        assert inspect.isclass(sym), f"{sym!r} is not a class/enum"


def test_item_status_has_lineage_stages():
    from workbench.domain import ItemStatus

    assert ItemStatus.INGESTED.value == "ingested"
    assert ItemStatus.EXTRACTED.value == "extracted"


def test_item_carries_seq_and_path():
    from workbench.domain import Item, ItemCategory, ItemOrigin, Priority

    root = Item(
        source_type="diff",
        source_id="D1",
        summary="s",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.MANUAL,
        priority=Priority.P2,
    )
    # defaults: unset until persisted / allocated
    assert root.seq is None
    assert root.path is None

    child = Item(
        source_type="diff",
        source_id="D1",
        summary="c",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        seq=1,
        path="123.1",
        parent_item_id=123,
    )
    assert child.seq == 1
    assert child.path == "123.1"

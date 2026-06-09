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

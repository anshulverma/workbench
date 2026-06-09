import logging

from pydantic import ValidationError

from workbench.domain import (
    TriageCard,
    TriageOption,
    ExtractedItem,
    RawItem,
    ItemCategory,
    CardMessage,
    CardSection,
)
from workbench.pipeline.presenter import (
    CardPresenter,
    PlainCardPresenter,
    CompositeCardPresenter,
)


def _item(source_type="diff") -> ExtractedItem:
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


def _plain_card() -> TriageCard:
    return TriageCard(
        card_content={
            "card_body": "PR #200 from alice",
            "summary": "Review PR #200",
            "source_type": "diff",
        },
        options=[
            TriageOption(label="Add P1", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )


def test_plain_presenter_wraps_format_card_for_chat():
    msg = PlainCardPresenter().render(_plain_card(), _item())
    assert isinstance(msg, CardMessage)
    assert "PR #200 from alice" in msg.header or any(
        "PR #200 from alice" in s.body for s in msg.sections
    )
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]


def test_composite_routes_by_source_type():
    class Marker(CardPresenter):
        def render(self, card, item):
            return CardMessage(header="DIFF-PRESENTER")

    comp = CompositeCardPresenter(
        by_source_type={"diff": Marker()}, default=PlainCardPresenter()
    )
    assert comp.render(_plain_card(), _item("diff")).header == "DIFF-PRESENTER"


def test_composite_unknown_source_type_uses_default():
    comp = CompositeCardPresenter(by_source_type={}, default=PlainCardPresenter())
    msg = comp.render(_plain_card(), _item("github"))
    assert isinstance(msg, CardMessage)
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]


def test_composite_delegate_failure_falls_back_to_default(caplog):
    class Boom(CardPresenter):
        def render(self, card, item):
            raise RuntimeError("kaboom")

    comp = CompositeCardPresenter(
        by_source_type={"diff": Boom()}, default=PlainCardPresenter()
    )
    with caplog.at_level(logging.WARNING):
        msg = comp.render(_plain_card(), _item("diff"))
    assert isinstance(msg, CardMessage)
    assert any("presenter_failure" in r.message for r in caplog.records)


def test_composite_content_invalid_logs_and_falls_back(caplog):
    class BadContent(CardPresenter):
        def render(self, card, item):
            CardSection.model_validate(
                {}
            )  # raises ValidationError (title/body required)
            return CardMessage(header="never")

    comp = CompositeCardPresenter(
        by_source_type={"diff": BadContent()}, default=PlainCardPresenter()
    )
    with caplog.at_level(logging.WARNING):
        msg = comp.render(_plain_card(), _item("diff"))
    assert isinstance(msg, CardMessage)
    assert [o.label for o in msg.options] == ["Add P1", "Skip"]
    assert any("presenter_content_invalid" in r.message for r in caplog.records)


def test_empty_composite_routes_all_to_default():
    comp = CompositeCardPresenter(by_source_type={}, default=PlainCardPresenter())
    msg = comp.render(_plain_card(), _item("anything"))
    assert isinstance(msg, CardMessage)

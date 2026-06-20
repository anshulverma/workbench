"""The lineage store ABCs and Stores container wiring."""

import inspect

from workbench.storage.base import (
    EntityLink,
    EntityLinkStore,
    MessageStore,
    LlmCallStore,
    Stores,
)


def test_entity_link_dataclass_fields():
    link = EntityLink(
        entity_type="llm_call",
        entity_id=7,
        item_id=42,
        item_path="123.1",
        correlation_id=None,
    )
    assert link.entity_type == "llm_call"
    assert link.entity_id == 7
    assert link.item_path == "123.1"


def test_entity_link_store_abstract_methods():
    methods = {
        name for name, _ in inspect.getmembers(EntityLinkStore, inspect.isfunction)
    }
    assert {
        "record",
        "record_by_correlation",
        "unlink_entity",
        "for_item",
        "for_entity",
    } <= methods


def test_message_store_abstract_methods():
    methods = {name for name, _ in inspect.getmembers(MessageStore, inspect.isfunction)}
    assert {"save", "get_by_id", "list_recent", "delete_older_than"} <= methods


def test_llm_call_store_save_many_accepts_entity_links_kwarg():
    sig = inspect.signature(LlmCallStore.save_many)
    assert "entity_links" in sig.parameters


def test_stores_accepts_entity_links_and_messages():
    sig = inspect.signature(Stores.__init__)
    assert "entity_links" in sig.parameters
    assert "messages" in sig.parameters

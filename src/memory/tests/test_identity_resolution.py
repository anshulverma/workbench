import pytest
from memory.queue import PendingIngestionStore
from memory.models import (
    STRONG_SIGNAL_KEYS, MEDIUM_SIGNAL_KEYS, WEAK_SIGNAL_KEYS,
    SIGNAL_SCORES, MERGE_THRESHOLD,
)

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"


@pytest.fixture
async def store():
    s = PendingIngestionStore(TEST_DSN)
    await s.initialize()
    await s.pool.execute("DELETE FROM entity_identities")
    await s.pool.execute("DELETE FROM entities")
    yield s
    await s.close()


# --- Signal tier constants ---


def test_signal_tier_constants():
    assert "email" in STRONG_SIGNAL_KEYS
    assert "phone" in STRONG_SIGNAL_KEYS
    assert "platform_uid" in STRONG_SIGNAL_KEYS
    assert "name" in MEDIUM_SIGNAL_KEYS
    assert "username" in MEDIUM_SIGNAL_KEYS
    assert "first_name" in WEAK_SIGNAL_KEYS
    assert "timezone" in WEAK_SIGNAL_KEYS
    assert "title" in WEAK_SIGNAL_KEYS
    assert SIGNAL_SCORES["strong"] == 10
    assert SIGNAL_SCORES["medium"] == 5
    assert SIGNAL_SCORES["weak"] == 1
    assert MERGE_THRESHOLD == 10


# --- resolve_identity ---


@pytest.mark.asyncio
async def test_first_entity_creates_canonical_self_mapping(store):
    """First time seeing an entity creates identity mapping to itself."""
    canonical = await store.resolve_identity(
        "person", "github:alice-gh",
        {"email": "alice@meta.com", "name": "Alice Smith", "team": "infra"},
    )
    assert canonical == "github:alice-gh"

    mapping = await store.get_canonical("person", "github:alice-gh")
    assert mapping == "github:alice-gh"


@pytest.mark.asyncio
async def test_strong_signal_match_merges(store):
    """Matching on a strong signal (email, 10pts >= threshold 10) merges."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "name": "Alice Smith",
    })

    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com", "name": "Alice S."},
    )
    assert canonical == "github:alice-gh"

    mapping = await store.get_canonical("person", "email:alice@meta.com")
    assert mapping == "github:alice-gh"


@pytest.mark.asyncio
async def test_medium_signals_merge_when_combined(store):
    """Two medium signals (name=5 + username=5 = 10) hit threshold."""
    await store.upsert_entity("person", "github:alice-gh", {
        "name": "Alice Smith", "username": "asmith",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "name": "Alice Smith", "username": "asmith",
    })

    canonical = await store.resolve_identity(
        "person", "slack:asmith",
        {"name": "Alice Smith", "username": "asmith"},
    )
    assert canonical == "github:alice-gh"


@pytest.mark.asyncio
async def test_weak_signals_alone_do_not_merge(store):
    """Weak signals alone (first_name=1) never hit threshold."""
    await store.upsert_entity("person", "github:alice-gh", {
        "first_name": "Alice",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "first_name": "Alice",
    })

    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"first_name": "Alice"},
    )
    # Not merged -- separate canonical
    assert canonical == "email:alice@meta.com"


@pytest.mark.asyncio
async def test_no_cross_type_merge(store):
    """person and repo entities with same signals should not merge."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    canonical = await store.resolve_identity(
        "repo", "repo:alice@meta.com",
        {"email": "alice@meta.com"},
    )
    # Different entity_type -- must not merge
    assert canonical == "repo:alice@meta.com"


@pytest.mark.asyncio
async def test_get_canonical_returns_none_for_unknown(store):
    result = await store.get_canonical("person", "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_identity_idempotent(store):
    """Calling resolve_identity twice with same source_id returns same canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    c1 = await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    c2 = await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    assert c1 == c2


# --- query_entity through resolution ---


@pytest.mark.asyncio
async def test_query_entity_resolves_through_identity(store):
    """Querying by alias returns merged facts from canonical entity."""
    # Create canonical entity
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })

    # Create alias that merges into canonical
    canonical = await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com", "role": "tech lead"},
    )
    assert canonical == "github:alice-gh"

    # Upsert the new facts under the canonical id
    await store.upsert_entity("person", canonical, {"role": "tech lead"})

    # Query by alias should return canonical's merged facts
    entity = await store.get_entity_resolved("person", "email:alice@meta.com")
    assert entity is not None
    assert entity["entity_id"] == "github:alice-gh"
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_get_entity_resolved_returns_none_for_unknown(store):
    entity = await store.get_entity_resolved("person", "nonexistent")
    assert entity is None

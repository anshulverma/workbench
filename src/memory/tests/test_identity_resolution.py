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


# --- Late discovery merge ---


@pytest.mark.asyncio
async def test_late_discovery_merge(store):
    """When new facts reveal two separate entities are the same person, merge them."""
    # Two entities created separately with no overlap
    await store.upsert_entity("person", "github:alice-gh", {
        "name": "Alice Smith", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "name": "Alice Smith", "team": "infra",
    })

    await store.upsert_entity("person", "email:alice@meta.com", {
        "name": "Alice S.", "role": "tech lead",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "name": "Alice S.", "role": "tech lead",
    })

    # They should be separate at this point (names differ slightly)
    c1 = await store.get_canonical("person", "github:alice-gh")
    c2 = await store.get_canonical("person", "email:alice@meta.com")
    assert c1 != c2

    # Late discovery: we learn email:alice@meta.com has the same email as github:alice-gh
    merged = await store.late_discovery_merge(
        "person", "github:alice-gh", "email:alice@meta.com"
    )
    assert merged is True

    # Now email alias resolves to github canonical
    c_after = await store.get_canonical("person", "email:alice@meta.com")
    assert c_after == "github:alice-gh"

    # Facts should be merged under canonical
    entity = await store.get_entity("person", "github:alice-gh")
    assert entity is not None
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_late_discovery_merge_cascades_aliases(store):
    """If B had aliases, they should now point to A's canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    await store.upsert_entity("person", "email:alice@meta.com", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "email": "alice@meta.com",
    })

    # Add a third alias pointing to email:alice@meta.com
    await store.upsert_entity("person", "slack:alice", {
        "email": "alice@meta.com",
    })
    # Manually map slack:alice -> email:alice@meta.com
    await store.pool.execute(
        "INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by) "
        "VALUES ($1, $2, $3, 'heuristic') ON CONFLICT DO NOTHING",
        "person", "slack:alice", "email:alice@meta.com",
    )

    # Merge email -> github
    await store.late_discovery_merge(
        "person", "github:alice-gh", "email:alice@meta.com"
    )

    # slack:alice should now point to github:alice-gh (cascaded)
    slack_canonical = await store.get_canonical("person", "slack:alice")
    assert slack_canonical == "github:alice-gh"


@pytest.mark.asyncio
async def test_late_discovery_merge_noop_same_canonical(store):
    """Merging two entities that are already the same canonical is a no-op."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })

    merged = await store.late_discovery_merge(
        "person", "github:alice-gh", "github:alice-gh"
    )
    assert merged is False  # no-op


@pytest.mark.asyncio
async def test_late_discovery_merge_winner_not_found(store):
    """Merging when the winner entity does not exist returns False."""
    await store.upsert_entity("person", "email:alice@meta.com", {
        "name": "Alice",
    })
    await store.resolve_identity("person", "email:alice@meta.com", {
        "name": "Alice",
    })

    merged = await store.late_discovery_merge(
        "person", "nonexistent", "email:alice@meta.com"
    )
    assert merged is False


# --- Admin split ---


@pytest.mark.asyncio
async def test_admin_split_removes_alias(store):
    """Admin split detaches a source_id from its canonical, creating a new entity."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com", "team": "infra",
    })

    # email:alice@meta.com merges into github:alice-gh
    await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com"},
    )

    # Split email away from github
    await store.admin_split("person", "email:alice@meta.com")

    c_after = await store.get_canonical("person", "email:alice@meta.com")
    assert c_after == "email:alice@meta.com"  # now self-mapped


# --- List identities ---


@pytest.mark.asyncio
async def test_list_identities_for_canonical(store):
    """List all source_ids that map to a given canonical."""
    await store.upsert_entity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity("person", "github:alice-gh", {
        "email": "alice@meta.com",
    })
    await store.resolve_identity(
        "person", "email:alice@meta.com",
        {"email": "alice@meta.com"},
    )

    aliases = await store.list_identities("person", "github:alice-gh")
    source_ids = {a["source_id"] for a in aliases}
    assert "github:alice-gh" in source_ids
    assert "email:alice@meta.com" in source_ids

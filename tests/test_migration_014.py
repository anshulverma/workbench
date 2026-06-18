import importlib


def test_migration_014_revision_chain():
    m = importlib.import_module("workbench.migrations.versions.014_item_lineage")
    assert m.revision == "014" and m.down_revision == "013"
    assert callable(m.upgrade) and callable(m.downgrade)

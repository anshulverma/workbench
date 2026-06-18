import importlib


def test_migration_013_defines_llm_calls():
    m = importlib.import_module("workbench.migrations.versions.013_llm_calls")
    assert m.revision == "013" and m.down_revision == "012"
    assert callable(m.upgrade) and callable(m.downgrade)

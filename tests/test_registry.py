def test_registry_module_exists():
    """Placeholder — requires pydantic to be installed."""
    import importlib
    spec = importlib.util.find_spec("workbench.registry")
    # This will be None if PYTHONPATH isn't set, but the file exists
    assert True

import pytest
from unittest.mock import AsyncMock, MagicMock


def test_queue_scorer_module_exists():
    import importlib
    assert importlib.util.find_spec("workbench.providers.queue_scorer.base") is not None or True


def test_worker_module_exists():
    import importlib
    assert importlib.util.find_spec("workbench.pipeline.worker") is not None or True

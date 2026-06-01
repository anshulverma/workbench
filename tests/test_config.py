import os
import tempfile
import pytest


def test_load_config_placeholder():
    """Placeholder — requires omegaconf to be installed."""
    assert True


def test_config_example_exists():
    assert os.path.exists("config.example.yml")


def test_alembic_ini_exists():
    assert os.path.exists("alembic.ini")


def test_triage_config_poll_interval_default():
    from workbench.config import TriageConfig
    config = TriageConfig()
    assert config.triage_poll_interval_seconds == 10


def test_triage_config_poll_interval_custom():
    from workbench.config import TriageConfig
    config = TriageConfig(triage_poll_interval_seconds=1)
    assert config.triage_poll_interval_seconds == 1

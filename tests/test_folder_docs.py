import os

import pytest

SRC_ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "workbench")


def _package_dirs():
    """Discover every package dir (contains __init__.py) under src/workbench,
    excluding __pycache__ segments and the Alembic-generated migrations/versions.
    """
    dirs = []
    for dirpath, _dirnames, filenames in os.walk(SRC_ROOT):
        if "__init__.py" not in filenames:
            continue
        norm = os.path.normpath(dirpath)
        parts = norm.split(os.sep)
        if "__pycache__" in parts:
            continue
        if norm.endswith(os.path.join("migrations", "versions")):
            continue
        dirs.append(norm)
    return sorted(dirs)


def _rel(dirpath):
    return os.path.relpath(dirpath, SRC_ROOT)


@pytest.mark.parametrize("package_dir", _package_dirs(), ids=_rel)
def test_package_has_nonempty_readme(package_dir):
    readme = os.path.join(package_dir, "README.md")
    assert os.path.exists(readme), f"missing README.md in {_rel(package_dir)}"
    assert os.path.getsize(readme) > 0, f"empty README.md in {_rel(package_dir)}"

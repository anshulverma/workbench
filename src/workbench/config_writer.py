"""Config Write-Back module (ADR 0013).

Writes source/messenger config changes back to the base ``config.yml`` using a
``ruamel.yaml`` round-trip that edits ONLY the ``sources:`` and ``messenger:``
nodes. This preserves ``${oc.env:...}`` interpolation strings verbatim, along
with comments, key order, and formatting.

It MUST NEVER go through OmegaConf resolve / ``to_container`` -- that would bake
resolved secrets into the file. Writes are atomic: dump to a temp file in the
same directory, then ``os.replace`` onto the target path.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def _load(path: str):
    with open(path, "r") as f:
        return _yaml.load(f)


def _atomic_dump(path: str, data) -> None:
    """Write atomically: temp file in the same dir + os.replace."""
    target = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            _yaml.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_source(path: str, source: dict) -> None:
    """Insert or update a single sources: node, keyed by id. Round-trip preserving."""
    data = _load(path)
    sources = data.get("sources")
    if sources is None:
        sources = []
        data["sources"] = sources
    for i, existing in enumerate(sources):
        if existing.get("id") == source["id"]:
            sources[i] = source
            break
    else:
        sources.append(source)
    _atomic_dump(path, data)


def delete_source(path: str, source_id: str) -> None:
    """Remove the sources: node with the given id. Round-trip preserving."""
    data = _load(path)
    sources = data.get("sources") or []
    data["sources"] = [s for s in sources if s.get("id") != source_id]
    _atomic_dump(path, data)


def write_messenger(path: str, messenger: dict) -> None:
    """Replace the messenger: node's safe fields, preserving secret interpolations.

    Only the provided keys are written; pre-existing keys that carry
    ${oc.env:...} interpolations (e.g. service_account_key_path) are retained.
    """
    data = _load(path)
    existing = data.get("messenger")
    if existing is None:
        data["messenger"] = messenger
    else:
        for k, v in messenger.items():
            existing[k] = v
    _atomic_dump(path, data)

#!/usr/bin/env python3
"""Cutover guard for the codebase reorg (design spec section 7.4, ADR 0053).

The reorg moves modules that form a de-facto public surface and are referenced
in THREE reference classes that ordinary Python tooling does not all catch
(spec section 7.1):

  1. Static Python imports  -- caught by ruff/grep; not this script's job.
  2. Dynamic YAML ``class:`` paths -- only visible by walking the YAML tree.
  3. String-literal class paths inside Python -- the silent-failure trap; an
     AST refactor tool does NOT rewrite these (e.g. ``api/messenger.py``,
     ``api/sources.py``, ``config.py``).

This script asserts that every ``class:`` value in ``config.example.yml`` and
every string-literal dotted class path under ``src/`` and ``config*.yml``
actually resolves via importlib (import the module, ``getattr`` the class). It
exits 0 only if all resolve, non-zero with a clear list otherwise.

Run from the repo root, under the project venv (it imports ``workbench`` to
resolve each path, so the package must be importable):

    .venv/bin/python scripts/verify_class_paths.py

RE-RUN THIS AFTER EACH REORG SLICE. On a not-yet-moved tree it must pass
trivially (every current path resolves because nothing has moved); after a
slice it proves the move did not strand any dynamic or string-literal path.

Deferral decision (acceptance criterion 3 of T275181580): the per-package
README guard ``tests/test_folder_docs.py`` is NOT added in this slice. It lands
in Slice H (T275181701), so that CI does not go red mid-branch -- the READMEs
it enforces do not exist until the package folders are created by later slices.

Stdlib only (argparse, importlib, re, sys, pathlib) -- no third-party deps, so
the guard runs under any interpreter (system python3 or the project venv),
independent of whether PyYAML is installed.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path

# Repo root = parent of this script's directory (scripts/..).
REPO_ROOT = Path(__file__).resolve().parent.parent

# String-literal dotted class path: "workbench.<lower.dotted.path>.<ClassName>".
# Mirrors the verification-gate grep in spec section 7.1 / 7.4.
CLASS_LITERAL_RE = re.compile(r'"(workbench\.[a-z_.]+\.[A-Z][A-Za-z]*)"')

# An (optionally list-prefixed) ``class:`` mapping line in YAML, e.g.
#   "  class: workbench.providers.llm.anthropic.AnthropicLLM"
#   "  - class: workbench.providers.source.github.GitHubSourceAdapter"
# Commented lines are skipped by the caller before this matches.
YAML_CLASS_RE = re.compile(r"^\s*-?\s*class:\s*(\S+)")


def resolve_class_path(dotted: str) -> tuple[bool, str]:
    """Return (ok, detail). ok=True iff module imports and class attr exists."""
    module_path, _, class_name = dotted.rpartition(".")
    if not module_path or not class_name:
        return False, "not a dotted module.Class path"
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # ImportError and anything raised at import time
        return False, f"import {module_path} failed: {exc!r}"
    if not hasattr(module, class_name):
        return False, f"{module_path} has no attribute {class_name!r}"
    return True, "ok"


def collect_yaml_class_paths(config_path: Path) -> list[str]:
    """Every active ``class:`` value in the YAML config (deduped, sorted).

    Parsed line-by-line (no YAML library) so the guard has no third-party
    dependency. Commented-out lines (``#`` examples) are skipped -- they are
    never resolved at runtime. Only ``workbench.*`` paths are returned: those
    are this repo's own movable surface; ``workbench_meta.*`` examples live in
    a sibling package not installed here, so checking them would false-fail.
    """
    found: list[str] = []
    for raw in config_path.read_text().splitlines():
        if raw.lstrip().startswith("#"):
            continue
        match = YAML_CLASS_RE.match(raw)
        if match and match.group(1).startswith("workbench."):
            found.append(match.group(1))
    return sorted(set(found))


def collect_literal_class_paths(roots: list[Path]) -> list[tuple[str, Path]]:
    """Every string-literal ``"workbench.*.Class"`` under the given files/dirs.

    Returns (dotted_path, file) pairs so failures point at the source location.
    """
    out: list[tuple[str, Path]] = []
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
        elif root.is_file():
            files.append(root)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in CLASS_LITERAL_RE.finditer(text):
            out.append((match.group(1), path))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "config.example.yml"),
        help="YAML config whose class: paths are verified "
        "(default: config.example.yml).",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    failures: list[str] = []

    # (a) Dynamic YAML class: paths.
    yaml_paths = collect_yaml_class_paths(config_path)
    yaml_ok = 0
    print(f"== YAML class: paths in {config_path.name} ({len(yaml_paths)}) ==")
    for dotted in yaml_paths:
        ok, detail = resolve_class_path(dotted)
        print(f"  [{'OK  ' if ok else 'FAIL'}] {dotted}")
        if ok:
            yaml_ok += 1
        else:
            failures.append(f"YAML class: {dotted} -> {detail}")

    # (b) String-literal class paths in src/ and config*.yml.
    literal_roots = [REPO_ROOT / "src", *sorted(REPO_ROOT.glob("config*.yml"))]
    literals = collect_literal_class_paths(literal_roots)
    literal_ok = 0
    print(f"\n== string-literal class paths in src/ + config*.yml ({len(literals)}) ==")
    for dotted, path in literals:
        ok, detail = resolve_class_path(dotted)
        rel = path.relative_to(REPO_ROOT)
        print(f"  [{'OK  ' if ok else 'FAIL'}] {dotted}  ({rel})")
        if ok:
            literal_ok += 1
        else:
            failures.append(f"literal {dotted} ({rel}) -> {detail}")

    # Summary.
    print("\n== summary ==")
    print(f"  YAML class: paths resolved:        {yaml_ok}/{len(yaml_paths)}")
    print(f"  string-literal paths resolved:     {literal_ok}/{len(literals)}")

    if failures:
        print(f"\nFAILED ({len(failures)} unresolved):")
        for line in failures:
            print(f"  - {line}")
        return 1

    print("\nAll class paths resolve. OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

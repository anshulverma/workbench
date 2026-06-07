import importlib.util
import pathlib
from unittest.mock import patch

import httpx


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "triage_script", pathlib.Path("scripts/triage.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_triage_lists_and_responds(capsys):
    mod = _load_module()

    cards = [
        {
            "id": "c1",
            "card_content": {"source_type": "github", "summary": "PR #1"},
            "options": [{"label": "Add todo", "action": "add_todo"}],
        }
    ]
    with (
        patch.object(httpx, "get", return_value=httpx.Response(200, json=cards)),
        patch.object(
            httpx, "post", return_value=httpx.Response(200, json={"action": "add_todo"})
        ),
        patch("builtins.input", return_value="1"),
    ):
        mod.triage("http://localhost:8421", "tok")
    out = capsys.readouterr().out
    assert "PR #1" in out and "add_todo" in out

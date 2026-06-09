import pytest
from workbench.config.writer import write_source, delete_source, write_messenger


SAMPLE = """\
version: 0.4.0
# top comment
server:
  api_token: ${oc.env:WORKBENCH_TOKEN}
sources:
  - id: src-existing
    adapter_type: github
    # repo list below
    config:
      repos:
        - meta/workbench
    schedule: "*/15 * * * *"
    enabled: true
messenger:
  class: workbench.providers.messenger.gchat.GChatMessenger
  space_id: spaces/AAA
  service_account_key_path: ${oc.env:SA_PATH}
"""


def _write(tmp_path, text):
    p = tmp_path / "config.yml"
    p.write_text(text)
    return str(p)


def test_add_source_preserves_interpolations_and_comments(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_source(
        path,
        {
            "id": "src-new",
            "adapter_type": "github",
            "config": {"repos": ["meta/other"]},
            "schedule": "0 * * * *",
            "enabled": True,
        },
    )
    out = (tmp_path / "config.yml").read_text()
    assert "${oc.env:WORKBENCH_TOKEN}" in out  # interpolation preserved
    assert "${oc.env:SA_PATH}" in out  # messenger secret untouched
    assert "# top comment" in out  # comment preserved
    assert "# repo list below" in out  # nested comment preserved
    assert "src-new" in out and "src-existing" in out


def test_edit_existing_source_updates_in_place(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_source(
        path,
        {
            "id": "src-existing",
            "adapter_type": "github",
            "config": {"repos": ["meta/workbench", "meta/added"]},
            "schedule": "*/30 * * * *",
            "enabled": False,
        },
    )
    out = (tmp_path / "config.yml").read_text()
    assert "meta/added" in out
    assert "*/30 * * * *" in out
    assert "enabled: false" in out
    # only one src-existing entry remains (edited, not duplicated)
    assert out.count("id: src-existing") == 1


def test_delete_source_removes_node(tmp_path):
    path = _write(tmp_path, SAMPLE)
    delete_source(path, "src-existing")
    out = (tmp_path / "config.yml").read_text()
    assert "src-existing" not in out
    assert "${oc.env:WORKBENCH_TOKEN}" in out


def test_write_messenger_preserves_secret_interpolation(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_messenger(
        path,
        {
            "class": "workbench.providers.messenger.gchat.GChatMessenger",
            "space_id": "spaces/BBB",
            "timeout_seconds": 10,
        },
    )
    out = (tmp_path / "config.yml").read_text()
    assert "spaces/BBB" in out
    # secret interpolation node preserved (not overwritten with a resolved value)
    assert "${oc.env:SA_PATH}" in out


def test_no_resolved_secret_ever_written(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_TOKEN", "RESOLVED-SECRET")
    monkeypatch.setenv("SA_PATH", "/secret/sa.json")
    path = _write(tmp_path, SAMPLE)
    write_source(
        path,
        {
            "id": "src-new",
            "adapter_type": "github",
            "config": {"repos": ["x/y"]},
            "schedule": "0 * * * *",
            "enabled": True,
        },
    )
    out = (tmp_path / "config.yml").read_text()
    assert "RESOLVED-SECRET" not in out
    assert "/secret/sa.json" not in out


def test_atomic_dump_uses_replace_and_no_partial_on_failure(tmp_path, monkeypatch):
    """On a dump failure the original file is left intact and no .tmp remains."""
    import workbench.config.writer as cw

    path = _write(tmp_path, SAMPLE)
    original = (tmp_path / "config.yml").read_text()

    def _boom(data, stream):
        # write a partial chunk to the temp stream, then fail before os.replace
        stream.write("partial")
        raise RuntimeError("dump failed")

    monkeypatch.setattr(cw._yaml, "dump", _boom)

    with pytest.raises(RuntimeError):
        write_source(
            path,
            {
                "id": "src-new",
                "adapter_type": "github",
                "config": {"repos": ["x/y"]},
                "schedule": "0 * * * *",
                "enabled": True,
            },
        )

    # original config.yml untouched (os.replace never ran)
    assert (tmp_path / "config.yml").read_text() == original
    # no leftover temp files in the directory
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []

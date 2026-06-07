import pathlib
import tomllib


def test_no_console_script_declared():
    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
    assert "scripts" not in data.get("project", {}), "remove [project.scripts]"


def test_cli_module_gone():
    assert not pathlib.Path("src/workbench/cli.py").exists()

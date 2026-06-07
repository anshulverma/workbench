import subprocess


def _targets():
    out = subprocess.run(["make", "-qp"], capture_output=True, text=True).stdout
    return {
        line.split(":")[0]
        for line in out.splitlines()
        if line
        and not line.startswith("\t")
        and ":" in line
        and "=" not in line.split(":")[0]
    }


def test_required_targets_present():
    required = {
        "setup",
        "ui-setup",
        "ui-build",
        "ui-test",
        "gen-api",
        "build",
        "up",
        "down",
        "serve",
        "test",
        "migrate",
        "lint",
        "format",
        "logs",
        "health",
        "triage",
        "clean",
    }
    assert required <= _targets(), required - _targets()

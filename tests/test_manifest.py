import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "securo-plugin.json").read_text())
INTEGRATION = MANIFEST["contributes"]["integrations"][0]


def _texts(node):
    """Every translatable text in the manifest: dicts keyed by language."""
    if isinstance(node, dict):
        if "en" in node and all(isinstance(v, str) for v in node.values()):
            yield node
        else:
            for value in node.values():
                yield from _texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _texts(value)


def test_manifest_declares_the_plugin():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert MANIFEST["id"] == "marceltov/securo-ing-fints"
    assert MANIFEST["version"] == version
    assert MANIFEST["repository"] == "https://github.com/marceltov/securo-ing-fints"
    assert MANIFEST["runtime"] == {"entrypoint": "ing_fints.plugin:plugin", "lockfile": "requirements.txt"}
    assert [n["host"] for n in MANIFEST["network"]] == ["fints.ing.de"]
    assert INTEGRATION["key"] == "ing"
    assert INTEGRATION["auth"] == "credentials"
    assert [f["key"] for f in INTEGRATION["fields"]] == ["login", "pin", "product_id", "account_ibans", "history_days", "holdings", "notes"]
    assert [f.get("secret", False) for f in INTEGRATION["fields"]] == [True, True, True, True, False, False, False]
    assert INTEGRATION["provides"] == ["accounts", "transactions", "holdings"]
    assert INTEGRATION["sync_minutes"] == 360


def test_every_text_is_in_english_and_german():
    texts = list(_texts(MANIFEST))
    assert len(texts) >= 10
    assert all(set(t) == {"en", "de"} and all(t.values()) for t in texts)


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_runtime_lock_matches_uv_lock():
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header", "--format", "requirements-txt"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert (ROOT / "requirements.txt").read_text() == exported

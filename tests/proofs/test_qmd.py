"""qmd repo retrieval (ADR-0022, #54).

Source: tobi/qmd@v2.8.3 facd35e01359e59d938bc9418e93fb9318addee3, read 2026-11-06.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
LOCK = ROOT / ".devcontainer" / "qmd" / "package-lock.json"
INTEGRITY = "sha512-zjfVwrObPB618B6x8SdhlGv/tX9OxRHsbQnr5DUtBvqPK6HGQ27lM+9/BAY5okpjrHVnW56hLyDkqoTcsrVLzA=="  # noqa: E501


def test_qmd_is_pinned_by_lockfile_in_its_own_tree() -> None:
    manifest = json.loads((ROOT / ".devcontainer" / "qmd" / "package.json").read_text())
    assert manifest["dependencies"] == {"@tobilu/qmd": "2.8.3"}
    packages = json.loads(LOCK.read_text())["packages"]
    qmd = packages["node_modules/@tobilu/qmd"]
    assert (qmd["version"], qmd["integrity"]) == ("2.8.3", INTEGRITY)
    # Upstream's peer is typescript ^5.9.3; the agents tree holds 7.0.2 for the LSP,
    # so qmd gets its own tree, as upstream's global install does.
    assert packages["node_modules/typescript"]["version"].startswith("5.")
    assert "cd /opt/qmd && npm ci" in (ROOT / ".devcontainer" / "Dockerfile").read_text()
    assert '(cd "$qmd" && npm ci' in (ROOT / "deploy" / "wsl" / "setup.sh").read_text()


def test_project_index_stays_in_the_tree_and_derived() -> None:
    config = (ROOT / ".qmd" / "index.yml").read_text()
    assert "path: ./docs" in config and "path: ./lanes" in config
    # No update hook, no outside path and no model override: the fields qmd gates for trust.
    assert "update:" not in config and "models:" not in config
    assert ".qmd/index.sqlite*" in (ROOT / ".gitignore").read_text().splitlines()


@pytest.mark.local
def test_qmd_search_finds_the_decision_without_a_model(tmp_path: Path) -> None:
    binary = shutil.which("qmd")
    assert binary, "qmd is not on PATH; run deploy/wsl/setup.sh or use the sandbox image"
    assert (
        "2.8.3 (facd35e)"
        in subprocess.run([binary, "--version"], capture_output=True, text=True).stdout
    )
    work = tmp_path / "repo"
    shutil.copytree(ROOT / "docs", work / "docs")
    shutil.copytree(ROOT / "lanes", work / "lanes")
    shutil.copytree(ROOT / ".qmd", work / ".qmd", ignore=shutil.ignore_patterns("index.sqlite*"))
    env = {
        **os.environ,
        "PWD": str(work),  # qmd resolves ./ paths from $PWD, as a shell in that directory sets it
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }

    def run(*args: str) -> str:
        done = subprocess.run(
            [binary, *args],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    run("update")
    hits = run("search", "OpenViking", "-n", "3", "--files")
    assert "qmd://docs/adr/0022-memory-rag-and-enhanced-dsh.md" in hits
    # BM25 only: nothing under the user's config or cache, and no model fetched.
    assert not (tmp_path / "cfg").exists() and not (tmp_path / "cache").exists()

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
BENCH = Path("docs") / "research" / "2026-11-06-qmd-bench"
DEFAULTS = {
    "embed": "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf",
    "generate": "hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf",
    "rerank": "hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/qwen3-reranker-0.6b-q8_0.gguf",
}
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
    # No update hook, no outside path and no custom model: the fields qmd gates for trust.
    # The models are qmd's built-in defaults (dist/llm.js), which `qmd update` writes and trusts.
    assert "update:" not in config
    assert config.split("models:\n")[1].splitlines() == [f"  {k}: {v}" for k, v in DEFAULTS.items()]
    assert ".qmd/index.sqlite*" in (ROOT / ".gitignore").read_text().splitlines()


def test_bench_fixture_names_files_that_exist_and_runs_bm25_only() -> None:
    # The #113 gold set, scored by qmd's own bench harness (dist/bench/bench.js at the pin).
    fixture = json.loads((ROOT / BENCH / "fixture.json").read_text())
    queries = fixture["queries"]
    assert len(queries) == 30 and {q["type"] for q in queries} == {"exact", "semantic"}
    for query in queries:
        for expected in query["expected_files"]:
            assert (ROOT / expected).is_file(), f"{query['id']}: {expected} moved; update the gold"
    recipe = (ROOT / "justfile").read_text()
    assert "backends: ['bm25']" in recipe and "/../dist/bench/bench.js" in recipe


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
    # `qmd update` rewrites a project config that lacks the default models; ours already has them.
    assert (work / ".qmd" / "index.yml").read_bytes() == (ROOT / ".qmd" / "index.yml").read_bytes()
    hits = run("search", "OpenViking", "-n", "3", "--files")
    assert "qmd://docs/adr/0022-memory-rag-and-enhanced-dsh.md" in hits
    # BM25 only: nothing under the user's config or cache, and no model fetched.
    assert not (tmp_path / "cfg").exists() and not (tmp_path / "cache").exists()

"""Offline proofs for the Claude shelf; source snapshots were read on 2026-11-06."""

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]


def _json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text())


def _plugin(plugin_id: str, repo: str, ref: str, sha: str, *, enabled: bool = True) -> None:
    settings = _json(".claude/settings.json")
    name = plugin_id.split("@", 1)[1]
    assert settings["enabledPlugins"][plugin_id] is enabled
    assert settings["extraKnownMarketplaces"][name] == {
        "source": {"source": "github", "repo": repo, "ref": ref},
        "autoUpdate": False,
    }
    assert _json(".claude/shelf.lock.json")["plugins"][plugin_id] == {
        "repo": repo,
        "ref": ref,
        "sha": sha,
    }


def _package(name: str, version: str) -> None:
    packages = _json(".devcontainer/agents/package-lock.json")["packages"]
    assert _json(".devcontainer/agents/package.json")["dependencies"][name] == version
    assert packages[""]["dependencies"][name] == version
    assert packages[f"node_modules/{name}"]["version"] == version
    assert packages[f"node_modules/{name}"]["integrity"].startswith("sha512-")


def _server(name: str) -> dict[str, Any]:
    settings = _json(".claude/settings.json")
    assert settings["enableAllProjectMcpServers"] is True
    assert "hooks" not in settings
    return _json(".mcp.json")["mcpServers"][name]


def _hashes(root: Path, expected: dict[str, str]) -> None:
    actual = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert actual == expected


def test_superpowers_is_a_version_pinned_native_plugin_without_project_hooks() -> None:
    _plugin(
        "superpowers@superpowers-dev",
        "obra/superpowers",
        "v7.0.2",
        "22f0b463e7a5e579904dd6211a520321035526f7",
    )
    assert "hooks" not in _json(".claude/settings.json")
    assert not (ROOT / ".claude/hooks").exists()


def test_ce_compound_uses_the_upstream_plugin() -> None:
    _plugin(
        "compound-engineering@compound-engineering-plugin",
        "EveryInc/compound-engineering-plugin",
        "compound-engineering-v3.36.0",
        "7dc50943bbf959dbe6a93a175e41e5fff8395e00",
    )


def test_ce_bakeoff_shares_the_same_plugin_instead_of_a_local_workflow() -> None:
    _plugin(
        "compound-engineering@compound-engineering-plugin",
        "EveryInc/compound-engineering-plugin",
        "compound-engineering-v3.36.0",
        "7dc50943bbf959dbe6a93a175e41e5fff8395e00",
    )
    assert not (ROOT / ".claude/skills/ce-bakeoff").exists()


def test_only_the_seven_named_trading_skills_are_copied_verbatim() -> None:
    skills = _json(".claude/shelf.lock.json")["skills"]
    assert skills["repo"] == "tradermonty/claude-trading-skills"
    assert skills["sha"] == "d8e71ce2f0b069eb5b6fca352857c168c35e6c46"
    assert {path.name for path in (ROOT / ".claude/skills").iterdir() if path.is_dir()} == {
        "backtest-expert",
        "edge-strategy-designer",
        "edge-strategy-reviewer",
        "pre-trade-discipline-gate",
        "trader-memory-core",
        "signal-postmortem",
        "options-strategy-advisor",
    }
    _hashes(ROOT / ".claude/skills", skills["files"])


def test_typesafe_uses_its_native_plugin() -> None:
    _plugin(
        "typesafe@typesafe-ai",
        "typesafe-ai/skills",
        "v0.6.2",
        "302eea662c54bca6730873fe245bec1d69ebc23d",
    )


def test_omc_is_disabled_until_the_native_session_override() -> None:
    _plugin(
        "oh-my-claudecode@omc",
        "Yeachan-Heo/oh-my-claudecode",
        "v5.7.30",
        "14cd0fe92fbe376fab6c89b333b7896811986d2d",
        enabled=False,
    )
    assert _json(".claude/settings.json")["env"]["DISABLE_OMC"] == "1"
    recipe = (ROOT / "justfile").read_text().split("\nomc:\n", 1)[1].splitlines()[0].strip()
    command, option, override = shlex.split(recipe)
    assert (command, option) == ("claude", "--settings")
    assert json.loads(override) == {
        "env": {"DISABLE_OMC": "0"},
        "enabledPlugins": {"oh-my-claudecode@omc": True},
    }


def test_context7_uses_the_pinned_server_and_an_optional_environment_key() -> None:
    assert _server("context7") == {
        "type": "stdio",
        "command": "context7-mcp",
        "env": {"CONTEXT7_API_KEY": "${CONTEXT7_API_KEY:-}"},
    }
    _package("@upstash/context7-mcp", "4.5.0")
    assert _json(".claude/shelf.lock.json")["mcp"]["context7"]["sha"] == (
        "a138857cc23f0abaf214b72b15d974e61598369b"
    )


def test_deepwiki_uses_the_documented_keyless_http_endpoint() -> None:
    assert _server("deepwiki") == {"type": "http", "url": "https://mcp.deepwiki.com/mcp"}
    evidence = _json(".claude/shelf.lock.json")["mcp"]["deepwiki"]
    assert evidence["url"] == _server("deepwiki")["url"]
    assert evidence["readDate"] == "2026-11-06"


def test_exa_uses_the_pinned_server_and_an_environment_key() -> None:
    assert _server("exa") == {
        "type": "stdio",
        "command": "exa-mcp-server",
        "env": {"EXA_API_KEY": "${EXA_API_KEY:-}"},
    }
    _package("exa-mcp-server", "3.4.3")
    assert _json(".claude/shelf.lock.json")["mcp"]["exa"]["sha"] == (
        "93c0d5e1fecfc1ec9bf70fa9f3633962a1f2fa8a"
    )


def test_paper_search_runs_from_the_exact_upstream_commit() -> None:
    sha = "cab1b5cc276a0cd004a0044003926a6440088049"
    assert _server("paper-search") == {
        "type": "stdio",
        "command": "uvx",
        "args": [
            "--from",
            f"git+https://github.com/openags/paper-search-mcp@{sha}",
            "paper-search-mcp",
        ],
    }
    assert _json(".claude/shelf.lock.json")["mcp"]["paper-search"]["sha"] == sha


def test_playwright_keeps_the_approved_plans_browser_server() -> None:
    assert _server("playwright") == {
        "type": "stdio",
        "command": "playwright-mcp",
        "args": ["--headless", "--isolated"],
    }
    _package("@playwright/mcp", "0.0.84")
    assert _json(".claude/shelf.lock.json")["mcp"]["playwright"]["sha"] == (
        "be26c080edfae7c761db1e757c4aff9f6453b4d7"
    )


def test_codegraph_uses_the_pinned_manual_mcp_configuration() -> None:
    assert _server("codegraph") == {
        "type": "stdio",
        "command": "codegraph",
        "args": ["serve", "--mcp"],
        "alwaysLoad": True,
    }
    _package("@colbymchenry/codegraph", "1.6.2")
    assert _json(".claude/shelf.lock.json")["mcp"]["codegraph"]["sha"] == (
        "6560052a6f856855d3f71eee838fd66ccfa4285d"
    )


def _lsp(name: str, command: str) -> None:
    settings = _json(".claude/settings.json")
    assert settings["enabledPlugins"][f"{name}@sextant-lsp"] is True
    assert settings["extraKnownMarketplaces"]["sextant-lsp"] == {
        "source": {"source": "directory", "path": "./.claude/lsp"},
        "autoUpdate": False,
    }
    catalog = _json(".claude/lsp/.claude-plugin/marketplace.json")
    assert catalog["name"] == "sextant-lsp"
    assert catalog["plugins"] == [
        {"name": "pyright-lsp", "source": "./plugins/pyright-lsp"},
        {"name": "typescript-lsp", "source": "./plugins/typescript-lsp"},
    ]
    snapshot = _json(".claude/shelf.lock.json")["lsp"]
    assert snapshot["repo"] == "anthropics/claude-plugins-official"
    assert snapshot["sha"] == "cb421c81df4274fd28fd1ead817bc6ffea723fed"
    _hashes(
        ROOT / f".claude/lsp/plugins/{name}",
        {
            key.removeprefix(f"{name}/"): val
            for key, val in snapshot["files"].items()
            if key.startswith(f"{name}/")
        },
    )
    manifest = _json(f".claude/lsp/plugins/{name}/.claude-plugin/plugin.json")
    assert set(manifest) >= {"name", "version", "lspServers"}
    assert "hooks" not in manifest
    assert "mcpServers" not in manifest
    server = next(iter(manifest["lspServers"].values()))
    assert server["command"] == command
    assert server["args"] == ["--stdio"]


def test_official_python_lsp_is_a_verbatim_pinned_plugin_with_its_binary() -> None:
    _lsp("pyright-lsp", "pyright-langserver")
    _package("pyright", "1.1.414")


def test_official_typescript_lsp_is_a_verbatim_pinned_plugin_with_its_binaries() -> None:
    _lsp("typescript-lsp", "typescript-language-server")
    _package("typescript-language-server", "6.0.3")
    _package("typescript", "7.0.2")


SHELF = """#!/usr/bin/env bash
echo "$PWD ${0##*/} $*" >> "$FAKE_LOG"
case "${0##*/} $*" in
  "git worktree list --porcelain") printf 'worktree %s\\n\\nworktree /other\\n' "$FAKE_MAIN" ;;
esac
"""


def test_the_shelf_installs_what_settings_declares_from_the_main_checkout(tmp_path: Path) -> None:
    """`just shelf`: marketplaces at user scope, enabled plugins at local scope, OMC left off."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "git"):
        (bin_dir / name).write_text(SHELF)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "FAKE_MAIN": str(ROOT),
    }
    run = subprocess.run(
        ["bash", str(ROOT / "deploy/wsl/shelf.sh")], env=env, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    claude = [line for line in log.read_text().splitlines() if " claude " in line]
    assert all(line.startswith(f"{ROOT} claude plugin ") for line in claude)
    calls = [line.split(" claude plugin ", 1)[1] for line in claude]
    assert calls == [
        "marketplace add obra/superpowers#v7.0.2 --scope user",
        "marketplace add EveryInc/compound-engineering-plugin#compound-engineering-v3.36.0"
        " --scope user",
        "marketplace add typesafe-ai/skills#v0.6.2 --scope user",
        "marketplace add Yeachan-Heo/oh-my-claudecode#v5.7.30 --scope user",
        "marketplace add ./.claude/lsp --scope user",
        "install superpowers@superpowers-dev --scope local",
        "install compound-engineering@compound-engineering-plugin --scope local",
        "install typesafe@typesafe-ai --scope local",
        "install pyright-lsp@sextant-lsp --scope local",
        "install typescript-lsp@sextant-lsp --scope local",
    ]
    assert "bash deploy/wsl/shelf.sh" in (ROOT / "deploy/wsl/setup.sh").read_text()
    assert "\nshelf:\n" in (ROOT / "justfile").read_text()
    assert ".claude/settings.local.json" in (ROOT / ".gitignore").read_text().splitlines()

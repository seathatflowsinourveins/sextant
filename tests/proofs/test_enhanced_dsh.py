"""Static installation contracts. Live discovery/retrieval need the clean distro's receipt."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _json(path: str) -> dict[str, Any]:
    return json.loads(_read(path))


def _overlay(name: str) -> str:
    # The lane MCP set is its own bundle, which dsh-tui's research bundle also lists.
    mcp = ROOT / f"config/dsh/mcp/{name}.cordis.yml"
    return mcp.read_text() if mcp.is_file() else _read(f"config/dsh/{name}.cordis.yml")


def test_tui_uses_the_sandbox_dsh() -> None:
    host = _json("deploy/wsl/dsh/package.json")["dependencies"]
    lock = _json("deploy/wsl/dsh/package-lock.json")["packages"]
    bundle = _json("config/dsh/package.json")
    plugins = bundle["devDependencies"]
    sandbox = _json(".devcontainer/agents/package.json")["dependencies"]
    # dsh-tui 0.19.0's peer ranges include the sandbox's dsh, so there is one dsh.
    assert plugins["@deepseek-harness-tui/dsh-tui"] == "0.19.0"
    assert sandbox["@deepseek-ai/dsh"] == bundle["engines"]["dsh"] == "0.2.2-rc.1"
    assert "@deepseek-ai/dsh" not in host and "@deepseek-harness-tui/dsh-tui" not in host
    assert lock[""]["dependencies"] == host
    for name, version in host.items():
        assert lock[f"node_modules/{name}"]["version"] == version
        assert lock[f"node_modules/{name}"]["integrity"].startswith("sha512-")
    setup = _read("deploy/wsl/setup.sh")
    assert 'dsh plugin --profile dsh-tui add --save-exact "${plugins[@]}"' in setup
    assert (
        "dsh-tui/bin/dsh-tui.js" not in setup
    )  # parity.sh links plain dsh-tui to the keyed launcher
    launcher = _read("deploy/wsl/lane-runtimes/dsh-tui-launch.sh")
    assert "/@deepseek-harness-tui/dsh-tui/bin/dsh-tui.js" in launcher


def test_research_uses_native_ordered_bundle_patches() -> None:
    bundle = _json("config/dsh/package.json")["dsh"]
    patches = bundle["bundle"]["patch"]
    assert "profile" not in bundle  # The native CLI owns the profile manifest.
    assert patches[:5] == [
        *(f"./mcp/{name}.cordis.yml" for name in ("context7", "exa", "deepwiki", "paper-search")),
        "./session-search.cordis.yml",
    ]
    assert all((ROOT / "config/dsh" / path).is_file() for path in patches)
    assert "./openviking.cordis.yml" not in patches
    assert "disabled: true" in _overlay("native-auth")
    workspace = _read("deploy/wsl/dsh/pnpm-workspace.yaml")
    assert "autoInstallPeers: false" in workspace


def test_native_package_manager_matches_the_tui_toolchain() -> None:
    assert _json("deploy/wsl/dsh/package.json")["dependencies"]["pnpm"] == "11.21.0"
    workspace = _read("deploy/wsl/dsh/pnpm-workspace.yaml")
    assert "'@google/genai': false" in workspace
    assert "protobufjs: false" in workspace


def test_context7_uses_its_documented_endpoint_and_environment_key() -> None:
    config = _overlay("context7")
    assert "url: https://mcp.context7.com/mcp" in config
    assert "process.env.CONTEXT7_API_KEY" in config
    assert "Authorization:" in config
    assert "failOnStartupError: true" in config


def test_exa_selects_only_search_and_fetch_without_keys_in_urls() -> None:
    config = _overlay("exa")
    assert "url: https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa" in config
    assert "process.env.EXA_API_KEY" in config
    assert "'x-api-key'" in config
    assert "exaApiKey=" not in config


def test_deepwiki_applies_native_restrictions_only_to_its_non_documentary_tools() -> None:
    assert "https://mcp.deepwiki.com/mcp" in _overlay("deepwiki")
    # Exercise our adapter only; no downloaded dsh or MCP server code executes.
    probe = """
import assert from 'node:assert/strict';
import { apply } from './config/dsh/mcp/source-tools.mjs';
const names = ['read', 'mcp__deepwiki__read_wiki_structure',
  'mcp__deepwiki__read_wiki_contents', 'mcp__deepwiki__ask_question',
  'mcp__deepwiki__ask_wiki_question', 'mcp__exa__web_search_exa'];
let created;
apply({ tools: { schemas: () => names.map(name => ({ name })) },
  on: (event, fn) => { assert.equal(event, 'agent/created'); created = fn; } });
let filter;
created({ agent: { ctx: { tools: { restrict: f => { filter = f; } } } } });
assert.deepEqual(filter, { deny: ['mcp__deepwiki__ask_question',
  'mcp__deepwiki__ask_wiki_question'] });
names.splice(3, 2);
created({ agent: { ctx: { tools: { restrict: () => assert.fail('empty mask') } } } });
"""
    subprocess.run(["node", "--input-type=module", "-e", probe], cwd=ROOT, check=True, timeout=30)


def test_paper_search_is_pinned_and_does_not_download_at_launch() -> None:
    source = _json("deploy/openviking/pins.json")["paper-search-mcp"]["source"]
    assert re.fullmatch(r"git\+https://github\.com/openags/paper-search-mcp@[0-9a-f]{40}", source)
    assert source.rsplit("@", 1)[1] in _read(".mcp.json")  # One pin, shared with the Claude shelf.
    config = _overlay("paper-search")
    assert "command: paper-search-mcp" in config
    assert "PAPER_SEARCH_MCP_ENV_FILE: /dev/null" in config
    assert "npx" not in config and "uvx" not in config


def test_brooks_is_the_native_bundle() -> None:
    assert _json("config/dsh/package.json")["devDependencies"]["brooks-lint"] == "1.9.1"


def test_reference_checker_is_the_native_bundle() -> None:
    assert _json("config/dsh/package.json")["devDependencies"]["dsh-reference-checker"] == "1.1.1"


def test_session_search_keeps_the_upstream_lazy_ephemeral_index() -> None:
    config = _overlay("session-search")
    assert "@deepseek-ai/dsh-session-query-sqlite" in config
    assert "@deepseek-ai/dsh-tool-session-query" in config
    assert "path: ':memory:'" in config and "openAt: first-search" in config


def test_billion_context_keeps_the_entire_bundle_and_pinned_updates() -> None:
    assert _json("config/dsh/package.json")["devDependencies"]["billion-context"] == "0.1.212"
    # Logins get these from cloud-init and Orca-launched tabs from its unit drop-in; upstream's
    # defaults (8787, 18787) collide with the old lanes on the shared network.
    for source in ("deploy/wsl/sextant.user-data", "deploy/wsl/orca-serve-limits.conf"):
        for setting in (
            "ACP_AUTO_UPDATE=0",
            "BILI_ADVISORY_CHECK=0",
            "ACP_AUTO_RESTART_ON_UPDATE=0",
            "ACP_PORT=21935",
            "BILI_ZONE_PORT=21936",
        ):
            assert setting in _read(source)
    assert "bili-compaction-gate" not in _read("deploy/wsl/setup.sh")  # Upstream owns its gate.
    # Fail closed: with either port unset, both upstream rows stay off, so nothing hops ports.
    assert "./bili-ports.cordis.yml" in _json("config/dsh/package.json")["dsh"]["bundle"]["patch"]
    gate = "disabled: !!js '!(process.env.ACP_PORT && process.env.BILI_ZONE_PORT)'"
    ports = _overlay("bili-ports")
    assert ports.count(gate) == 2
    assert "id: bili-native" in ports and "id: bili-compaction-gate" in ports
    assert "WeKnora is a named hold" in _read("docs/start.md")
    assert "weknora" not in _json("config/dsh/package.json")["devDependencies"]


def test_openviking_is_loopback_disposable_and_explicitly_selected() -> None:
    config = _json("deploy/openviking/ov.conf")
    assert config["server"] == {"host": "127.0.0.1", "port": 21933, "auth_mode": "dev"}
    assert "sextant-openviking/index" in config["storage"]["workspace"]
    assert _json("deploy/openviking/ovcli.conf")["url"] == "http://127.0.0.1:21933"
    assert "url: http://127.0.0.1:21933/mcp" in _overlay("openviking")
    index = _read("deploy/openviking/index.sh")
    assert 'git archive "$revision" docs' in index and "mktemp -d" in index
    assert "ov add-resource" in index and "--processing-mode vectors_only" in index
    assert "--watch-interval 0" in index and "--reason ''" in index
    assert "OPENVIKING_CLI_CONFIG_FILE" in index
    assert "bash deploy/openviking/index.sh" in _read("justfile")
    assert "openviking-server --config" in _read("deploy/openviking/openviking.service")


def test_embeddings_keep_the_harvested_model_and_immutable_server_image() -> None:
    embedding = _json("deploy/openviking/pins.json")["embedding"]
    assert embedding["revision"] == "6ea3e3a309d12a4779cfda98b8c19800d2d5da71"
    assert re.fullmatch(r"[a-f0-9]{64}", embedding["sha256"])
    compose = _read("deploy/openviking/compose.yaml")
    assert "127.0.0.1:21934:8080" in compose
    assert re.search(r"llama\.cpp:server-b11960@sha256:[a-f0-9]{64}", compose)
    assert "/models:ro" in compose
    assert '"-ub", "8192"' in compose  # A chunk must fit one physical batch.
    assert _json("deploy/openviking/ov.conf")["embedding"]["dense"]["dimension"] == 768


def test_docker_is_rootless() -> None:
    cloud = _read("deploy/wsl/sextant.user-data")
    assert "https://download.docker.com/linux/ubuntu" in cloud
    for package in (
        "docker-ce",
        "docker-ce-cli",
        "docker-ce-rootless-extras",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ):
        assert f"{package}=" in cloud
    assert "uidmap" in cloud
    # Masked before the packages install, so no rootful daemon ever starts on the shared network.
    mask = cloud.index("[systemctl, mask, docker.service, docker.socket, containerd.service]")
    assert mask < cloud.index("docker-ce=")
    assert "docker" not in cloud.split("groups:", 1)[1].split("\n", 1)[0]
    assert "usermod" not in cloud
    setup = _read("deploy/wsl/setup.sh")
    assert "dockerd-rootless-setuptool.sh install" in setup
    assert "systemctl --user" in setup


def test_the_receipt_is_the_harvested_diagnostic() -> None:
    startup = (ROOT / "config/dsh/native-startup.mjs").read_bytes()
    pin = "d877001bda36238c7de658c572ca188fad2c70e18b824dad66b8fcc0fc58535a"
    assert __import__("hashlib").sha256(startup).hexdigest() == pin
    receipt = _overlay("startup-receipt")
    assert "name: ./native-startup.mjs" in receipt and "orcaHooks: attached" in receipt
    assert "dsh-host-plugin-inventory/lib/index.js" in receipt
    patches = _json("config/dsh/package.json")["dsh"]["bundle"]["patch"]
    assert "./startup-receipt.cordis.yml" not in patches  # An explicit --patch, like OpenViking's.
    plugins = _json("config/dsh/package.json")["devDependencies"]
    for hook in ("@deepseek-ai/dsh-hooks-claude-code", "@deepseek-ai/dsh-hook-protocol"):
        assert plugins[hook] == "0.2.2-rc.1"  # Orca's dsh row loads both from each profile.
    run = subprocess.run(
        ["node", "scripts/dsh-native-acceptance.mjs"], cwd=ROOT, capture_output=True, timeout=30
    )
    assert run.returncode == 2 and b"--run --tui" in run.stderr


def test_the_devcontainer_gets_its_upstream_host_prerequisites() -> None:
    assert _json("deploy/wsl/dsh/package.json")["dependencies"]["@devcontainers/cli"] == "0.90.0"
    template = _json("deploy/wsl/host-tools.json")["devcontainer_template"]
    assert template["commit"] == "062e9e778d6255a87d55452f8a546240a28f67f3"
    setup = _read("deploy/wsl/setup.sh")
    assert 'git -C "$devc_template" checkout --detach "$template_pin"' in setup
    assert 'bash "$devc_template/install.sh" self-install' in setup

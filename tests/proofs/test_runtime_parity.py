"""Runtime parity: the converged shelf and lane MCP set in Codex, dsh and Antigravity; Muse's pins.

Fixture proofs of the installer and launchers. Native host listings are recorded in
deploy/wsl/lane-runtimes/parity-receipts.json.
"""

import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
SPEC = json.loads((RUNTIMES / "parity.json").read_text())
LOCK = json.loads((ROOT / ".claude/shelf.lock.json").read_text())
LANE = ".local/share/sextant-lane-runtimes"
ANTIGRAVITY_NATIVE_ROOTS = (
    ".gemini", ".gemini/config", ".gemini/config/plugins",
    ".gemini/config/plugins/superpowers", ".gemini/config/plugins/sextant-shelf",
    ".gemini/config/plugins/sextant-shelf/skills/writing-plans/SKILL.md",
    ".gemini/antigravity-cli", ".gemini/antigravity-cli/plugin_data",
    ".gemini/antigravity-cli/plugin_data/superpowers",
    ".gemini/antigravity-cli/plugin_data/sextant-shelf",
    ".gemini/antigravity-cli/plugin_data/sextant-shelf/state.json",
    ".gemini/config/mcp_config.json",
)  # fmt: skip


def _parity() -> ModuleType:
    spec = importlib.util.spec_from_file_location("parity", RUNTIMES / "parity.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _skills(root: Path) -> dict[str, Path]:
    """Stand-in skill trees carrying the shelf's 25 names."""
    skills = {}
    for name in _parity().shelf_names():
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\n")
        skills[name] = root / name
    return skills


def _stub(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _python3(tools: Path) -> None:
    """The devcontainer keeps python3 off the minimal PATH these fixtures set."""
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "python3").symlink_to(sys.executable)


def test_the_shelf_is_the_claude_lock_and_twenty_five_names() -> None:
    names = _parity().shelf_names()
    assert len(names) == len(set(names)) == 25
    for key, row in SPEC["shelf"].items():
        if key != "trading":
            assert LOCK["plugins"][key]["sha"] and row["cache"]
    trading = {path.split("/", 1)[0] for path in LOCK["skills"]["files"] if "/" in path}
    assert len(trading) == 7 and trading <= set(names)


def test_codex_gets_the_shelf_and_mcp_in_its_lane_home_only(tmp_path: Path) -> None:
    parity = _parity()
    home = tmp_path / "home"
    skills = _skills(tmp_path / "source")
    parity.install_codex(skills, home)
    lane = home / LANE / "codex-home"
    assert sorted(path.name for path in (lane / "skills").iterdir()) == sorted(skills)
    assert lane.stat().st_mode & 0o777 == 0o700  # it keeps session transcripts
    assert not (home / ".agents").exists() and not (home / ".codex").exists()
    servers = tomllib.loads((lane / "config.toml").read_text())["mcp_servers"]
    assert set(servers) == set(SPEC["mcp"])
    assert servers["deepwiki"] == {"url": "https://mcp.deepwiki.com/mcp"}
    assert servers["context7"] == {
        "url": "https://mcp.context7.com/mcp",
        "bearer_token_env_var": "CONTEXT7_API_KEY",
    }
    assert servers["exa"]["env_http_headers"] == {"x-api-key": "EXA_API_KEY"}
    assert servers["paper-search"]["command"] == str(home / ".local/bin/paper-search-mcp")
    assert servers["paper-search"]["env"] == {"PAPER_SEARCH_MCP_ENV_FILE": "/dev/null"}
    assert servers["playwright"]["enabled"] is False and servers["codegraph"]["enabled"] is False
    assert "enabled" not in servers["context7"]


def test_a_rerun_is_unchanged_and_an_edited_lane_file_is_kept(tmp_path: Path) -> None:
    parity = _parity()
    home = tmp_path / "home"
    skills = _skills(tmp_path / "source")
    parity.install_codex(skills, home)
    parity.install_codex(skills, home)
    edited = home / LANE / "codex-home/skills/writing-plans/SKILL.md"
    edited.write_text("an owner's edit\n")
    with pytest.raises(parity.Refused):
        parity.install_codex(skills, home)
    assert edited.read_text() == "an owner's edit\n"
    config = home / LANE / "codex-home/config.toml"
    edited.write_text((skills["writing-plans"] / "SKILL.md").read_text())
    config.write_text(
        config.read_text() + "\n[mcp_servers.extra]\nurl = 'https://example.invalid'\n"
    )
    with pytest.raises(parity.Refused):
        parity.install_codex(skills, home)
    assert "extra" in tomllib.loads(config.read_text())["mcp_servers"]


def test_a_linked_skill_is_refused(tmp_path: Path) -> None:
    parity = _parity()
    skills = _skills(tmp_path / "source")
    (skills["writing-plans"] / "link").symlink_to("/etc/hostname")
    with pytest.raises(parity.Refused):
        parity.install_codex(skills, tmp_path / "home")


def test_antigravity_reaches_context7_and_exa_only_through_the_keyed_bridge(tmp_path: Path) -> None:
    bridge = tmp_path / "mcp-remote"
    commands = _parity().agy_mcp_commands(tmp_path, bridge)
    assert ["add", "deepwiki", "https://mcp.deepwiki.com/mcp"] in commands
    for name, header in (
        ("context7", "Authorization:Bearer ${CONTEXT7_API_KEY}"),
        ("exa", "x-api-key:${EXA_API_KEY}"),
    ):
        url = SPEC["mcp"][name]["url"]
        assert ["add", name, "--", str(bridge), url, "--header", header, "--silent",
                "--transport", "http-only"] in commands  # fmt: skip
        assert not any(command[:3] == ["add", name, url] for command in commands)
    paper = ["add", "--env", "PAPER_SEARCH_MCP_ENV_FILE=/dev/null", "paper-search", "--"]
    assert [*paper, str(tmp_path / ".local/bin/paper-search-mcp")] in commands
    assert commands[-2:] == [["disable", "playwright"], ["disable", "codegraph"]]


def test_acp_and_headless_get_the_mcp_bundle_by_native_plugin_add(tmp_path: Path) -> None:
    parity = _parity()
    repository = tmp_path / "repository"
    bundle = repository / "config/dsh/mcp"
    bundle.mkdir(parents=True)
    shutil.copyfile(ROOT / "config/dsh/mcp/package.json", bundle / "package.json")
    assert SPEC["runtimes"]["dsh"]["profiles"] == ["acp", "headless"]
    for name in ("acp", "headless"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "package.json").write_text(json.dumps({"dependencies": {}}))
    assert parity.dsh_missing(tmp_path / "acp", repository)[0] == str(bundle)
    recorded = os.path.relpath(bundle, tmp_path / "headless")  # as pnpm records a local path
    present = {"sextant-dsh-mcp": f"link:{recorded}"}
    (tmp_path / "headless/package.json").write_text(json.dumps({
        "dependencies": present, "dsh": {"profile": {"bundles": ["sextant-dsh-mcp"]}},
    }))  # fmt: skip
    (tmp_path / "headless/node_modules").mkdir()
    (tmp_path / "headless/node_modules/sextant-dsh-mcp").symlink_to(bundle)
    assert str(bundle) not in parity.dsh_missing(tmp_path / "headless", repository)


@pytest.mark.parametrize("form", ["relative to the profile", "under ~", "absolute"])
def test_dsh_skills_go_to_its_own_home_and_the_bundle_through_dsh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    dsh_home = tmp_path / "dsh-home"
    _link_dsh_research(dsh_home, repository, form)
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("acp", "headless"):
        (dsh_home / "profiles" / name).mkdir(parents=True)
        (dsh_home / "profiles" / name / "package.json").write_text('{"dependencies": {}}')
    log = tmp_path / "dsh.log"
    dsh = _stub(tmp_path / "dsh", f'printf "%s\\n" "$*" >> "{log}"\n')
    _stub(tmp_path / "tools/pnpm", "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'tools'}:{os.environ['PATH']}")
    parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(dsh)], repository)
    assert len(list((dsh_home / "skills").iterdir())) == 25
    quality = parity.SPEC["runtimes"]["dsh"]["quality"]
    goalloop = next(
        row["spec"] for row in quality["plugins"] if row["package"] == "dsh-goalloop-agentteams"
    )
    shim = str(repository / "config/dsh/review-cmd")
    assert log.read_text().splitlines() == [
        f"plugin --profile acp add --save-exact {repository}/config/dsh/mcp {goalloop} {shim}",
        f"plugin --profile headless add --save-exact {repository}/config/dsh/mcp {goalloop} {shim}",
        f"plugin --profile dsh-tui add --save-exact {goalloop} {shim}",
    ]


def test_every_dsh_profile_composes_the_same_mcp_patches_and_effort_is_max() -> None:
    mcp = json.loads((ROOT / "config/dsh/mcp/package.json").read_text())["dsh"]["bundle"]["patch"]
    research = json.loads((ROOT / "config/dsh/package.json").read_text())
    patches = research["dsh"]["bundle"]["patch"]
    names = ("context7", "exa", "deepwiki", "paper-search", "source-tools")
    assert mcp == [f"./{name}.cordis.yml" for name in (*names, "max-effort")]
    assert [path for path in patches if path.startswith("./mcp/")] == [
        f"./mcp/{name}.cordis.yml" for name in (*names, "max-effort")
    ]
    assert all((ROOT / "config/dsh" / path).is_file() for path in patches)
    assert all((ROOT / "config/dsh/mcp" / path).is_file() for path in mcp)
    for job in ("playwright", "codegraph"):  # explicit --patch jobs, in no bundle
        assert (ROOT / f"config/dsh/mcp/{job}.cordis.yml").is_file()
        assert f"./{job}.cordis.yml" not in mcp and f"./mcp/{job}.cordis.yml" not in patches
    assert patches[-1] == "./mcp/max-effort.cordis.yml"
    text = (ROOT / "config/dsh/mcp/max-effort.cordis.yml").read_text()
    rows = {row["id"]: row["config"] for row in yaml.safe_load(text.replace("!!js ", ""))}
    assert rows["agent-default-model"] == {
        "provider": "deepseek-official",
        "model": "deepseek-flash",
        "reasoningEffort": "max",
    }
    llm = rows["llm-deepseek"]
    assert llm["thinking"] == "enabled" and llm["reasoningEffort"] == "max"
    assert llm["apiKeyEnv"] == "DEEPSEEK_API_KEY"
    # billion-context 0.1.212 replaces this row with its retries; composed last, both survive.
    assert llm["retryPolicy"]["retryableCodes"] == [
        "EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT", "MALFORMED_RESPONSE",
    ]  # fmt: skip


def _muse_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    prefix = tmp_path / "home" / LANE
    prefix.mkdir(parents=True)
    launcher = prefix / "muse-launch.sh"
    shutil.copyfile(RUNTIMES / "muse-launch.sh", launcher)
    launcher.chmod(0o755)
    for name in ("pins.json", "model-policy.json"):
        shutil.copyfile(RUNTIMES / name, prefix / name)
    version = json.loads((RUNTIMES / "pins.json").read_text())["muse"]["version"]
    log = tmp_path / "muse.log"
    _stub(tmp_path / f"home/.local/share/muse-code/muse-{version}", f'echo "$*" >> "{log}"\n')
    command = tmp_path / "muse"
    command.symlink_to(launcher)
    return command, log, tmp_path / "home"


# Muse's reminder roster runs below max and no documented setting pins it, so sessions turn it off.
QUIET = " ".join(
    f"-c runtime_capabilities.plugin:tbh-reminders:reminder:{name}.enabled=false"
    for name in ("skill-reminder", "goal-reminder", "verify-reminder")
)
PINS = "--model muse-wonder-full-1.0 --reasoning-effort max --contributor-mode off"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        ((), f"{PINS} {QUIET}"),
        (("--trust-workspace",), f"{PINS} {QUIET} --trust-workspace"),
        (("exec", "--json", "task"), f"exec {PINS} {QUIET} --json task"),
        (("serve",), f"serve --model muse-wonder-full-1.0 --contributor-mode off {QUIET}"),
        (("skills", "list", "--json"), "skills list --json"),
        (("--version",), "--version"),
        (
            ("exec", "--model", "muse-spark-1.3", "task"),
            f"exec --reasoning-effort max --contributor-mode off {QUIET} "
            "--model muse-spark-1.3 task",
        ),
    ),
)
def test_muse_sessions_run_wonder_full_at_max_with_contributor_mode_off(
    tmp_path: Path, arguments: tuple[str, ...], expected: str
) -> None:
    command, log, home = _muse_layout(tmp_path)
    result = subprocess.run(
        [str(command), *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().strip() == expected


@pytest.mark.parametrize(
    "arguments",
    (
        ("--contributor-mode", "on"),
        ("exec", "--contributor-mode=on", "task"),
        ("exec", "--model", "muse-spark-1.3-contributor", "task"),
    ),
)
def test_muse_refuses_contributor_mode_and_contributor_models(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    command, log, home = _muse_layout(tmp_path)
    result = subprocess.run(
        [str(command), *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert result.returncode == 2 and "product improvement" in result.stderr
    assert not log.exists()


def _keyed_layout(tmp_path: Path, launcher: str, keys: str) -> tuple[Path, Path, Path]:
    prefix = tmp_path / "home" / LANE
    prefix.mkdir(parents=True)
    shutil.copyfile(RUNTIMES / launcher, prefix / launcher)
    (prefix / launcher).chmod(0o755)
    shutil.copyfile(RUNTIMES / "model-policy.json", prefix / "model-policy.json")
    (prefix / "repository-path").write_text(str(tmp_path / "repo") + "\n")
    log = tmp_path / "calls.log"
    words = [*keys.split(), "--"]  # at most nine, so each is one positional parameter
    positions = " ".join(f"${index}" for index in range(1, len(words) + 1))
    _stub(
        tmp_path / "repo/scripts/with-keys.sh",
        f'[ "{positions}" = "{" ".join(words)}" ] || exit 9\n'
        f'echo keyed >> "{log}"\nshift {len(words)}\nexec "$@"\n',
    )
    return prefix, log, tmp_path / "home"


def test_dsh_injects_its_three_keys_in_one_strict_hop_and_versions_stay_keyless(
    tmp_path: Path,
) -> None:
    keys = "--strict -k DEEPSEEK_API_KEY -k CONTEXT7_API_KEY -k EXA_API_KEY"
    prefix, log, home = _keyed_layout(tmp_path, "dsh-launch.sh", keys)
    entry = prefix.parent / "sextant-agents/node_modules/@deepseek-ai/dsh/lib/bin.js"
    _stub(entry, f'echo "dsh $*" >> "{log}"\n')
    launcher = prefix / "dsh-launch.sh"
    for arguments in (("--profile", "acp"), ("--version",)):
        subprocess.run(
            [str(launcher), *arguments], check=True, env={**os.environ, "HOME": str(home)}
        )
    assert log.read_text().splitlines() == ["keyed", "dsh --profile acp", "dsh --version"]
    # dsh-tui's locator reads the first $-free quoted .js path beside the launcher.
    assert '"../sextant-agents/node_modules/@deepseek-ai/dsh/lib/bin.js"' in launcher.read_text()


def test_antigravity_sessions_are_keyed_and_its_config_commands_are_keyless(
    tmp_path: Path,
) -> None:
    prefix, log, home = _keyed_layout(
        tmp_path, "antigravity-launch.sh", "--strict -k CONTEXT7_API_KEY -k EXA_API_KEY"
    )
    _stub(prefix / "bin/antigravity/antigravity", f'echo "agy $*" >> "{log}"\n')
    launcher = prefix / "antigravity-launch.sh"
    for arguments in ((), ("mcp", "list"), ("plugin", "list", "--json"), ("--version",)):
        subprocess.run(
            [str(launcher), *arguments], check=True, env={**os.environ, "HOME": str(home)}
        )
    assert log.read_text().splitlines() == [
        "keyed",
        "agy --model gemini-4-argon-high --effort high",
        "agy mcp list",
        "agy plugin list --json",
        "agy --version",
    ]


def test_muse_is_pinned_to_metas_manifest_and_wonder_full_at_max() -> None:
    muse = json.loads((RUNTIMES / "pins.json").read_text())["muse"]
    base = "https://lookaside.facebook.com/lookaside/muse/download/?channel=muse"
    assert muse["version"] == "1.4.6-R6000.1"
    assert muse["manifest"] == f"{base}&version=1.4.6-R6000.1&file=manifest.json"
    assert muse["url"] == f"{base}&version=1.4.6-R6000.1&file=muse-x86-linux"
    assert muse["sha256"] == "82a495542965a5b6256f7acdb81693451c28640a419d5528ad8340ea93f36f6f"
    assert muse["size"] == 360958168
    policy = json.loads((RUNTIMES / "model-policy.json").read_text())["meta"]
    assert policy["model"] == "muse-wonder-full-1.0" and policy["effort"] == "max"
    assert policy["contributor_mode"] == "off"


MUSE_PAYLOAD = {
    ".muse-plugin/plugin.json": '{"schemaVersion":1,"name":"superpowers","version":"7.0.2"}\n',
    "skills/payload.md": "original payload\n",
    "retired.txt": "original retired payload\n",
}


@pytest.fixture
def muse_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    parity, home = _parity(), tmp_path / "home"
    cache = home / ".local/share/sextant-runtime-skills"
    data = home / ".local/share/muse"
    config = home / ".config/muse"
    registry = data / "plugins/installed.json"
    source = cache / "superpowers"
    prefix = home / LANE
    prefix.mkdir(parents=True)
    (prefix / "repository-path").write_text(str(ROOT))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(data.parent))
    monkeypatch.setattr(sys, "argv", ["parity.py", "--runtime", "muse"])
    skills = _skills(tmp_path / "skills")
    monkeypatch.setattr(parity, "shelf", lambda _cache: skills)
    for relative, content in MUSE_PAYLOAD.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def native(command: list[str]) -> None:
        noun, verb, path, *args = command[1:]
        assert (verb, args) == ("install", ["--scope", "user", "--json"])
        origin = Path(path)
        if noun == "skills":
            shutil.copytree(origin, config / "skills" / origin.name)
            return
        assert noun == "plugins"
        name = json.loads((origin / ".muse-plugin/plugin.json").read_text())["name"]
        body = b"".join(
            str(file.relative_to(origin)).encode() + b"\0" + file.read_bytes()
            for file in sorted(origin.rglob("*"))
            if file.is_file() and ".git" not in file.relative_to(origin).parts
        )
        digest = hashlib.sha256(body).hexdigest()
        root = data / "plugins/cache/local" / name
        if root.exists():
            shutil.rmtree(root)
        package = root / digest / "package"
        shutil.copytree(origin, package, ignore=shutil.ignore_patterns(".git"))
        (package.parent / "agent-definitions").mkdir()
        state = (
            json.loads(registry.read_text())
            if registry.exists()
            else {
                "version": 1,
                "plugins": {},
            }
        )
        state["plugins"][name] = {
            "id": name,
            "enabled": True,
            "source": {"provenance": "native-local", "path": str(origin)},
            "cache_path": str(package.relative_to(data)),
            "package_sha256": f"sha256:{digest}",
        }
        registry.write_text(json.dumps(state))

    monkeypatch.setattr(parity, "_native", native)
    return parity.main, source, registry, config, skills


def test_parity_delivers_muse_skills_and_mcp_without_changing_settings(muse_delivery, capsys):
    run, _source, registry, config, skills = muse_delivery
    settings = config / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b'{"model":"owner-value"}\n')
    assert run() == 0
    first = capsys.readouterr()
    assert 'muse: {"installed": 12}' in first.out
    state = registry.read_bytes()
    plugins = json.loads(state)["plugins"]
    assert set(plugins) == {"superpowers", "sextant-mcp"}
    mcp = registry.parents[1] / plugins["sextant-mcp"]["cache_path"]
    manifest = json.loads((mcp / ".muse-plugin/plugin.json").read_text())
    servers = {server["id"]: server for server in manifest["capabilities"]["mcpServers"]}
    assert set(servers) == set(SPEC["mcp"])
    for name, server in servers.items():
        assert server["command"] == ["bash", f"mcp/{name}.sh"]
        assert (mcp / server["command"][1]).is_file()
    superpowers = set(SPEC["shelf"]["superpowers@superpowers-dev"]["skills"])
    assert {path.name for path in (config / "skills").iterdir()} == set(skills) - superpowers
    assert run() == 0
    assert 'muse: {"unchanged": 12}' in capsys.readouterr().out
    assert settings.read_bytes() == b'{"model":"owner-value"}\n'
    assert registry.read_bytes() == state


def test_muse_mcp_wrappers_supply_config_after_muse_clears_the_environment(muse_delivery):
    run, _source, registry, _config, _skills = muse_delivery
    assert run() == 0
    plugins = json.loads(registry.read_text())["plugins"]
    package = registry.parents[1] / plugins["sextant-mcp"]["cache_path"]
    for name, key, header in (
        ("context7", "CONTEXT7_API_KEY", "Authorization: Bearer ${CONTEXT7_API_KEY}"),
        ("exa", "EXA_API_KEY", "x-api-key: ${EXA_API_KEY}"),
    ):
        script = (package / f"mcp/{name}.sh").read_text()
        command = shlex.split(script.split("exec ", 1)[1])
        assert command[:5] == [str(ROOT / "scripts/with-keys.sh"), "--strict", "-k", key, "--"]
        assert command[command.index("--header") + 1] == header
    paper = (package / "mcp/paper-search.sh").read_text()
    assert shlex.split(paper.split("exec ", 1)[1])[:2] == [
        "env",
        "PAPER_SEARCH_MCP_ENV_FILE=/dev/null",
    ]


def _muse_package(registry: Path) -> Path:
    record = json.loads(registry.read_text())["plugins"]["superpowers"]
    return registry.parents[1] / record["cache_path"]


def _filesystem_snapshot(root: Path) -> dict:
    def entry(path: Path) -> tuple[int, bytes | str | None]:
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            return mode, path.read_bytes()
        if stat.S_ISLNK(mode):
            return mode, os.readlink(path)
        return mode, None

    return {path.relative_to(root): entry(path) for path in (root, *root.rglob("*"))}


def _muse_mutations():
    for relative in MUSE_PAYLOAD:
        for operation in ("remove", "bytes", "permissions", "executable", "symlink"):
            yield pytest.param(operation, relative, id=f"{operation}-{relative}")
    for operation in ("permissions", "special-mode"):
        for relative in (".", "skills"):
            yield pytest.param(operation, relative, id=f"{operation}-dir-{relative}")
    for operation in ("add-file", "add-dir", "add-fifo"):
        yield pytest.param(operation, "owner-added", id=operation)
    yield pytest.param("add-file", "../../other-digest/package", id="orphan-cache")
    yield pytest.param("add-file", "../agent-definitions/owner.md", id="agent-cache")
    for field in ("cache_path", "package_sha256"):
        for operation in ("missing", "empty", "malformed", "other"):
            yield pytest.param(operation, field, id=f"record-{field}-{operation}")
    yield pytest.param("remove-record", "", id="orphan-package")
    yield pytest.param("remove-receipt", "", id="missing-baseline")


def _mutate_muse(operation: str, relative: str, package: Path, registry: Path, source: Path):
    if operation == "remove-receipt":
        (source.parent / "muse-superpowers.json").unlink()
    elif operation in {"missing", "empty", "malformed", "other", "remove-record"}:
        state = json.loads(registry.read_text())
        record = state["plugins"]["superpowers"]
        if operation == "remove-record":
            del state["plugins"]["superpowers"]
        elif operation == "missing":
            del record[relative]
        else:
            record[relative] = {
                "empty": "",
                "malformed": 17,
                "other": f"sha256:{'0' * 64}",
            }[operation]
        registry.write_text(json.dumps(state))
    else:
        target = package / relative
        if operation == "remove":
            target.unlink()
        elif operation == "bytes":
            target.write_bytes(target.read_bytes() + b"owner edit\n")
        elif operation in {"permissions", "executable", "special-mode"}:
            bit = {"permissions": 0o040, "executable": 0o100, "special-mode": 0o2000}
            target.chmod(stat.S_IMODE(target.stat().st_mode) ^ bit[operation])
        elif operation == "symlink":
            target.unlink()
            target.symlink_to(source / relative)
        elif operation == "add-file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("owner file\n")
        elif operation == "add-dir":
            target.mkdir()
        else:
            assert operation == "add-fifo"
            os.mkfifo(target)


@pytest.mark.parametrize("move_payload", (False, True), ids=("same", "moved"))
@pytest.mark.parametrize(("operation", "relative"), list(_muse_mutations()))
def test_parity_refuses_each_muse_mutation_and_preserves_state(
    muse_delivery, capsys, operation, relative, move_payload
):
    run, source, registry, _config, _skills = muse_delivery
    assert run() == 0
    capsys.readouterr()
    package = _muse_package(registry)
    if move_payload:
        (source / "skills/payload.md").write_text("incoming changed bytes\n")
        (source / "retired.txt").unlink()
    _mutate_muse(operation, relative, package, registry, source)
    before = _filesystem_snapshot(registry.parent)
    assert run() == 1
    assert "NOT_CONFIGURED:" in capsys.readouterr().err
    assert _filesystem_snapshot(registry.parent) == before


@pytest.mark.parametrize("change", ("payload", "mode"))
def test_parity_reinstalls_only_the_clean_muse_package_when_source_moves(
    muse_delivery, capsys, change
):
    run, source, registry, _config, _skills = muse_delivery
    assert run() == 0
    capsys.readouterr()
    incoming = source / "skills/payload.md"
    if change == "payload":
        incoming.write_text("incoming changed bytes\n")
        (source / "retired.txt").unlink()
    else:
        incoming.chmod(0o755)
    assert run() == 0
    assert 'muse: {"installed": 1, "unchanged": 11}' in capsys.readouterr().out
    assert _filesystem_snapshot(_muse_package(registry)) == _filesystem_snapshot(source)
    assert run() == 0
    assert 'muse: {"unchanged": 12}' in capsys.readouterr().out


def test_qmd_is_on_every_runtimes_path() -> None:
    setup = (ROOT / "deploy/wsl/setup.sh").read_text()
    assert 'ln -sfn "$qmd/node_modules/.bin/qmd" "$HOME/.local/bin/qmd"' in setup


def test_parity_installs_the_launchers_the_verified_muse_binary_and_the_cooled_bridge() -> None:
    parity = (RUNTIMES / "parity.sh").read_text()
    for name in ("agy", "dsh", "sextant-dsh", "muse"):
        assert f'"$HOME/.local/bin/{name}"' in parity
    assert "jq -r .muse.sha256" in parity and "sha256sum -c -" in parity
    assert (RUNTIMES / "install.sh").read_text().rstrip().endswith('bash "$here/parity.sh"')
    bridge = json.loads((RUNTIMES / "mcp-bridge/package-lock.json").read_text())["packages"]
    remote = bridge["node_modules/mcp-remote"]
    assert remote["version"] == "0.15.2" and remote["integrity"].startswith("sha512-3PrXMgjJew6x")


DSH_HOME = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh")


@pytest.mark.local
@pytest.mark.parametrize("profile", ["acp", "headless", "dsh-tui"])
def test_dsh_effective_tree_keeps_max_effort_after_every_bundle(profile: str) -> None:
    """The composed tree, not the patch file: a later bundle (billion-context 0.1.212 did) replacing
    a row's whole config would drop the pin silently."""
    package = "sextant-dsh-research" if profile == "dsh-tui" else "sextant-dsh-mcp"
    bundle = DSH_HOME / "profiles" / profile / "node_modules" / package
    if not (bundle / "package.json").is_file():
        pytest.skip("this dsh profile does not compose the branch's bundle yet")
    dsh = Path.home() / ".local/share/sextant-agents/node_modules/@deepseek-ai/dsh/lib/bin.js"
    tree = subprocess.run(
        [str(dsh), "--profile", profile, "--dump-config"],
        capture_output=True,
        text=True,
        env={**os.environ, "DSH_HOME": str(DSH_HOME)},
        check=True,
        timeout=120,
    ).stdout
    rows = [row for row in yaml.safe_load(tree.replace("!!js ", "")) if isinstance(row, dict)]
    final = {row["id"]: row for row in rows if "id" in row}  # the last layer's row wins
    llm = final["llm-deepseek"]["config"]
    assert llm["reasoningEffort"] == "max" and llm["thinking"] == "enabled"
    assert final["agent-default-model"]["config"]["reasoningEffort"] == "max"


def test_a_stalled_native_call_fails_visibly_instead_of_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parity = _parity()
    monkeypatch.setattr(parity, "NATIVE_TIMEOUT", 1)
    repository = _mcp_repository(tmp_path)
    dsh_home = tmp_path / "dsh-home"
    _link_dsh_research(dsh_home, repository)
    for name in ("acp", "headless"):
        (dsh_home / "profiles" / name).mkdir(parents=True)
        (dsh_home / "profiles" / name / "package.json").write_text('{"dependencies": {}}')
    _stub(tmp_path / "tools/pnpm", "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'tools'}:{os.environ['PATH']}")
    stalled = _stub(tmp_path / "dsh", "read -r line\nsleep 5\n")  # waits on stdin, then stalls
    with pytest.raises(subprocess.TimeoutExpired):
        parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(stalled)], repository)


def test_without_pnpm_the_dsh_step_stops_before_any_plugin_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    dsh_home = tmp_path / "dsh-home"
    _link_dsh_research(dsh_home, repository)
    for name in ("acp", "headless"):
        (dsh_home / "profiles" / name).mkdir(parents=True)
        (dsh_home / "profiles" / name / "package.json").write_text('{"dependencies": {}}')
    called = tmp_path / "called"
    dsh = _stub(tmp_path / "dsh", f'touch "{called}"\n')
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(parity.Refused, match="pnpm"):
        parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(dsh)], repository)
    assert not called.exists()


def test_parity_sh_stops_with_a_clear_message_when_pnpm_is_missing(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    _python3(tools)
    result = subprocess.run(
        ["/bin/bash", str(RUNTIMES / "parity.sh")],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": f"{tools}:/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 4
    assert "pnpm" in result.stderr and "deploy/wsl/dsh/package-lock.json" in result.stderr
    assert not (tmp_path / ".local/share/sextant-lane-runtimes").exists()  # before any change


def _mcp_repository(tmp_path: Path) -> Path:
    bundle = tmp_path / "repository/config/dsh/mcp"
    bundle.mkdir(parents=True)
    shutil.copyfile(ROOT / "config/dsh/mcp/package.json", bundle / "package.json")
    shutil.copyfile(ROOT / "config/dsh/package.json", bundle.parent / "package.json")
    return tmp_path / "repository"


def _link_dsh_research(
    dsh_home: Path, repository: Path, form: str = "relative to the profile"
) -> Path:
    profile = dsh_home / "profiles/dsh-tui"
    (profile / "node_modules").mkdir(parents=True)
    bundle = repository / "config/dsh"
    if form == "under ~":
        value = "~/" + str(bundle.relative_to(dsh_home.parent))
    elif form == "absolute":
        value = str(bundle)
    else:
        value = os.path.relpath(bundle, profile)
    manifest = {
        "dependencies": {"sextant-dsh-research": f"link:{value}"},
        "dsh": {"profile": {"bundles": ["sextant-dsh-research"]}},
    }
    (profile / "package.json").write_text(json.dumps(manifest))
    (profile / "node_modules/sextant-dsh-research").symlink_to(bundle, target_is_directory=True)
    return profile


@pytest.mark.parametrize(
    "state",
    [
        "missing profile",
        "missing dependency",
        "stale dependency",
        "missing link",
        "stale link",
        "inactive bundle",
    ],
)
def test_a_missing_or_stale_dsh_tui_research_link_is_refused_before_any_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    dsh_home = tmp_path / "dsh-home"
    profile = _link_dsh_research(dsh_home, repository)
    manifest = profile / "package.json"
    data = json.loads(manifest.read_text())
    link = profile / "node_modules/sextant-dsh-research"
    if state == "missing profile":
        shutil.rmtree(profile)
    elif state == "missing dependency":
        data["dependencies"].clear()
    elif state == "stale dependency":
        data["dependencies"]["sextant-dsh-research"] = "link:../old-repository/config/dsh"
    elif state == "missing link":
        link.unlink()
    elif state == "stale link":
        link.unlink()
        link.symlink_to(tmp_path / "old-repository/config/dsh", target_is_directory=True)
    else:
        data["dsh"]["profile"]["bundles"].clear()
    if state != "missing profile":
        manifest.write_text(json.dumps(data))
    before = parity._tree(dsh_home)
    paths = sorted(str(path.relative_to(dsh_home)) for path in dsh_home.rglob("*"))
    log = tmp_path / "dsh.log"
    dsh = _stub(tmp_path / "dsh", f'printf "%s\\n" "$*" >> "{log}"\n')
    _stub(tmp_path / "tools/pnpm", "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'tools'}:{os.environ['PATH']}")
    with pytest.raises(parity.Refused, match=r"dsh-tui.*sextant-dsh-research"):
        parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(dsh)], repository)
    assert parity._tree(dsh_home) == before
    assert sorted(str(path.relative_to(dsh_home)) for path in dsh_home.rglob("*")) == paths
    assert not log.exists() and not (dsh_home / "skills").exists()


def test_dsh_plugin_initializes_a_shipped_profile_that_never_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dsh-official-bundles README: app-boot initializes a missing shipped profile (acp, headless)
    from its template; dsh-app-boot README: `dsh plugin` initializes a base-backed profile."""
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    dsh_home = tmp_path / "dsh-home"
    _link_dsh_research(dsh_home, repository)
    log = tmp_path / "dsh.log"
    dsh = _stub(tmp_path / "dsh", f'printf "%s\\n" "$*" >> "{log}"\n')
    _stub(tmp_path / "tools/pnpm", "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'tools'}:{os.environ['PATH']}")
    parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(dsh)], repository)
    bundle = repository / "config/dsh/mcp"
    quality = parity.SPEC["runtimes"]["dsh"]["quality"]
    goalloop = next(
        row["spec"] for row in quality["plugins"] if row["package"] == "dsh-goalloop-agentteams"
    )
    shim = str(repository / "config/dsh/review-cmd")
    assert log.read_text().splitlines() == [
        f"plugin --profile acp add --save-exact {bundle} {goalloop} {shim}",
        f"plugin --profile headless add --save-exact {bundle} {goalloop} {shim}",
        f"plugin --profile dsh-tui add --save-exact {goalloop} {shim}",
    ]


def test_dsh_quality_rows_install_the_p10_picks_on_every_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    shim = repository / "config/dsh/review-cmd"
    (shim / "node_modules").mkdir(parents=True)
    (shim / "package.json").write_text(json.dumps({"name": "sextant-dsh-review-cmd"}))
    (shim / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    dsh_home = tmp_path / "dsh-home"
    _link_dsh_research(dsh_home, repository)
    log = tmp_path / "dsh.log"
    dsh = _stub(tmp_path / "dsh", f'printf "%s\\n" "$*" >> "{log}"\n')
    pnpm_log = tmp_path / "pnpm.log"
    _stub(tmp_path / "tools/pnpm", f'printf "%s\\n" "$*" >> "{pnpm_log}"\n')
    monkeypatch.setenv("PATH", f"{tmp_path / 'tools'}:{os.environ['PATH']}")
    parity.install_dsh(_skills(tmp_path / "source"), dsh_home, [str(dsh)], repository)
    quality = parity.SPEC["runtimes"]["dsh"]["quality"]
    goalloop = next(
        row["spec"] for row in quality["plugins"] if row["package"] == "dsh-goalloop-agentteams"
    )
    assert log.read_text().splitlines() == [
        f"plugin --profile acp add --save-exact {repository}/config/dsh/mcp {goalloop} {shim}",
        f"plugin --profile headless add --save-exact {repository}/config/dsh/mcp {goalloop} {shim}",
        f"plugin --profile dsh-tui add --save-exact {goalloop} {shim}",
    ]
    assert len(pnpm_log.read_text().splitlines()) == 3


def test_a_step_failing_on_the_filesystem_is_reported_and_later_steps_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parity = _parity()
    home = tmp_path / "home"
    (home / LANE).mkdir(parents=True)
    (home / LANE / "repository-path").write_text(f"{ROOT}\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["parity.py"])
    monkeypatch.setattr(parity, "shelf", lambda cache: {})
    ran: list[str] = []

    def unreadable(*args: object) -> list[str]:
        raise PermissionError("profiles/acp/package.json is unreadable")

    monkeypatch.setattr(parity, "install_codex", lambda *args: ran.append("codex") or [])
    monkeypatch.setattr(parity, "install_dsh", unreadable)
    monkeypatch.setattr(parity, "install_antigravity", lambda *args: ran.append("agy") or [])
    assert parity.main() == 1
    assert ran == ["codex", "agy"]
    assert "dsh: NOT_CONFIGURED: profiles/acp/package.json is unreadable" in capsys.readouterr().err


@pytest.mark.parametrize("form", ["relative to the profile", "under ~", "absolute"])
def test_a_bundle_link_recorded_relative_or_under_home_counts_as_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """dsh-plugin-manager (installed, lib/index.js:214): pnpm records a `file:` or `link:` path
    relative to the profile or with `~` for the home directory."""
    parity = _parity()
    monkeypatch.setenv("HOME", str(tmp_path))
    repository = _mcp_repository(tmp_path)
    bundle = repository / "config/dsh/mcp"
    profile = tmp_path / "dsh-home/profiles/acp"
    profile.mkdir(parents=True)
    if form == "under ~":
        value = "~/" + str(bundle.relative_to(tmp_path))
    elif form == "absolute":  # what dsh 0.2.2-rc.1 recorded on a scratch home
        value = str(bundle)
    else:
        value = os.path.relpath(bundle, profile)
    recorded = {"sextant-dsh-mcp": f"link:{value}"}
    (profile / "package.json").write_text(json.dumps({
        "dependencies": recorded, "dsh": {"profile": {"bundles": ["sextant-dsh-mcp"]}},
    }))  # fmt: skip
    (profile / "node_modules").mkdir()
    (profile / "node_modules/sextant-dsh-mcp").symlink_to(bundle)
    assert str(bundle) not in parity.dsh_missing(profile, repository)


@pytest.mark.parametrize("name", ["acp", "headless"])
@pytest.mark.parametrize("state", ["missing link", "stale link", "inactive bundle"])
def test_acp_and_headless_require_the_installed_target_and_enabled_bundle(
    tmp_path: Path, name: str, state: str
) -> None:
    parity = _parity()
    repository = _mcp_repository(tmp_path)
    bundle = repository / "config/dsh/mcp"
    profile = tmp_path / "dsh-home/profiles" / name
    (profile / "node_modules").mkdir(parents=True)
    data = {
        "dependencies": {"sextant-dsh-mcp": f"link:{os.path.relpath(bundle, profile)}"},
        "dsh": {"profile": {"bundles": [] if state == "inactive bundle" else ["sextant-dsh-mcp"]}},
    }
    (profile / "package.json").write_text(json.dumps(data))
    if state != "missing link":
        target = tmp_path / "old-repository/config/dsh/mcp" if state == "stale link" else bundle
        (profile / "node_modules/sextant-dsh-mcp").symlink_to(target)
    assert parity.dsh_missing(profile, repository)[0] == str(bundle)


def _snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (
            path.lstat().st_mode,
            str(path.readlink())
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else None,
        )
        for path in (root, *root.rglob("*"))
    }


@pytest.mark.parametrize(
    ("runtime", "relative"),
    [
        ("codex", "."), ("codex", ".."), ("codex", "skills"), ("codex", "config.toml"),
        ("dsh", "."), ("dsh", "skills"), ("dsh", "profiles"), ("dsh", "profiles/acp"),
        ("dsh", "profiles/headless"), ("dsh", "profiles/acp/node_modules"),
        ("dsh", "profiles/acp/package.json"),
        ("antigravity", "."), ("antigravity", ".."), ("antigravity", "skills"),
        ("antigravity", "plugin.json"), ("antigravity", "LICENSE.tradermonty"),
    ],
)  # fmt: skip
def test_a_linked_managed_root_is_refused_before_any_lane_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str, relative: str
) -> None:
    parity = _parity()
    home = tmp_path / "home"
    cache = home / ".local/share/sextant-runtime-skills"
    dsh_home = home / ".dsh"
    repository = _mcp_repository(tmp_path)
    _link_dsh_research(dsh_home, repository)
    lane = {
        "codex": home / LANE / "codex-home",
        "dsh": dsh_home,
        "antigravity": cache / "antigravity",
    }[runtime]
    lane.mkdir(parents=True, exist_ok=True)
    lane.chmod(0o755)  # even chmod must wait for the preflight
    root = Path(os.path.abspath(lane / relative))
    root.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "shared"
    is_file = root.suffix in (".toml", ".json", ".tradermonty")
    if root.exists():
        root.rename(target)
    elif is_file:
        target.write_text("")
    else:
        target.mkdir()
    root.symlink_to(target, target_is_directory=not is_file)
    skills = _skills(tmp_path / "source")
    calls: list[list[str]] = []
    monkeypatch.setattr(parity, "_native", lambda command: calls.append(command))
    monkeypatch.setattr(parity.shutil, "which", lambda command: "/fixture/pnpm")
    before = _snapshot(tmp_path)
    with pytest.raises(parity.Refused, match="managed root"):
        if runtime == "codex":
            parity.install_codex(skills, home)
        elif runtime == "dsh":
            parity.install_dsh(skills, dsh_home, ["fixture-dsh"], repository)
        else:
            parity.install_antigravity(skills, cache, home, ["fixture-agy"], tmp_path / "bridge")
    assert _snapshot(tmp_path) == before
    assert calls == []


@pytest.mark.parametrize("step", ["preflight", "installer"])
@pytest.mark.parametrize("target_exists", [True, False], ids=["existing", "dangling"])
@pytest.mark.parametrize("relative", ANTIGRAVITY_NATIVE_ROOTS)
def test_antigravity_native_roots_are_refused_before_any_write_or_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
    target_exists: bool,
    relative: str,
) -> None:
    parity = _parity()
    home = tmp_path / "home"
    root = home / relative
    root.parent.mkdir(parents=True)
    target = tmp_path / "shared"
    is_file = root.suffix in (".json", ".md")
    if target_exists:
        if is_file:
            target.write_text("an owner's state\n")
        else:
            target.mkdir()
            (target / "owner-state").write_text("keep me\n")
    root.symlink_to(target, target_is_directory=not is_file)
    skills = _skills(tmp_path / "source")
    calls: list[list[str]] = []
    monkeypatch.setattr(parity, "_native", lambda command: calls.append(command))
    monkeypatch.setenv("DSH_HOME", str(home / ".dsh"))
    before = _snapshot(tmp_path)
    with pytest.raises(parity.Refused, match="managed root"):
        if step == "preflight":
            parity.preflight(home)
        else:
            parity.install_antigravity(
                skills,
                home / ".local/share/sextant-runtime-skills",
                home,
                ["fixture-agy"],
                tmp_path / "bridge",
            )
    assert _snapshot(tmp_path) == before
    assert calls == []


def test_antigravity_native_install_accepts_real_roots_and_a_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parity = _parity()
    home = tmp_path / "home"
    monkeypatch.setenv("DSH_HOME", str(home / ".dsh"))
    for relative in ANTIGRAVITY_NATIVE_ROOTS:
        root = home / relative
        if root.suffix in (".json", ".md"):
            root.parent.mkdir(parents=True, exist_ok=True)
            root.write_text("owner state\n")
        else:
            root.mkdir(parents=True, exist_ok=True)
    before = _snapshot(home / ".gemini")
    skills = _skills(tmp_path / "source")
    cache = home / ".local/share/sextant-runtime-skills"
    bridge = tmp_path / "bridge"
    calls: list[list[str]] = []
    monkeypatch.setattr(parity, "_native", lambda command: calls.append(command))
    for _ in range(2):
        parity.preflight(home)
        parity.install_antigravity(skills, cache, home, ["fixture-agy"], bridge)
        assert _snapshot(home / ".gemini") == before
    expected = [
        ["fixture-agy", "plugin", "install", str(cache / name)]
        for name in ("superpowers", "antigravity")
    ] + [["fixture-agy", "mcp", *command] for command in parity.agy_mcp_commands(home, bridge)]
    assert calls == expected * 2
    assert json.loads((cache / "antigravity/plugin.json").read_text())["name"] == "sextant-shelf"


@pytest.mark.parametrize("installer", ["install.sh", "parity.sh"])
@pytest.mark.parametrize(
    "relative", [LANE, f"{LANE}/mcp-bridge", ".local/bin", ".dsh/skills", *ANTIGRAVITY_NATIVE_ROOTS]
)
def test_shell_installers_preflight_managed_roots_before_any_home_write(
    tmp_path: Path, installer: str, relative: str
) -> None:
    home = tmp_path / "home"
    target = tmp_path / "shared"
    root = home / relative
    is_file = root.suffix in (".json", ".md")
    if is_file:
        target.write_text("owner state\n")
    else:
        target.mkdir()
    root.parent.mkdir(parents=True)
    root.symlink_to(target, target_is_directory=not is_file)
    tools = tmp_path / "tools"
    _stub(tools / "pnpm", "exit 0\n")
    _python3(tools)
    # A missed preflight must never reach downloads, native installs or live tools.
    for command in ("npm", "curl", "install", "uv"):
        _stub(tools / command, "exit 86\n")
    before = _snapshot(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(RUNTIMES / installer)], capture_output=True, text=True,
        env={"HOME": str(home), "PATH": f"{tools}:/usr/bin:/bin", "TMPDIR": str(tmp_path)},
        check=False,
    )  # fmt: skip
    assert result.returncode != 0 and "managed root" in result.stderr
    assert _snapshot(tmp_path) == before


def _git_fixture(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Sextant",
         "-c", "user.email=sextant@Noesis.localdomain", "-c", "commit.gpgsign=false",
         "-C", str(path), *args], text=True,
    ).strip()  # fmt: skip


def _cached_shelf(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git_fixture(upstream, "init", "--initial-branch=main")
    skill = upstream / "SKILL.md"
    skill.write_text("old pin\n")
    _git_fixture(upstream, "add", "SKILL.md")
    _git_fixture(upstream, "commit", "-m", "old pin")
    _git_fixture(upstream, "tag", "v1")
    cache = tmp_path / "cache"
    _git_fixture(tmp_path, "clone", "--depth", "1", "--branch", "v1", upstream.as_uri(), str(cache))
    skill.write_text("new pin\n")
    _git_fixture(upstream, "commit", "-am", "new pin")
    _git_fixture(upstream, "tag", "v2")
    pin = {"repo": "fixture/shelf", "ref": "v2", "sha": _git_fixture(upstream, "rev-parse", "HEAD")}
    return upstream, cache, pin


def test_a_clean_shelf_cache_fetches_and_checks_out_the_new_locked_pin(tmp_path: Path) -> None:
    parity = _parity()
    _, cache, pin = _cached_shelf(tmp_path)
    assert parity.checkout(cache, pin) == cache
    assert _git_fixture(cache, "rev-parse", "HEAD") == pin["sha"]
    assert (cache / "SKILL.md").read_text() == "new pin\n"
    assert parity.checkout(cache, pin) == cache  # reruns stay unchanged


@pytest.mark.parametrize("kind", ["tracked", "untracked", "ignored"])
def test_a_dirty_shelf_cache_is_kept_before_fetching_a_new_pin(tmp_path: Path, kind: str) -> None:
    parity = _parity()
    _, cache, pin = _cached_shelf(tmp_path)
    edited = cache / ("SKILL.md" if kind == "tracked" else "local-notes")
    if kind == "ignored":
        (cache / ".git/info/exclude").write_text("local-notes\n")
    edited.write_text("keep the owner's edit\n")
    head = _git_fixture(cache, "rev-parse", "HEAD")
    with pytest.raises(parity.Refused, match="differs from its pinned commit"):
        parity.checkout(cache, pin)
    assert _git_fixture(cache, "rev-parse", "HEAD") == head
    assert not (cache / ".git/FETCH_HEAD").exists()
    assert edited.read_text() == "keep the owner's edit\n"


def test_a_linked_shelf_cache_is_refused_before_git_can_write(tmp_path: Path) -> None:
    parity = _parity()
    _, cache, pin = _cached_shelf(tmp_path)
    linked = tmp_path / "linked-cache"
    linked.symlink_to(cache, target_is_directory=True)
    with pytest.raises(parity.Refused, match="managed root"):
        parity.checkout(linked, pin)
    assert not (cache / ".git/FETCH_HEAD").exists()


@pytest.mark.parametrize("login", [".codex", ".config/orca/accounts/codex", ".local/share/orca"])
def test_a_lane_codex_home_inside_a_login_home_is_refused_before_any_write(
    tmp_path: Path, login: str
) -> None:
    """codex-launch.sh's guard, in the installer too: the lane CODEX_HOME never resolves into
    ~/.codex or an Orca account home, where Codex's ChatGPT logins live."""
    parity = _parity()
    launcher = (RUNTIMES / "codex-launch.sh").read_text()
    assert all(f'"$(readlink -m "$HOME/{root}")"/*' in launcher for root in parity.LOGIN_HOMES)
    home = tmp_path / "home"
    target = home / login
    target.mkdir(parents=True)
    lane = home / LANE / "codex-home"
    lane.parent.mkdir(parents=True)
    lane.symlink_to(target)
    with pytest.raises(parity.Refused, match="login home"):
        parity.install_codex(_skills(tmp_path / "source"), home)
    assert list(target.iterdir()) == []


def test_no_dsh_profile_installs_dsh_defend() -> None:
    """The lead, 2026-11-08 10:48:49, at the owner's question: dsh-defend is out. The secrets line
    keeps with-keys.sh, gitleaks over every PR range in `just ci` and #262's hard-lines plugin."""
    research = json.loads((ROOT / "config/dsh/package.json").read_text())
    assert "dsh-defend" not in research.get("devDependencies", {})  # setup.sh's dsh-tui list
    assert "dsh-defend" not in json.dumps(SPEC)  # parity.py's acp and headless adds
    assert "dsh-defend" not in (ROOT / "deploy/wsl/setup.sh").read_text()

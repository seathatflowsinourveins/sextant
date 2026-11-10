#!/usr/bin/env python3
"""Prove every runtime row as it is launched, before a session uses it (LEAD-1821 section 3).

The rows are the landscape's: Claude Code, DeepSeek Harness, Codex, Antigravity, Muse, the
OmniRoute router, Orca and AO. For each row this reads the surface that actually launches it:
the installed version against its pin, the model and effort against the policy or the tracked
config, the shelf and MCP set in that runtime's own home, the native hard-line guard, and every
repository path the row reads. A drift stops `just session-start`; the host is fixed, never the
check. Proofs live in tests/proofs/test_runtime_doctor.py as fixture homes carrying one defect.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIMES = ROOT / "deploy" / "wsl" / "lane-runtimes"
# The host floats on latest but Fable 5.2 needs this floor: anthropics/claude-code@v2.1.321
# CHANGELOG.md:5 and code.claude.com/docs/en/model-config, read 2026-11-09; the host acceptance
# test holds the same floor (tests/host/test_clean_distro.py:15-19).
CLAUDE_FABLE_FLOOR = "2.1.321"
CHECKS = ("version", "model_effort", "parity", "guard", "repository")
ROWS = ("claude", "dsh", "codex", "antigravity", "muse", "omniroute", "orca", "ao")
WATCH_CHECK = ("watch", "turn_started")
WATCH_BOUND_SOURCE = "orchestration.workerStart timeoutMs (Orca 1.4.251)"
CLAUDE = re.compile(r"claude|anthropic|opus|sonnet|haiku", re.IGNORECASE)
VERSION = re.compile(r"(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)")
SHELF_PLUGINS = (
    "superpowers@superpowers-dev",
    "compound-engineering@compound-engineering-plugin",
    "typesafe@typesafe-ai",
)
LSP_PLUGINS = ("pyright-lsp@sextant-lsp", "typescript-lsp@sextant-lsp")
DSH_MCP = ("mcp-context7", "mcp-exa", "mcp-deepwiki", "mcp-paper-search")


@dataclass(frozen=True)
class Result:
    """One host command's exit code and text, with a failure normalized for the doctor."""

    code: int
    out: str = ""
    err: str = ""

    @property
    def text(self) -> str:
        return f"{self.out}\n{self.err}"


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> Result:
    """Run one native command; a missing binary or a stall is a finding, never a traceback."""
    child_env = dict(os.environ)
    if env:
        child_env.update(env)
    try:
        done = subprocess.run(
            command,
            cwd=cwd,
            env=child_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Result(127, "", f"{type(error).__name__}: {error}")
    return Result(done.returncode, done.stdout, done.stderr)


@dataclass
class Host:
    """The home, checkout and installed prefix the doctor reads; tests inject a fake runner."""

    home: Path
    repo: Path
    prefix: Path
    runner: Callable[..., Result] = run_command

    def run(self, command: list[str], **kwargs: object) -> Result:
        return self.runner(command, **kwargs)

    def path(self, *parts: str) -> Path:
        return self.home.joinpath(*parts)


@dataclass(frozen=True)
class Finding:
    """One drift with a stable row.check code, so a proof can name the defect it caught."""

    row: str
    check: str
    message: str

    @property
    def code(self) -> str:
        return f"{self.row}.{self.check}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checked: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)


def _finding(row: str, check: str, message: str) -> Finding:
    return Finding(row, check, message)


def _fail(out: dict[str, list[Finding]], row: str, check: str, message: str) -> None:
    out[check].append(_finding(row, check, message))


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _json_file(path: Path) -> Any:
    text = _read(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _json_text(text: str) -> Any:
    """Decode the first complete JSON value after any CLI banner.

    A line that merely starts with "[" can be a bracketed banner such as
    "[dotenv@17.2.1] ..."; only a line whose raw decode succeeds is the reply.
    """
    decoder = json.JSONDecoder()
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped[:1] in ("{", "["):
            try:
                return decoder.raw_decode(text[offset + len(line) - len(stripped) :])[0]
            except (json.JSONDecodeError, ValueError):
                pass
        offset += len(line)
    return None


def _json_command(host: Host, command: list[str], **kwargs: object) -> Any:
    result = host.run(command, **kwargs)
    if result.code != 0:
        return None
    return _json_text(result.out) or _json_text(result.text)


def _sha_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _version(text: str) -> str | None:
    found = VERSION.search(text)
    return found.group(1) if found else None


def _semver(text: str | None) -> tuple[int, ...]:
    if not text:
        return ()
    return tuple(int(part) for part in text.split("-", 1)[0].split("."))


def _policy(host: Host) -> Any:
    value = _json_file(host.repo / RUNTIMES.relative_to(ROOT) / "model-policy.json")
    return value if isinstance(value, dict) else {}


def _pins(host: Host) -> Any:
    value = _json_file(host.repo / RUNTIMES.relative_to(ROOT) / "pins.json")
    return value if isinstance(value, dict) else {}


_PARITY: dict[str, object] = {}


def _parity(host: Host) -> Any:
    """Import the one tracked renderer so the doctor checks bytes, never a second copy."""
    path = host.repo / RUNTIMES.relative_to(ROOT) / "parity.py"
    key = str(path.resolve())
    if key not in _PARITY:
        spec = importlib.util.spec_from_file_location("sextant_runtime_parity", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PARITY[key] = module
    return _PARITY[key]


def _shelf(host: Host) -> list[str]:
    return list(_parity(host).shelf_names())


def _automations(host: Host) -> list[dict]:
    value = _json_command(host, ["orca-ide", "automations", "list", "--json"])
    if isinstance(value, dict):
        result = value.get("result", value)
        if isinstance(result, dict):
            rows = result.get("automations", [])
            return [row for row in rows if isinstance(row, dict)]
    return []


def _remote(host: Host) -> str:
    result = host.run(["git", "-C", str(host.repo), "remote", "get-url", "origin"])
    return result.out.strip() if result.code == 0 else ""


def _slug(url: str) -> str:
    found = re.search(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$", url.strip())
    return found.group(1) if found else ""


def _is_main_worktree(host: Host, candidate: Path) -> bool:
    """A declared checkout is permanent only when git lists it as its main worktree."""
    result = host.run(["git", "-C", str(candidate), "worktree", "list", "--porcelain"])
    if result.code != 0:
        return False
    for line in result.out.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ")).resolve() == candidate.resolve()
    return False


def _main_checkout(host: Host) -> Path:
    """The canonical host checkout, even when the doctor runs from an AO clone.

    The installer records the host checkout in prefix/repository-path. Trust it only
    when it is this repository's main worktree, never a linked task worktree; otherwise
    fall back to the first worktree entry, which is the main checkout of a normal setup.
    """
    declared = _read(host.prefix / "repository-path")
    if declared:
        candidate = Path(declared.strip()).expanduser()
        if candidate.is_dir():
            same = candidate.resolve() == host.repo.resolve()
            if not same:
                want = _slug(_remote(host))
                got = _slug(
                    host.run(["git", "-C", str(candidate), "remote", "get-url", "origin"]).out
                )
                same = bool(want) and got == want
            if same and _is_main_worktree(host, candidate):
                return candidate.resolve()
    result = host.run(["git", "-C", str(host.repo), "worktree", "list", "--porcelain"])
    if result.code == 0:
        for line in result.out.splitlines():
            if line.startswith("worktree "):
                return Path(line.removeprefix("worktree ")).resolve()
    return host.repo.resolve()


def _current_repository(
    host: Host, value: object, main: Path | None = None, allow_clone: bool = False
) -> bool:
    """A host path names this checkout when it is the main checkout or below it.

    A separate clone of the same repository is only accepted where a clone is the
    expected shape (AO's project and its repos directory), never for an installed
    path or another checkout's plugin record.
    """
    if not isinstance(value, str) or not value:
        return False
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = host.repo / path
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.is_dir():
        return False
    checkout = main or _main_checkout(host)
    if resolved == checkout or checkout in resolved.parents:
        return True
    if not allow_clone or not path.is_dir():
        return False
    top = host.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    if top.code != 0:
        return False
    origin = host.run(["git", "-C", str(path), "remote", "get-url", "origin"])
    return origin.code == 0 and _slug(origin.out) == _slug(_remote(host))


def _check_installed_launcher(
    host: Host, row: str, check: str, out: dict[str, list[Finding]], name: str, repo_file: Path
) -> None:
    link = host.home / ".local" / "bin" / name
    if not link.exists():
        _fail(out, row, check, f"~/.local/bin/{name} is missing; run the tracked installer")
        return
    try:
        target = link.resolve()
    except OSError:
        _fail(out, row, check, f"~/.local/bin/{name} does not resolve")
        return
    if not target.is_file():
        _fail(out, row, check, f"~/.local/bin/{name} resolves to {target.name}, not a file")
        return
    if _sha_file(target) != _sha_file(repo_file):
        _fail(
            out,
            row,
            check,
            f"~/.local/bin/{name} resolves to an installed launcher that differs from "
            f"deploy/wsl/lane-runtimes/{repo_file.name}",
        )
        return
    if repo_file.name in ("codex-launch.sh", "muse-launch.sh"):
        prefix_file = host.prefix / repo_file.name
        if _sha_file(prefix_file) != _sha_file(repo_file):
            _fail(
                out,
                row,
                check,
                f"{prefix_file.name} in the installed prefix differs from the tracked launcher",
            )


def _check_repository_path(host: Host, row: str, out: dict[str, list[Finding]]) -> None:
    file = host.prefix / "repository-path"
    value = _read(file)
    if value is None:
        _fail(
            out,
            row,
            "repository",
            "~/.local/share/sextant-lane-runtimes/repository-path is missing",
        )
        return
    if not _current_repository(host, value.strip()):
        _fail(
            out,
            row,
            "repository",
            f"repository-path names {value.strip()}, not the main checkout {_main_checkout(host)}",
        )


def _check_prefix_policy(host: Host, row: str, check: str, out: dict[str, list[Finding]]) -> Any:
    installed = _json_file(host.prefix / "model-policy.json")
    tracked = _json_file(host.repo / RUNTIMES.relative_to(ROOT) / "model-policy.json")
    if installed is None:
        _fail(out, row, check, "installed model-policy.json is missing")
    elif installed != tracked:
        _fail(out, row, check, "installed model-policy.json differs from the tracked policy")
    return tracked if isinstance(tracked, dict) else {}


def _check_routing(host: Host, row: str, check: str, out: dict[str, list[Finding]]) -> Any:
    installed = _json_file(host.prefix / "routing.json")
    tracked = _json_file(host.repo / RUNTIMES.relative_to(ROOT) / "routing.json")
    if installed is None:
        _fail(out, row, check, "installed routing.json is missing")
    elif installed != tracked:
        _fail(out, row, check, "installed routing.json differs from the tracked routing")
    return tracked if isinstance(tracked, dict) else {}


# --- rows ---------------------------------------------------------------------------


def check_claude(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    settings = _json_file(host.repo / ".claude" / "settings.json")
    receipt = _json_file(host.repo / "deploy" / "wsl" / "hard-lines" / "claude-receipt.json")
    policy = _policy(host)
    claude_policy = policy.get("claude") if isinstance(policy.get("claude"), dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    receipt = receipt if isinstance(receipt, dict) else {}

    result = host.run(["claude", "--version"])
    installed = _version(result.text)
    floor = CLAUDE_FABLE_FLOOR
    if result.code != 0 or not installed:
        _fail(out, "claude", "version", f"claude --version failed: {result.text.strip()[:160]}")
    elif _semver(installed) < _semver(floor):
        _fail(
            out,
            "claude",
            "version",
            f"Claude Code {installed} is older than the Fable floor {floor}",
        )

    env_value = settings.get("env")
    env = env_value if isinstance(env_value, dict) else {}
    if settings.get("model") != receipt.get("model"):
        _fail(
            out,
            "claude",
            "model_effort",
            f"project model {settings.get('model')!r} differs from the hard-lines receipt "
            f"model {receipt.get('model')!r}",
        )
    if env.get("CLAUDE_CODE_EFFORT_LEVEL") != claude_policy.get("effort"):
        _fail(
            out,
            "claude",
            "model_effort",
            f"CLAUDE_CODE_EFFORT_LEVEL is {env.get('CLAUDE_CODE_EFFORT_LEVEL')!r}, not "
            f"{claude_policy.get('effort')!r}",
        )
    automations = _automations(host)
    reflection = next(
        (row for row in automations if row.get("name") == "Verified reflection"), None
    )
    if reflection is None:
        _fail(out, "claude", "model_effort", "Orca has no Verified reflection automation")
    else:
        args = str(reflection.get("extraAgentArgs") or "")
        reflection_policy = policy.get("claude_reflection") or policy.get("claude", {})
        want = (
            f"--model {reflection_policy.get('model')} --effort {reflection_policy.get('effort')}"
        )
        if want not in args:
            _fail(
                out,
                "claude",
                "model_effort",
                f"Verified reflection runs {args!r}, not the policy {want!r}",
            )

    enabled_value = settings.get("enabledPlugins")
    enabled = enabled_value if isinstance(enabled_value, dict) else {}
    expected = list(SHELF_PLUGINS) + list(LSP_PLUGINS)
    missing = [plugin for plugin in expected if enabled.get(plugin) is not True]
    if missing:
        _fail(out, "claude", "parity", f"project plugins not enabled: {', '.join(missing)}")
    lock = _parity(host).LOCK
    for relative, digest in lock["skills"]["files"].items():
        path = host.repo / ".claude" / "skills" / relative
        if _sha_file(path) != digest:
            _fail(out, "claude", "parity", f"trading skill {relative} differs from its lock hash")
            break
    records = _json_command(host, ["claude", "plugin", "list", "--json"])
    if not isinstance(records, list):
        _fail(out, "claude", "parity", "claude plugin list --json did not return a list")
    else:
        main = _main_checkout(host)
        current: dict[str, Any] = {}
        for row in records:
            if not isinstance(row, dict) or not row.get("projectPath"):
                continue
            try:
                project = Path(str(row.get("projectPath"))).resolve()
            except OSError:
                continue
            if project == main:
                current[str(row.get("id"))] = row
        installed_ids = {key for key, row in current.items() if row.get("projectEnabled") is True}
        absent = [plugin for plugin in expected if plugin not in installed_ids]
        if absent:
            _fail(
                out,
                "claude",
                "parity",
                f"plugin install records are missing {', '.join(absent)} for this checkout",
            )
        for row in current.values():
            path = row.get("installPath")
            if path and not Path(str(path)).is_dir():
                _fail(out, "claude", "parity", f"plugin {row.get('id')} install path is missing")
                break

    deny = (
        settings.get("permissions", {}).get("deny")
        if isinstance(settings.get("permissions"), dict)
        else None
    )
    if not isinstance(deny, list) or not deny:
        _fail(out, "claude", "guard", "project permissions.deny is empty")
    elif _sha_text(json.dumps(deny)) != receipt.get("deny_sha256"):
        _fail(
            out,
            "claude",
            "guard",
            "project deny list differs from the hard-lines receipt deny_sha256",
        )
    if receipt.get("permission_mode") != "bypassPermissions":
        _fail(
            out,
            "claude",
            "guard",
            f"hard-lines receipt permission_mode is {receipt.get('permission_mode')!r}",
        )

    marketplace_value = settings.get("extraKnownMarketplaces")
    marketplaces = marketplace_value if isinstance(marketplace_value, dict) else {}
    for name, row in marketplaces.items():
        source = row.get("source") if isinstance(row, dict) else None
        if isinstance(source, dict):
            path = source.get("path") or source.get("repo")
            if (
                isinstance(path, str)
                and path.startswith("/")
                and not _current_repository(host, path)
            ):
                _fail(
                    out,
                    "claude",
                    "repository",
                    f"marketplace {name} source path names {path}, not this checkout",
                )
    for automation in automations:
        run_value = automation.get("runContext")
        run = run_value if isinstance(run_value, dict) else {}
        path = run.get("path")
        if isinstance(path, str) and not _current_repository(host, path):
            _fail(
                out,
                "claude",
                "repository",
                f"automation {automation.get('name')} runs at {path}, not this checkout",
            )
    return out


def _yaml_block(text: str, ident: str) -> str | None:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"- id: {ident}"), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("- id: ")), len(lines)
    )
    return "\n".join(lines[start + 1 : end])


def _yaml_field(block: str | None, key: str) -> str | None:
    if block is None:
        return None
    found = re.search(rf"^\s+{re.escape(key)}:\s*(\S+)\s*$", block, re.MULTILINE)
    return found.group(1).strip("'\"") if found else None


def _dsh_home(host: Host) -> Path:
    """The one dsh home the command, manifests and skills must share.

    DSH_HOME wins when the caller set it; otherwise dsh's own default is ~/.dsh.
    A leftover ~/.dsh-full profile tree must never redirect only the manifest reads.
    """
    configured = os.environ.get("DSH_HOME")
    return Path(configured).expanduser() if configured else host.home / ".dsh"


def _dsh_profile(host: Host, profile: str, home: Path) -> tuple[Result, str]:
    result = host.run(["dsh", "--profile", profile, "--dump-config"], env={"DSH_HOME": str(home)})
    return result, result.text


def check_dsh(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    lock = _json_file(host.repo / "config" / "dsh" / "profile.lock.json")
    lock = lock if isinstance(lock, dict) else {}
    result = host.run(["dsh", "--version"])
    installed = _version(result.text)
    if result.code != 0 or installed != lock.get("engine"):
        _fail(
            out,
            "dsh",
            "version",
            f"dsh {installed or 'unknown'} does not match the locked engine {lock.get('engine')}",
        )

    patch = _read(host.repo / "config" / "dsh" / "mcp" / "max-effort.cordis.yml") or ""
    want_provider = _yaml_field(_yaml_block(patch, "agent-default-model"), "provider")
    want_model = _yaml_field(_yaml_block(patch, "agent-default-model"), "model")
    want_effort = _yaml_field(_yaml_block(patch, "agent-default-model"), "reasoningEffort")
    want_thinking = _yaml_field(_yaml_block(patch, "llm-deepseek"), "thinking")
    want_provider_effort = _yaml_field(_yaml_block(patch, "llm-deepseek"), "reasoningEffort")
    dsh_home = _dsh_home(host)
    profiles = ["acp", "headless", "dsh-tui"]
    for profile in profiles:
        run, text = _dsh_profile(host, profile, dsh_home)
        if run.code != 0:
            _fail(out, "dsh", "model_effort", f"dsh --profile {profile} --dump-config failed")
            continue
        default = _yaml_block(text, "agent-default-model")
        llm = _yaml_block(text, "llm-deepseek")
        got = (
            _yaml_field(default, "provider"),
            _yaml_field(default, "model"),
            _yaml_field(default, "reasoningEffort"),
            _yaml_field(llm, "thinking"),
            _yaml_field(llm, "reasoningEffort"),
        )
        want = (want_provider, want_model, want_effort, want_thinking, want_provider_effort)
        if got != want:
            _fail(
                out, "dsh", "model_effort", f"profile {profile} runs {got}, not the tracked {want}"
            )
        for ident in DSH_MCP:
            if _yaml_block(text, ident) is None:
                _fail(out, "dsh", "parity", f"profile {profile} is missing {ident}")
        guard = _yaml_block(text, "sextant-hard-lines")
        if guard is None or "hard-lines.mjs" not in guard:
            _fail(out, "dsh", "guard", f"profile {profile} has no sextant-hard-lines guard")

    for name in _shelf(host):
        if not (dsh_home / "skills" / name / "SKILL.md").is_file():
            _fail(out, "dsh", "parity", f"~/.dsh/skills/{name} is missing")
            break
    spec = _parity(host).SPEC["runtimes"]["dsh"]
    mcp_bundle = host.repo / spec["mcp_bundle"]
    mcp_package = _json_file(mcp_bundle / "package.json")
    mcp_name = str(mcp_package.get("name")) if isinstance(mcp_package, dict) else ""
    hard = _json_file(host.repo / "config" / "dsh" / "hard-lines" / "package.json")
    hard_name = str(hard.get("name")) if isinstance(hard, dict) else "sextant-dsh-hard-lines"
    quality = spec["quality"]
    quality_profiles = quality["profiles"]
    link_packages = {hard_name}
    for profile in profiles:
        required = [hard_name]
        if profile in quality_profiles:
            for entry in quality["plugins"]:
                if profile in entry.get("profiles", quality_profiles):
                    required.append(entry["package"])
                    if entry["spec"].startswith(("config/", ".github/")):
                        link_packages.add(entry["package"])
        if profile != "dsh-tui" and mcp_name:
            required.append(mcp_name)
            link_packages.add(mcp_name)
        manifest = _json_file(dsh_home / "profiles" / profile / "package.json")
        if not isinstance(manifest, dict):
            _fail(out, "dsh", "parity", f"profile {profile} has no package.json")
            continue
        dependency_value = manifest.get("dependencies")
        dependencies = dependency_value if isinstance(dependency_value, dict) else {}
        dsh_value = manifest.get("dsh")
        dsh = dsh_value if isinstance(dsh_value, dict) else {}
        profile_value = dsh.get("profile")
        profile_row = profile_value if isinstance(profile_value, dict) else {}
        bundles = profile_row.get("bundles", [])
        if not isinstance(bundles, list):
            bundles = []
        for package in dict.fromkeys(required):
            recorded = dependencies.get(package)
            if recorded is None or (
                package in link_packages and not str(recorded).startswith("link:")
            ):
                _fail(out, "dsh", "parity", f"profile {profile} does not record {package}")
            if package not in bundles:
                _fail(out, "dsh", "parity", f"profile {profile} does not enable {package}")
    installed = host.prefix / "dsh-launch.sh"
    if _sha_file(installed) != _sha_file(host.repo / RUNTIMES.relative_to(ROOT) / "dsh-launch.sh"):
        _fail(out, "dsh", "repository", "installed dsh-launch.sh differs from the tracked launcher")
    _check_repository_path(host, "dsh", out)
    return out


def check_codex(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    agents = _json_file(host.repo / ".devcontainer" / "agents" / "package.json")
    pin = None
    if isinstance(agents, dict):
        pin = agents.get("dependencies", {}).get("@openai/codex")
    pin = str(pin).lstrip("^~=") if pin else None
    result = host.run(["codex", "--version"])
    installed = _version(result.text)
    if result.code != 0 or installed != pin:
        _fail(
            out, "codex", "version", f"Codex {installed or 'unknown'} does not match the pin {pin}"
        )

    policy = _check_prefix_policy(host, "codex", "model_effort", out)
    routing = _check_routing(host, "codex", "model_effort", out)
    model = policy.get("gpt", {}).get("model")
    effort = policy.get("gpt", {}).get("effort")
    expected_member = f"codex/{model}-{effort}" if model and effort else ""
    models = routing.get("models") if isinstance(routing.get("models"), list) else []
    if expected_member and expected_member not in models:
        _fail(
            out,
            "codex",
            "model_effort",
            f"routing.json does not name the policy member {expected_member}",
        )
    _check_installed_launcher(
        host,
        "codex",
        "model_effort",
        out,
        "sextant-codex",
        host.repo / RUNTIMES.relative_to(ROOT) / "codex-launch.sh",
    )
    launcher = _read(host.prefix / "codex-launch.sh") or ""
    for needle in (
        'pool=$(jq -er .combo "$prefix/routing.json")',
        'effort=$(jq -er .gpt.effort "$prefix/model-policy.json")',
        '-c "model=\\"$pool\\""',
        '-c "model_reasoning_effort=\\"$effort\\""',
    ):
        if needle not in launcher:
            _fail(out, "codex", "model_effort", f"installed codex-launch.sh lacks {needle}")

    lane = host.prefix / "codex-home"
    expected = _parity(host).codex_toml(host.home)
    actual = _read(lane / "config.toml")
    if actual is None:
        _fail(out, "codex", "parity", "codex-home/config.toml is missing")
    elif actual != expected:
        _fail(out, "codex", "parity", "codex-home/config.toml differs from the pinned render")
    if lane.is_dir() and (lane.stat().st_mode & 0o077):
        _fail(out, "codex", "parity", "codex-home is readable by another user")
    for name in _shelf(host):
        if not (lane / "skills" / name / "SKILL.md").is_file():
            _fail(out, "codex", "parity", f"codex-home/skills/{name} is missing")
            break

    rules = _read(lane / "rules" / "sextant-hard-lines.rules")
    tracked = _read(host.repo / ".codex" / "rules" / "default.rules")
    if rules is None:
        _fail(out, "codex", "guard", "codex-home/rules/sextant-hard-lines.rules is missing")
    elif rules != tracked:
        _fail(out, "codex", "guard", "lane Codex rules differ from .codex/rules/default.rules")

    _check_repository_path(host, "codex", out)
    return out


def check_antigravity(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    pins = _pins(host)
    want = pins.get("runtimes", {}).get("antigravity", {}).get("version")
    result = host.run(["agy", "--version"])
    installed = _version(result.text)
    if result.code != 0 or installed != want:
        _fail(
            out,
            "antigravity",
            "version",
            f"agy {installed or 'unknown'} does not match the pin {want}",
        )

    policy = _policy(host).get("google", {})
    _check_installed_launcher(
        host,
        "antigravity",
        "model_effort",
        out,
        "agy",
        host.repo / RUNTIMES.relative_to(ROOT) / "antigravity-launch.sh",
    )
    launcher = _read(host.prefix / "antigravity-launch.sh") or ""
    for needle in (
        '--model "$model"',
        f"--effort {policy.get('effort')}",
        "AGY_CLI_DISABLE_AUTO_UPDATE=true",
    ):
        if needle not in launcher:
            _fail(out, "antigravity", "model_effort", f"installed launcher lacks {needle}")
    models = host.run(["agy", "models"])
    if models.code != 0 or str(policy.get("antigravity")) not in models.text:
        _fail(
            out,
            "antigravity",
            "model_effort",
            f"agy models does not list the policy model {policy.get('antigravity')}",
        )

    parity = _parity(host)
    plugins = _json_command(host, ["agy", "plugin", "list", "--json"])
    if not isinstance(plugins, list):
        _fail(out, "antigravity", "parity", "agy plugin list --json did not return a list")
    else:
        by_name = {row.get("name"): row for row in plugins if isinstance(row, dict)}
        superpowers = set(parity.SPEC["shelf"]["superpowers@superpowers-dev"]["skills"])
        shelf = set(_shelf(host)) - superpowers
        for name, expected in (("sextant-shelf", shelf), ("superpowers", superpowers)):
            row = by_name.get(name)
            if row is None or row.get("enabled") is not True:
                _fail(out, "antigravity", "parity", f"Antigravity plugin {name} is not enabled")
            elif set(row.get("skills", [])) != expected:
                _fail(
                    out,
                    "antigravity",
                    "parity",
                    f"Antigravity plugin {name} carries {len(row.get('skills', []))} skills, "
                    f"not {len(expected)}",
                )
    mcp = host.run(["agy", "mcp", "list"])
    if mcp.code != 0:
        _fail(out, "antigravity", "parity", "agy mcp list failed")
    else:
        lines = [
            line for line in mcp.out.splitlines() if line.strip() and not line.startswith("NAME")
        ]
        names = {line.split()[0]: line for line in lines if len(line.split()) > 1}
        for name, server in parity.SPEC["mcp"].items():
            if name not in names:
                _fail(out, "antigravity", "parity", f"Antigravity MCP server {name} is missing")
                continue
            status = "disabled" if server.get("opt_in") else "enabled"
            if status not in names[name]:
                _fail(
                    out, "antigravity", "parity", f"Antigravity MCP server {name} is not {status}"
                )
        for name in ("context7", "exa"):
            if name in names and "mcp-remote" not in names[name]:
                _fail(
                    out,
                    "antigravity",
                    "parity",
                    f"Antigravity MCP server {name} bypasses mcp-bridge",
                )
    hard = _json_file(host.repo / "deploy" / "wsl" / "hard-lines" / "antigravity.json")
    settings = _json_file(host.home / ".gemini" / "antigravity-cli" / "settings.json")
    deny = hard.get("permissions", {}).get("deny") if isinstance(hard, dict) else None
    have = settings.get("permissions", {}).get("deny") if isinstance(settings, dict) else None
    if not isinstance(deny, list) or not isinstance(have, list):
        _fail(out, "antigravity", "guard", "Antigravity deny rules are missing")
    else:
        absent = [rule for rule in deny if rule not in have]
        if absent:
            _fail(
                out,
                "antigravity",
                "guard",
                f"Antigravity settings are missing {len(absent)} hard-line deny rule(s)",
            )
        path = host.home / ".gemini" / "antigravity-cli" / "settings.json"
        if path.is_file() and (path.stat().st_mode & 0o077):
            _fail(out, "antigravity", "guard", "Antigravity settings are readable by another user")

    trusted = settings.get("trustedWorkspaces") if isinstance(settings, dict) else None
    if isinstance(trusted, list):
        # A trusted path may be this checkout or a separate clone of this repository (the trading
        # lead's own working copy, AO's clone). One that no longer exists is what the hard-lines
        # installer's prune removes; one that exists but is not this repository stays a finding.
        missing: list[object] = []
        foreign: list[object] = []
        for value in trusted:
            path = Path(value).expanduser() if isinstance(value, str) and value else None
            if path is not None and not path.is_absolute():
                path = host.repo / path
            if path is not None and not path.exists():
                missing.append(value)
            elif not _current_repository(host, value, allow_clone=True):
                foreign.append(value)
        if missing:
            _fail(
                out,
                "antigravity",
                "repository",
                f"{len(missing)} Antigravity trusted workspace(s) no longer exist, so the "
                f"installer's prune removes them: "
                f"{', '.join(map(str, missing[:3]))}{'...' if len(missing) > 3 else ''}",
            )
        if foreign:
            _fail(
                out,
                "antigravity",
                "repository",
                f"{len(foreign)} Antigravity trusted workspace(s) name another checkout: "
                f"{', '.join(map(str, foreign[:3]))}{'...' if len(foreign) > 3 else ''}",
            )
    _check_repository_path(host, "antigravity", out)
    return out


def check_muse(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    pins = _pins(host)
    want = pins.get("muse", {}).get("version")
    result = host.run(["muse", "--version"])
    if result.code != 0 or str(want) not in result.text:
        _fail(
            out,
            "muse",
            "version",
            f"Muse output {result.text.strip()!r} does not carry the pin {want}",
        )

    meta = _policy(host).get("meta", {})
    settings = _json_file(host.home / ".config" / "muse" / "settings.json")
    settings = settings if isinstance(settings, dict) else {}
    if settings.get("reasoning_effort") != meta.get("effort"):
        _fail(
            out,
            "muse",
            "model_effort",
            f"Muse reasoning_effort is {settings.get('reasoning_effort')!r}, "
            f"not {meta.get('effort')!r}",
        )
    if settings.get("contributor_mode_enabled") is not False:
        _fail(out, "muse", "model_effort", "Muse contributor mode is not disabled")
    _check_installed_launcher(
        host,
        "muse",
        "model_effort",
        out,
        "muse",
        host.repo / RUNTIMES.relative_to(ROOT) / "muse-launch.sh",
    )
    profile = host.run(
        [
            "muse",
            "model-profile",
            "show",
            str(meta.get("model")),
            "--effort",
            str(meta.get("effort")),
        ]
    )
    if (
        profile.code != 0
        or str(meta.get("model")) not in profile.text
        or str(meta.get("effort")) not in profile.text
    ):
        _fail(
            out,
            "muse",
            "model_effort",
            "muse model-profile does not attest the policy model and effort",
        )
    launcher = _read(host.prefix / "muse-launch.sh") or ""
    for needle in (
        "--contributor-mode=on",
        "*-contributor*",
        "reasoning-effort",
        "runtime_capabilities",
    ):
        if needle not in launcher:
            _fail(out, "muse", "guard", f"installed muse-launch.sh lacks {needle}")
    spec = _parity(host).SPEC["runtimes"]["muse"]
    if "#256" not in str(spec.get("shelf_and_mcp", "")):
        _fail(out, "muse", "parity", "the tracked Muse shelf/MCP deferral is not recorded")
    _check_repository_path(host, "muse", out)
    return out


def check_omniroute(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    pins = _pins(host)
    want = pins.get("omniroute", {}).get("version")
    binary = host.prefix / "router" / "node_modules" / ".bin" / "omniroute"
    result = host.run([str(binary), "--version"])
    installed = _version(result.text)
    if result.code != 0 or installed != want:
        _fail(
            out,
            "omniroute",
            "version",
            f"OmniRoute {installed or 'unknown'} does not match the pin {want}",
        )

    policy = _policy(host)
    combo_name = (_json_file(host.repo / RUNTIMES.relative_to(ROOT) / "routing.json") or {}).get(
        "combo"
    )
    data = host.run(
        [str(binary), "api", "combos", "get-api-combos", "--output", "json"],
        env={
            "DATA_DIR": str(host.prefix / "router-data"),
            "OMNIROUTE_BASE_URL": "http://127.0.0.1:22128",
            "OMNIROUTE_NO_UPDATE_NOTIFIER": "1",
        },
    )
    reply = _json_text(data.text) if data.code == 0 else None
    combos = reply.get("combos", []) if isinstance(reply, dict) else []
    combo = next((row for row in combos if row.get("name") == combo_name), None)
    want_member = (
        f"codex/{policy.get('gpt', {}).get('model')}-{policy.get('gpt', {}).get('effort')}"
    )
    if combo is None:
        _fail(out, "omniroute", "model_effort", f"router combo {combo_name!r} is missing")
    else:
        members = [
            str(member.get("model"))
            for member in combo.get("models", [])
            if member.get("kind") == "model"
        ]
        if members != [want_member]:
            _fail(
                out,
                "omniroute",
                "model_effort",
                f"router combo {combo_name} serves {members}, not [{want_member}]",
            )
        if any(CLAUDE.search(member) for member in members):
            _fail(out, "omniroute", "guard", "router combo reaches a Claude model")

    active = host.run(["systemctl", "--user", "is-active", "omniroute.service"])
    if active.code != 0 or active.out.strip() != "active":
        _fail(out, "omniroute", "parity", "omniroute.service is not active")
    unit = host.run(
        [
            "systemctl",
            "--user",
            "show",
            "omniroute.service",
            "-p",
            "ExecStart",
            "-p",
            "WorkingDirectory",
            "-p",
            "EnvironmentFiles",
        ]
    )
    if unit.code == 0:
        if str(host.prefix / "router-start.sh") not in unit.out:
            _fail(
                out,
                "omniroute",
                "parity",
                "omniroute.service does not run the tracked router-start.sh",
            )
        if "EnvironmentFiles=" in unit.out and "EnvironmentFiles=\n" not in unit.out + "\n":
            _fail(out, "omniroute", "parity", "omniroute.service loads an EnvironmentFile")
    routing = _json_file(host.prefix / "routing.json") or _json_file(
        host.repo / RUNTIMES.relative_to(ROOT) / "routing.json"
    )
    routing = routing if isinstance(routing, dict) else {}
    models = routing.get("models", [])
    retained = sorted(
        {str(model).split("/", 1)[0] for model in models if isinstance(model, str) and "/" in model}
    )
    if not retained:
        _fail(out, "omniroute", "parity", "routing.json names no retained runtime for key renewal")
    else:
        due = host.run(
            ["python3", "-I", str(host.repo / "scripts" / "omni_keys.py"), "due", *retained],
            env={"SEXTANT_LANE_RUNTIMES": str(host.prefix)},
        )
        if due.code == 0:
            _fail(out, "omniroute", "parity", "a runtime key is due for renewal")
        elif due.code != 1:
            _fail(out, "omniroute", "parity", f"omni_keys.py due failed (exit {due.code})")

    binds = host.run(["ss", "-ltnp"])
    if binds.code == 0:
        rows = [line for line in binds.out.splitlines() if ":22128" in line]
        if not rows:
            _fail(out, "omniroute", "guard", "nothing listens on the router's loopback port 22128")
        elif any("0.0.0.0:22128" in line or "[::]:22128" in line for line in rows):
            _fail(out, "omniroute", "guard", "port 22128 is bound beyond 127.0.0.1")

    working = host.run(
        ["systemctl", "--user", "show", "omniroute.service", "-p", "WorkingDirectory", "--value"]
    )
    if working.code != 0 or not _current_repository(host, working.out.strip()):
        _fail(
            out,
            "omniroute",
            "repository",
            f"omniroute.service WorkingDirectory is {working.out.strip()!r}, not this checkout",
        )
    _check_repository_path(host, "omniroute", out)
    return out


def _prompt_head(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def check_orca(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    pins = _pins(host)
    want = str(pins.get("orca", {}).get("tag", "")).removeprefix("v")
    result = host.run(["orca-ide", "--version"])
    installed = _version(result.text)
    if result.code != 0 or installed != want:
        _fail(
            out, "orca", "version", f"Orca {installed or 'unknown'} does not match the pin {want}"
        )

    full_policy = _policy(host)
    policy = full_policy.get("claude", {})
    reflection_policy = full_policy.get("claude_reflection") or policy
    automations = _automations(host)
    by_name = {row.get("name"): row for row in automations}
    lifecycle = by_name.get("Lifecycle sweep")
    reflection = by_name.get("Verified reflection")
    if reflection is None:
        _fail(out, "orca", "model_effort", "Orca has no Verified reflection automation")
    else:
        args = str(reflection.get("extraAgentArgs") or "")
        want_args = (
            f"--model {reflection_policy.get('model')} --effort {reflection_policy.get('effort')}"
        )
        if want_args not in args:
            _fail(
                out,
                "orca",
                "model_effort",
                f"Verified reflection runs {args!r}, not the policy {want_args!r}",
            )
    if lifecycle is None:
        _fail(out, "orca", "parity", "Orca has no Lifecycle sweep automation")

    remote = _slug(_remote(host))
    for name, automation, prompt_file, precheck_name in (
        ("Lifecycle sweep", lifecycle, "lifecycle-prompt.md", "lifecycle-precheck.sh"),
        ("Verified reflection", reflection, "reflection-prompt.md", "reflection-precheck.sh"),
    ):
        if automation is None:
            continue
        precheck_value = automation.get("precheck")
        precheck = precheck_value if isinstance(precheck_value, dict) else {}
        command = str(precheck.get("command") or "")
        path_match = re.search(r"(/\S+deploy/wsl/[^\s]+)", command)
        if not path_match:
            _fail(out, "orca", "guard", f"{name} precheck is not a tracked deploy/wsl script")
        else:
            script = Path(path_match.group(1))
            if not script.is_file():
                _fail(out, "orca", "guard", f"{name} precheck script {script.name} is missing")
            elif script.name != precheck_name:
                _fail(
                    out, "orca", "guard", f"{name} precheck is {script.name}, not {precheck_name}"
                )
            elif not _current_repository(host, str(script.parent)):
                _fail(
                    out,
                    "orca",
                    "repository",
                    f"{name} precheck runs {script.parent}, not a checkout of this repository",
                )
        prompt = str(automation.get("prompt") or "")
        tracked = _read(host.repo / "deploy" / "wsl" / prompt_file) or ""
        if not prompt or _prompt_head(prompt) != _prompt_head(tracked):
            _fail(out, "orca", "parity", f"{name} prompt is not the tracked {prompt_file}")
        run_value = automation.get("runContext")
        run = run_value if isinstance(run_value, dict) else {}
        source_value = automation.get("sourceContext")
        source = source_value if isinstance(source_value, dict) else {}
        identity_value = source.get("providerIdentity")
        identity = identity_value if isinstance(identity_value, dict) else {}
        if not _current_repository(host, run.get("path")):
            _fail(
                out, "orca", "repository", f"{name} runs at {run.get('path')!r}, not this checkout"
            )
        if remote and identity and f"{identity.get('owner')}/{identity.get('repo')}" != remote:
            _fail(
                out,
                "orca",
                "repository",
                f"{name} is bound to {identity.get('owner')}/{identity.get('repo')}, not {remote}",
            )
        if remote and run.get("projectId") not in (None, "", f"github:{remote}"):
            _fail(
                out,
                "orca",
                "repository",
                f"{name} run projectId is {run.get('projectId')!r}, not github:{remote}",
            )
        if remote and source.get("projectId") not in (None, "", f"github:{remote}"):
            _fail(
                out,
                "orca",
                "repository",
                f"{name} source projectId is {source.get('projectId')!r}, not github:{remote}",
            )
    return out


def _ao_projects(host: Host) -> list[dict]:
    database = host.home / ".ao" / "data" / "ao.db"
    if not database.is_file():
        return []
    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        rows = connection.execute("select * from projects").fetchall()
        connection.close()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def check_ao(host: Host) -> dict[str, list[Finding]]:
    out = {check: [] for check in CHECKS}
    script = _read(host.repo / "deploy" / "wsl" / "ao.sh") or ""
    pin_version = re.search(r"pin_version=(\S+)", script)
    pin_commit = re.search(r"pin_commit=(\S+)", script)
    result = host.run(["ao", "version"])
    installed = _version(result.text)
    if result.code != 0 or not pin_version or installed != pin_version.group(1):
        _fail(
            out,
            "ao",
            "version",
            f"AO {installed or 'unknown'} does not match the tracked pin "
            f"{pin_version.group(1) if pin_version else '?'}",
        )
    elif pin_commit and pin_commit.group(1)[:12] not in result.text:
        _fail(out, "ao", "version", "AO reports a commit other than the tracked pin")

    status = _json_command(host, ["ao", "status", "--json"])
    state = status.get("state") if isinstance(status, dict) else None
    if state != "running":
        _fail(out, "ao", "parity", f"AO daemon is {state or 'unknown'}, not running")
    doctor = _json_command(host, ["ao", "doctor", "--json"])
    if isinstance(doctor, dict) and doctor.get("failures"):
        _fail(out, "ao", "parity", f"AO doctor reports {doctor.get('failures')} failure(s)")
    projects = _ao_projects(host)
    if not projects:
        _fail(out, "ao", "parity", "AO has no project for this repository")
    policy = _policy(host)
    claude_policy = policy.get("claude") if isinstance(policy.get("claude"), dict) else {}
    receipt = _json_file(host.repo / "deploy" / "wsl" / "hard-lines" / "claude-receipt.json")
    receipt = receipt if isinstance(receipt, dict) else {}
    worker_model = None
    for project in projects:
        config = (
            project.get("config")
            or project.get("agent_config")
            or project.get("agentConfig")
            or "{}"
        )
        try:
            parsed = json.loads(config) if isinstance(config, str) else config
        except json.JSONDecodeError:
            parsed = {}
        worker = parsed.get("worker", {}).get("agent") if isinstance(parsed, dict) else None
        agent = parsed.get("agentConfig", {}) if isinstance(parsed, dict) else {}
        worker_model = (worker, agent.get("model"), agent.get("effort"))
        if worker != "claude-code":
            _fail(
                out,
                "ao",
                "model_effort",
                f"AO project {project.get('id')} worker is {worker!r}, not claude-code",
            )
        if agent.get("model") != receipt.get("model"):
            _fail(
                out,
                "ao",
                "model_effort",
                f"AO worker model {agent.get('model')!r} differs from the receipt "
                f"{receipt.get('model')!r}",
            )
        if agent.get("effort") != policy.get("claude", {}).get("effort"):
            _fail(
                out,
                "ao",
                "model_effort",
                f"AO worker effort {agent.get('effort')!r} differs from "
                f"{claude_policy.get('effort')!r}",
            )
    if worker_model and worker_model[0] != "claude-code":
        _fail(out, "ao", "parity", "AO's project worker is not the Claude Code default")

    for needle in (
        "--claim-pr",
        "--no-takeover",
        "review-family codex",
        'default=$(gh repo view "$repo_url" --json defaultBranchRef --jq .defaultBranchRef.name)',
        ".baseRefName == $default",
        'mergeMethod == "SQUASH"',
        'select(.name == "ci"',
    ):
        if needle not in script:
            _fail(out, "ao", "guard", f"ao.sh claim guard lacks {needle}")
    for project in projects:
        if not _current_repository(host, project.get("path"), allow_clone=True):
            _fail(
                out,
                "ao",
                "repository",
                f"AO project {project.get('id')} works in {project.get('path')}, "
                "not this repository",
            )
        url = str(
            project.get("repo_origin_url")
            or project.get("repo_url")
            or project.get("repoUrl")
            or ""
        )
        if url and _slug(url) != _slug(_remote(host)):
            _fail(
                out,
                "ao",
                "repository",
                f"AO project {project.get('id')} repository is {url}, not {_remote(host)}",
            )
    repos = host.home / ".ao" / "repos"
    if repos.is_dir():
        for clone in repos.iterdir():
            if clone.is_dir() and not _current_repository(host, str(clone), allow_clone=True):
                _fail(
                    out, "ao", "repository", f"AO clone {clone.name} does not name this repository"
                )
    return out


ROW_FUNCTIONS = {
    "claude": check_claude,
    "dsh": check_dsh,
    "codex": check_codex,
    "antigravity": check_antigravity,
    "muse": check_muse,
    "omniroute": check_omniroute,
    "orca": check_orca,
    "ao": check_ao,
}


def _age_seconds(text: object) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - moment).total_seconds())


def check_watch(host: Host, notes: list[str] | None = None) -> list[Finding]:
    """Alert when Orca accepted a prompt but no turn start followed its own dispatch bound."""
    path = host.home / ".config" / "orca" / "orchestration.db"
    if not path.is_file():
        return [
            _finding(
                *WATCH_CHECK,
                "orchestration database is missing at "
                f"{path}; a dispatched prompt's turn start is unobserved",
            )
        ]
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            dispatches = connection.execute(
                "select dispatch_id, state, stage, start_options, created_at, updated_at "
                "from worker_dispatches"
            ).fetchall()
            receipts = connection.execute(
                "select receipt, created_at from mutation_receipts "
                "where method = 'orchestration.workerStart'"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as error:
        return [
            _finding(
                *WATCH_CHECK,
                f"orchestration database is unreadable ({type(error).__name__}); "
                "turn start is unobserved",
            )
        ]

    latest: dict[str, tuple[float | None, dict[str, Any]]] = {}
    for row in receipts:
        try:
            receipt = json.loads(row["receipt"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        dispatch_id = receipt.get("dispatchId")
        if not isinstance(dispatch_id, str):
            continue
        stamp = _age_seconds(row["created_at"])
        previous = latest.get(dispatch_id)
        if previous is None or (stamp is not None and (previous[0] is None or stamp < previous[0])):
            latest[dispatch_id] = (stamp, receipt)

    findings: list[Finding] = []
    for row in dispatches:
        dispatch_id = row["dispatch_id"]
        state = row["state"]
        if not isinstance(dispatch_id, str) or state not in (
            "starting",
            "ready",
            "start_unknown",
            "outcome_unknown",
        ):
            continue
        receipt_row = latest.get(dispatch_id)
        if receipt_row is None:
            continue
        receipt = receipt_row[1]
        turn_start = receipt.get("turnStart")
        if turn_start == "observed" or receipt.get("state") in (
            "succeeded",
            "failed",
            "stopped",
            "abandoned",
        ):
            continue
        prompt = receipt.get("prompt") if isinstance(receipt.get("prompt"), dict) else {}
        stages = prompt.get("stages") if isinstance(prompt.get("stages"), list) else []
        if receipt.get("stage") != "input_accepted" and "input_accepted" not in stages:
            continue
        if "turn_started" in stages:
            continue
        provider = prompt.get("provider")
        observation = prompt.get("observation")
        if observation != "supported":
            detail = (
                f"dispatch {dispatch_id}: input accepted; provider {provider or 'unreported'} "
                f"({observation or 'unreported'}) is unobservable, so Orca cannot claim "
                "its turn start"
            )
            screen = (
                receipt.get("screenConfirm")
                or receipt.get("screen_confirm")
                or receipt.get("screen")
            )
            detail += f"; screen-confirm: {screen}" if screen else "; no screen-confirm recorded"
            if notes is not None:
                notes.append(detail)
            continue
        bound = receipt.get("timeoutMs")
        if not isinstance(bound, (int, float)):
            try:
                options = json.loads(row["start_options"] or "{}")
            except (TypeError, json.JSONDecodeError):
                options = {}
            milliseconds = options.get("timeoutMs") if isinstance(options, dict) else None
            bound = milliseconds if isinstance(milliseconds, (int, float)) else None
        if not isinstance(bound, (int, float)):
            if notes is not None:
                notes.append(
                    f"dispatch {dispatch_id}: input accepted; turn start has no Orca "
                    "dispatch bound, so it is unobserved but not an alert"
                )
            continue
        age = receipt_row[0]
        if age is None or age <= bound / 1000:
            continue
        findings.append(
            _finding(
                *WATCH_CHECK,
                f"dispatch {dispatch_id} has no observed turn start after {age:.0f}s "
                f"(turnStart={turn_start or 'missing'}; bound {bound / 1000:g}s from "
                f"{WATCH_BOUND_SOURCE})",
            )
        )
    return findings


def inspect_host(host: Host) -> Report:
    """Run every row and every dimension; a crashed row is a finding, never a stopped doctor."""
    report = Report()
    for row in ROWS:
        function = ROW_FUNCTIONS[row]
        try:
            found = function(host)
        except Exception as error:
            found = {
                check: [_finding(row, check, f"check crashed: {type(error).__name__}: {error}")]
                for check in CHECKS
            }
        for check in CHECKS:
            report.checked.append((row, check))
            for finding in found.get(check, []):
                report.add(finding)
    report.checked.append(WATCH_CHECK)
    try:
        report.findings.extend(check_watch(host, report.notes))
    except Exception as error:
        report.add(
            _finding(
                *WATCH_CHECK,
                f"check crashed: {type(error).__name__}: {error}",
            )
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--prefix", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    home = args.home.resolve()
    repo = args.repo.resolve()
    prefix = args.prefix or home / ".local" / "share" / "sextant-lane-runtimes"
    report = inspect_host(Host(home, repo, prefix))
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "checked": [f"{row}.{check}" for row, check in report.checked],
                    "notes": report.notes,
                    "findings": [
                        {
                            "code": finding.code,
                            "row": finding.row,
                            "check": finding.check,
                            "message": finding.message,
                        }
                        for finding in report.findings
                    ],
                },
                indent=2,
            )
        )
    else:
        for note in report.notes:
            print(f"note: {note}")
        for finding in report.findings:
            print(f"{finding.code}: {finding.message}")
        print(
            f"runtime doctor: {'OK' if report.ok else 'DRIFT'} "
            f"({len(report.findings)} finding(s) across {len(report.checked)} checks)"
        )
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""The all-runtime doctor's proof: a good fixture is green and every cell names its defect.

Each case builds a fixture home that stands in for the installed runtimes, injects one defect
into the surface that runtime actually reads, and asserts the exact row.check code.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REMOTE = "https://github.com/seathatflowsinourveins/sextant-next"
SLUG = "seathatflowsinourveins/sextant-next"
PLUGINS = [
    "superpowers@superpowers-dev",
    "compound-engineering@compound-engineering-plugin",
    "typesafe@typesafe-ai",
    "pyright-lsp@sextant-lsp",
    "typescript-lsp@sextant-lsp",
]
SHELF = ("writing-plans", "ce-compound", "typesafe-ai")
LIFECYCLE = "# Lifecycle sweep\n\nSweep the merged worktrees.\n"
REFLECTION = "# Verified reflection\n\nReflect on the session.\n"


@pytest.fixture(autouse=True)
def _isolate_dsh_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """The doctor honors DSH_HOME; each fixture supplies its own ~/.dsh."""
    monkeypatch.delenv("DSH_HOME", raising=False)


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_doctor(repo: Path):
    return _load(repo / "scripts" / "runtime_doctor.py", f"runtime_doctor_{id(repo)}")


class World:
    """The installed surfaces the fake command runner answers from."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.repo = tmp_path / "repo"
        self.prefix = self.home / ".local" / "share" / "sextant-lane-runtimes"
        self.muse_plugins = ["superpowers", "sextant-mcp"]
        self.versions = {
            "claude": "2.1.321",
            "dsh": "0.2.2-rc.1",
            "codex": "0.167.0",
            "agy": "1.4.6",
            "muse": "1.4.6-R6000.1",
            "omniroute": "3.8.53",
            "orca": "1.4.251",
            "ao": "0.14.10 commit 033d597032e4 built 2026-11-06T11:18:40Z",
        }
        self.dsh_dump = "\n".join(
            [
                "- id: agent-default-model",
                "  config:",
                "    provider: deepseek-official",
                "    model: deepseek-flash",
                "    reasoningEffort: max",
                "- id: llm-deepseek",
                "  config:",
                "    thinking: enabled",
                "    reasoningEffort: max",
                "- id: mcp-context7",
                "  config:",
                "    serverName: context7",
                "- id: mcp-exa",
                "- id: mcp-deepwiki",
                "- id: mcp-paper-search",
                "- id: sextant-hard-lines",
                "  name: >-",
                "    file:///fixture/sextant-dsh-hard-lines/hard-lines.mjs",
                "",
            ]
        )
        self.plugins = [
            {
                "id": plugin,
                "version": "1.0.0",
                "scope": "local",
                "enabled": True,
                "installPath": str(self.home / ".claude" / "plugins" / plugin.split("@")[0]),
                "installedAt": "2026-11-09T00:00:00Z",
                "projectPath": str(self.repo),
                "projectEnabled": True,
            }
            for plugin in PLUGINS
        ]
        for plugin in PLUGINS:
            (self.home / ".claude" / "plugins" / plugin.split("@")[0]).mkdir(
                parents=True, exist_ok=True
            )
        self.automations = [
            self._automation("Lifecycle sweep", LIFECYCLE, "lifecycle-precheck.sh", ""),
            self._automation(
                "Verified reflection",
                REFLECTION,
                "reflection-precheck.sh",
                "--model claude-fable-5-2 --effort high",
            ),
        ]
        self.agy_mcp = [
            ("context7", "enabled", "mcp-remote https://mcp.context7.com/mcp"),
            ("deepwiki", "enabled", "https://mcp.deepwiki.com/mcp"),
            ("exa", "enabled", "mcp-remote https://mcp.exa.ai/mcp"),
            ("paper-search", "enabled", "paper-search-mcp"),
            ("playwright", "disabled", "playwright-mcp"),
            ("codegraph", "disabled", "codegraph serve --mcp"),
        ]
        self.combo = {
            "combos": [
                {
                    "name": "sextant-gpt",
                    "models": [{"kind": "model", "model": "codex/gpt-6.1-sol-max"}],
                }
            ],
        }
        self.unit_working = str(self.repo)
        self.unit_exec = str(self.prefix / "router-start.sh")
        self.ao_state: str | None = "ready"
        self.ao_doctor = {"failures": 0}
        self.watch_turn_start = "observed"
        self.watch_timeout_ms = 60_000
        self.watch_provider = "claude"
        self.watch_observation = "supported"
        self.watch_stages = ["input_accepted"]
        self.watch_screen_confirm: str | None = None
        self.omni_due = 1
        self.bind = 'LISTEN 0 4096 127.0.0.1:22128 0.0.0.0:* users:(("omniroute",pid=1,fd=1))'
        self.build()

    def _automation(self, name: str, prompt: str, precheck: str, extra: str) -> dict:
        return {
            "name": name,
            "prompt": prompt,
            "precheck": {
                "command": f"bash {self.repo}/deploy/wsl/{precheck}",
                "timeoutSeconds": 120,
            },
            "extraAgentArgs": extra,
            "runContext": {"path": str(self.repo), "projectId": f"github:{SLUG}"},
            "sourceContext": {
                "providerIdentity": {"owner": "seathatflowsinourveins", "repo": "sextant-next"}
            },
            "projectId": "fixture-uuid",
        }

    def policy(self) -> dict:
        return {
            "gpt": {"model": "gpt-6.1-sol", "effort": "max"},
            "claude": {"model": "claude-opus-5-5", "effort": "high"},
            "claude_reflection": {"model": "claude-fable-5-2", "effort": "high"},
            "google": {"antigravity": "gemini-4-argon-high", "effort": "high"},
            "meta": {"model": "muse-wonder-full-1.0", "effort": "max", "contributor_mode": "off"},
        }

    def parity_spec(self) -> dict:
        return {
            "lock": ".claude/shelf.lock.json",
            "shelf": {
                "superpowers@superpowers-dev": {
                    "cache": "superpowers",
                    "skills": ["writing-plans"],
                },
                "compound-engineering@compound-engineering-plugin": {
                    "cache": "compound-engineering",
                    "skills": ["ce-compound"],
                },
                "typesafe@typesafe-ai": {"cache": "typesafe", "skills": ["typesafe-ai"]},
                "trading": {"root": ".claude/skills", "skills": "lock"},
            },
            "mcp": {
                "deepwiki": {"url": "https://mcp.deepwiki.com/mcp"},
                "context7": {
                    "url": "https://mcp.context7.com/mcp",
                    "key": "CONTEXT7_API_KEY",
                    "header": "Authorization",
                    "scheme": "Bearer",
                },
                "exa": {
                    "url": "https://mcp.exa.ai/mcp",
                    "key": "EXA_API_KEY",
                    "header": "x-api-key",
                },
                "paper-search": {"command": ".local/bin/paper-search-mcp"},
                "playwright": {
                    "command": ".local/share/sextant-agents/node_modules/.bin/playwright-mcp",
                    "args": ["--headless"],
                    "opt_in": True,
                },
                "codegraph": {
                    "command": ".local/share/sextant-agents/node_modules/.bin/codegraph",
                    "args": ["serve"],
                    "opt_in": True,
                },
            },
            "runtimes": {
                "codex": {"home": ".local/share/sextant-lane-runtimes/codex-home"},
                "dsh": {
                    "profiles": ["acp", "headless"],
                    "quality": {
                        "profiles": ["dsh-tui", "acp", "headless"],
                        "plugins": [
                            {
                                "package": "dsh-goalloop-agentteams",
                                "spec": "github:samirliu/dsh-goalloop-agentteams#6b4b1fad",
                            },
                            {"package": "sextant-dsh-review-cmd", "spec": "config/dsh/review-cmd"},
                        ],
                    },
                    "mcp_bundle": "config/dsh/mcp",
                },
                "muse": {"shelf_and_mcp": "blocked on issue #256; one user config root"},
            },
        }

    def build(self) -> None:
        repo, home, prefix = self.repo, self.home, self.prefix
        _write(repo / "scripts/runtime_doctor.py", (ROOT / "scripts/runtime_doctor.py").read_text())
        _write(
            repo / "deploy/wsl/lane-runtimes/parity.py",
            (ROOT / "deploy/wsl/lane-runtimes/parity.py").read_text(),
        )
        _write(
            repo / "deploy/wsl/lane-runtimes/parity.json", json.dumps(self.parity_spec(), indent=1)
        )
        _write(
            repo / ".claude/shelf.lock.json", json.dumps({"plugins": {}, "skills": {"files": {}}})
        )
        _write(repo / ".devcontainer/Dockerfile", "RUN claude install 2.1.318\n")
        _write(
            repo / ".devcontainer/agents/package.json",
            json.dumps({"dependencies": {"@openai/codex": "0.167.0"}}),
        )
        _write(repo / "deploy/wsl/lane-runtimes/model-policy.json", json.dumps(self.policy()))
        _write(
            repo / "deploy/wsl/lane-runtimes/routing.json",
            json.dumps(
                {
                    "base_url": "http://127.0.0.1:22128/v1",
                    "combo": "sextant-gpt",
                    "models": ["codex/gpt-6.1-sol-max"],
                }
            ),
        )
        _write(
            repo / "deploy/wsl/lane-runtimes/pins.json",
            json.dumps(
                {
                    "orca": {"tag": "v1.4.251"},
                    "runtimes": {"antigravity": {"version": "1.4.6"}},
                    "omniroute": {"version": "3.8.53"},
                    "muse": {"version": "1.4.6-R6000.1"},
                }
            ),
        )
        _write(repo / "scripts/omni_keys.py", "")
        _write(repo / "config/dsh/profile.lock.json", json.dumps({"engine": "0.2.2-rc.1"}))
        _write(
            repo / "config/dsh/hard-lines/package.json",
            json.dumps({"name": "sextant-dsh-hard-lines"}),
        )
        _write(repo / "config/dsh/mcp/package.json", json.dumps({"name": "sextant-dsh-mcp"}))
        _write(
            repo / "config/dsh/mcp/max-effort.cordis.yml",
            "\n".join(
                [
                    "- id: agent-default-model",
                    "  config:",
                    "    provider: deepseek-official",
                    "    model: deepseek-flash",
                    "    reasoningEffort: max",
                    "- id: llm-deepseek",
                    "  config:",
                    "    thinking: enabled",
                    "    reasoningEffort: max",
                    "",
                ]
            ),
        )
        _write(
            repo / ".codex/rules/default.rules",
            'prefix_rule(pattern=["git", "push"], decision="forbidden")\n',
        )
        _write(
            repo / "deploy/wsl/hard-lines/antigravity.json",
            json.dumps(
                {
                    "permissions": {"deny": [r"command(.*wsl\.exe.*)", r"write_file(.*/etc/.*)"]},
                }
            ),
        )
        deny = ["Bash(git push --force)", "Edit(//mnt/wsl/**)"]
        _write(
            repo / "deploy/wsl/hard-lines/claude-receipt.json",
            json.dumps(
                {
                    "deny_sha256": hashlib.sha256(json.dumps(deny).encode()).hexdigest(),
                    "permission_mode": "bypassPermissions",
                    "model": "claude-opus-5-5",
                    "effort": "high",
                }
            ),
        )
        _write(
            repo / ".claude/settings.json",
            json.dumps(
                {
                    "model": "claude-opus-5-5",
                    "effortLevel": "high",
                    "enabledPlugins": {plugin: True for plugin in PLUGINS},
                    "permissions": {"defaultMode": "bypassPermissions", "deny": deny},
                    "extraKnownMarketplaces": {},
                }
            ),
        )
        _write(repo / "deploy/wsl/ao.sh", (ROOT / "deploy/wsl/ao.sh").read_text())
        _write(repo / "deploy/wsl/lifecycle-prompt.md", LIFECYCLE)
        _write(repo / "deploy/wsl/reflection-prompt.md", REFLECTION)
        _write(repo / "deploy/wsl/lifecycle-precheck.sh", "exit 1\n", 0o755)
        _write(repo / "deploy/wsl/reflection-precheck.sh", "exit 1\n", 0o755)
        codex = (ROOT / "deploy/wsl/lane-runtimes/codex-launch.sh").read_text()
        muse = (
            "#!/bin/sh\n# --contributor-mode=on\n# *-contributor*\n"
            "# reasoning-effort\n# runtime_capabilities\n"
        )
        dsh = "#!/bin/sh\n"
        agy = '#!/bin/sh\n# AGY_CLI_DISABLE_AUTO_UPDATE=true\n# --model "$model"\n# --effort high\n'
        for name, text in (
            ("codex-launch.sh", codex),
            ("muse-launch.sh", muse),
            ("dsh-launch.sh", dsh),
            ("antigravity-launch.sh", agy),
        ):
            _write(repo / "deploy/wsl/lane-runtimes" / name, text, 0o755)
            _write(prefix / name, text, 0o755)
        _write(prefix / "model-policy.json", json.dumps(self.policy()))
        _write(
            prefix / "routing.json",
            json.dumps(
                {
                    "base_url": "http://127.0.0.1:22128/v1",
                    "combo": "sextant-gpt",
                    "models": ["codex/gpt-6.1-sol-max"],
                }
            ),
        )
        _write(prefix / "repository-path", str(repo))
        _write(prefix / "router-start.sh", "#!/bin/sh\n", 0o755)
        (prefix / "router/node_modules/.bin").mkdir(parents=True, exist_ok=True)
        _write(prefix / "router/node_modules/.bin/omniroute", "", 0o755)
        lane = prefix / "codex-home"
        lane.mkdir(parents=True, exist_ok=True)
        lane.chmod(0o700)
        parity = _load(repo / "deploy/wsl/lane-runtimes/parity.py", f"parity_{id(self)}")
        _write(lane / "config.toml", parity.codex_toml(home))
        _write(
            lane / "rules/sextant-hard-lines.rules",
            (repo / ".codex/rules/default.rules").read_text(),
        )
        for name in SHELF:
            _write(repo / ".claude/skills" / name / "SKILL.md", f"# {name}\n")
            _write(lane / "skills" / name / "SKILL.md", f"# {name}\n")
            _write(home / ".dsh/skills" / name / "SKILL.md", f"# {name}\n")

        for name, target in (
            ("claude", None),
            ("dsh", prefix / "dsh-launch.sh"),
            ("muse", prefix / "muse-launch.sh"),
            ("sextant-codex", prefix / "codex-launch.sh"),
            ("sextant-codex-review", prefix / "codex-launch.sh"),
            ("agy", prefix / "antigravity-launch.sh"),
        ):
            if target is not None:
                (home / ".local/bin").mkdir(parents=True, exist_ok=True)
                (home / ".local/bin" / name).symlink_to(target)
        _write(
            home / ".gemini/antigravity-cli/settings.json",
            json.dumps(
                {
                    "permissions": {"deny": [r"command(.*wsl\.exe.*)", r"write_file(.*/etc/.*)"]},
                    "trustedWorkspaces": [str(repo)],
                }
            ),
            0o600,
        )
        _write(
            home / ".config/muse/settings.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "reasoning_effort": "max",
                    "contributor_mode_enabled": False,
                    "contributor_mode_disclosure_acknowledged": True,
                }
            ),
        )
        for profile in ("acp", "headless", "dsh-tui"):
            deps = {
                "sextant-dsh-hard-lines": "link:../src/dsh/hard-lines",
                "dsh-goalloop-agentteams": "github:samirliu/dsh-goalloop-agentteams#6b4b1fad",
                "sextant-dsh-review-cmd": "link:../local/review-cmd",
            }
            bundles = [
                "sextant-dsh-hard-lines",
                "dsh-goalloop-agentteams",
                "sextant-dsh-review-cmd",
            ]
            if profile != "dsh-tui":
                deps["sextant-dsh-mcp"] = "link:../src/dsh/mcp"
                bundles.append("sextant-dsh-mcp")
            _write(
                home / ".dsh/profiles" / profile / "package.json",
                json.dumps(
                    {
                        "name": f"fixture-{profile}",
                        "private": True,
                        "dependencies": deps,
                        "dsh": {"profile": {"bundles": bundles}},
                    }
                ),
            )
        (home / ".ao/data").mkdir(parents=True, exist_ok=True)
        (home / ".ao/repos").mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(home / ".ao/data/ao.db")
        connection.execute(
            "create table projects (id text, path text, repo_origin_url text, display_name text, "
            "registered_at text, archived_at text, config text, kind text)"
        )
        connection.execute(
            "insert into projects values (?,?,?,?,?,?,?,?)",
            (
                "sextant",
                str(repo),
                REMOTE,
                "Sextant (AO fix-CI/review)",
                "",
                "",
                json.dumps(
                    {
                        "agentConfig": {"model": "claude-opus-5-5", "effort": "high"},
                        "worker": {"agent": "claude-code"},
                    }
                ),
                "single_repo",
            ),
        )
        connection.commit()
        connection.close()
        (home / ".config/orca").mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(home / ".config/orca/orchestration.db")
        connection.execute(
            "create table worker_dispatches (dispatch_id text primary key, state text, stage text, "
            "start_options text, created_at text, updated_at text)"
        )
        connection.execute(
            "create table mutation_receipts (caller_fingerprint text, request_id text, "
            "method text, payload_hash text, state text, receipt text, created_at text, "
            "updated_at text, "
            "primary key (caller_fingerprint, "
            "request_id))"
        )
        started = "2026-11-01 00:00:00"
        connection.execute(
            "insert into worker_dispatches values (?,?,?,?,?,?)",
            (
                "ctx_fixture",
                "ready",
                "input_accepted",
                json.dumps({"timeoutMs": 60_000}),
                started,
                started,
            ),
        )
        receipt = {
            "state": "ready",
            "runId": "run_fixture",
            "taskId": "task_fixture",
            "dispatchId": "ctx_fixture",
            "stage": "input_accepted",
            "turnStart": self.watch_turn_start,
            "timeoutMs": self.watch_timeout_ms,
            "prompt": {
                "stages": list(self.watch_stages),
                "provider": self.watch_provider,
                "observation": self.watch_observation,
            },
        }
        if self.watch_screen_confirm is not None:
            receipt["screenConfirm"] = self.watch_screen_confirm
        connection.execute(
            "insert into mutation_receipts values (?,?,?,?,?,?,?,?)",
            (
                "fixture",
                "request_fixture",
                "orchestration.workerStart",
                "",
                "completed",
                json.dumps(receipt),
                started,
                started,
            ),
        )
        connection.commit()
        connection.close()

    def set_watch_turn_start(self, value: str) -> None:
        path = self.home / ".config/orca/orchestration.db"
        connection = sqlite3.connect(path)
        row = connection.execute(
            "select caller_fingerprint, request_id, receipt from mutation_receipts "
            "where method = 'orchestration.workerStart'"
        ).fetchone()
        receipt = json.loads(row[2])
        receipt["turnStart"] = value
        connection.execute(
            "update mutation_receipts set receipt = ? "
            "where caller_fingerprint = ? and request_id = ?",
            (json.dumps(receipt), row[0], row[1]),
        )
        connection.commit()
        connection.close()

    def set_watch_unobservable(self) -> None:
        path = self.home / ".config/orca/orchestration.db"
        connection = sqlite3.connect(path)
        row = connection.execute(
            "select caller_fingerprint, request_id, receipt from mutation_receipts "
            "where method = 'orchestration.workerStart'"
        ).fetchone()
        receipt = json.loads(row[2])
        receipt["turnStart"] = "unsupported"
        receipt["prompt"] = {
            "stages": ["input_accepted"],
            "provider": "unsupported",
            "observation": "unsupported",
        }
        if self.watch_screen_confirm is not None:
            receipt["screenConfirm"] = self.watch_screen_confirm
        connection.execute(
            "update mutation_receipts set receipt = ? "
            "where caller_fingerprint = ? and request_id = ?",
            (json.dumps(receipt), row[0], row[1]),
        )
        connection.commit()
        connection.close()

    def remove_worker_start_receipt(self) -> None:
        path = self.home / ".config/orca/orchestration.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "delete from mutation_receipts where method = 'orchestration.workerStart'"
        )
        connection.commit()
        connection.close()


class Fake:
    """Answer the native probes from the fixture surface, not from this host."""

    def __init__(self, world: World):
        self.w = world
        self.Result = _load_doctor(world.repo).Result
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, command, **kwargs):
        cmd = [str(part) for part in command]
        self.calls.append(cmd)
        self.kwargs.append(kwargs)
        w = self.w
        text = " ".join(cmd)

        def ok(out: str = "", code: int = 0):
            return self.Result(code, out, "")

        if cmd[:3] == ["git", "-C", str(w.repo)] and cmd[3:] == ["remote", "get-url", "origin"]:
            return ok(REMOTE + "\n")
        if cmd[:3] == ["git", "-C", str(w.repo)] and cmd[3:] == ["worktree", "list", "--porcelain"]:
            return ok(f"worktree {w.repo}\n")
        if cmd[:2] == ["git", "-C"]:
            return ok("", 1)
        if cmd == ["claude", "--version"]:
            return ok(f"{w.versions['claude']} (Claude Code)\n")
        if cmd == ["claude", "plugin", "list", "--json"]:
            return ok(json.dumps(w.plugins))
        if cmd == ["dsh", "--version"]:
            return ok(w.versions["dsh"])
        if cmd[:2] == ["dsh", "--profile"] and cmd[-1] == "--dump-config":
            return ok(w.dsh_dump)
        if cmd == ["codex", "--version"]:
            return ok(f"codex-cli {w.versions['codex']}")
        if cmd == ["agy", "--version"]:
            return ok(w.versions["agy"])
        if cmd == ["agy", "models"]:
            return ok("gemini-4-argon-high\n")
        if cmd == ["agy", "plugin", "list", "--json"]:
            superpowers = ["writing-plans"]
            shelf = [name for name in SHELF if name not in superpowers]
            return ok(
                json.dumps(
                    [
                        {
                            "name": "sextant-shelf",
                            "enabled": True,
                            "version": "1.0.0",
                            "skills": shelf,
                        },
                        {
                            "name": "superpowers",
                            "enabled": True,
                            "version": "7.0.2",
                            "skills": superpowers,
                        },
                    ]
                )
            )
        if cmd == ["agy", "mcp", "list"]:
            rows = ["NAME TYPE STATUS COMMAND/URL"]
            rows += [f"{name} stdio {status} {command}" for name, status, command in w.agy_mcp]
            return ok("\n".join(rows) + "\n")
        if cmd == ["muse", "--version"]:
            return ok(f"Muse Code 1.4.6 ({w.versions['muse']})")
        if cmd[:3] == ["muse", "model-profile", "show"]:
            return ok("model muse-wonder-full-1.0\neffort max\n")
        if cmd == ["muse", "plugins", "list", "--json"]:
            spec = w.parity_spec()
            capabilities = {
                "superpowers": {
                    "skills": [
                        {"id": name}
                        for name in spec["shelf"]["superpowers@superpowers-dev"]["skills"]
                    ],
                },
                "sextant-mcp": {"mcp_servers": [{"id": name} for name in spec["mcp"]]},
            }
            return ok(
                json.dumps(
                    {
                        "plugins": [
                            {
                                "active": True,
                                "valid": True,
                                "plugin": {"id": name, "capabilities": capabilities[name]},
                            }
                            for name in w.muse_plugins
                        ]
                    }
                )
            )
        if cmd == ["muse", "skills", "list", "--source", "user", "--json"]:
            parity = w.parity_spec()["shelf"]["superpowers@superpowers-dev"]["skills"]
            shelf = set(
                _load(w.repo / "deploy/wsl/lane-runtimes/parity.py", "muse_shelf").shelf_names()
            )
            return ok(
                json.dumps({"skills": [{"name": name} for name in sorted(shelf - set(parity))]})
            )
        if cmd[0].endswith("omniroute") and cmd[-1] == "--version":
            return ok(w.versions["omniroute"])
        if cmd[0].endswith("omniroute") and "combos" in cmd:
            return ok(json.dumps(w.combo))
        if cmd == ["systemctl", "--user", "is-active", "omniroute.service"]:
            return ok("active\n")
        if cmd[:3] == ["systemctl", "--user", "show"] and cmd[-1] == "--value":
            return ok(w.unit_working + "\n")
        if cmd[:3] == ["systemctl", "--user", "show"]:
            return ok(
                f"ExecStart={{{w.unit_exec}}}\nWorkingDirectory={w.unit_working}\nEnvironmentFiles=\n"
            )
        if cmd[:3] == ["python3", "-I", str(w.repo / "scripts/omni_keys.py")]:
            return ok("", w.omni_due)
        if cmd == ["ss", "-ltnp"]:
            return ok(w.bind + "\n")
        if cmd == ["ao", "version"]:
            return ok(w.versions["ao"])
        if cmd == ["ao", "status", "--json"]:
            return ok(json.dumps({} if w.ao_state is None else {"state": w.ao_state}))
        if cmd == ["ao", "doctor", "--json"]:
            return ok(json.dumps(w.ao_doctor))
        if cmd == ["orca-ide", "--version"]:
            return ok(w.versions["orca"])
        if cmd == ["orca-ide", "automations", "list", "--json"]:
            return ok(json.dumps({"ok": True, "result": {"automations": w.automations}}))
        raise AssertionError(f"unexpected command: {text}")


def inspect(world: World):
    doctor = _load_doctor(world.repo)
    return doctor.inspect_host(doctor.Host(world.home, world.repo, world.prefix, Fake(world)))


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_good_fixture_is_green(tmp_path):
    world = World(tmp_path)
    report = inspect(world)
    assert report.findings == [], [f"{f.code}: {f.message}" for f in report.findings]
    assert len(report.checked) == 41


def test_antigravity_trusts_this_repository_wherever_it_lives_and_names_a_removed_path(tmp_path):
    """An existing checkout of this repository is trusted wherever it lives (the trading lead's own
    working copy, AO's separate clone); a path that no longer exists is what the installer's prune
    removes; an existing path that is not a checkout of this repository stays a finding."""
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)
    own = tmp_path / "own-clone"
    own.mkdir()
    foreign = tmp_path / "archive-clone"
    foreign.mkdir()
    plain = tmp_path / "plain-directory"
    plain.mkdir()
    fake = Fake(world)

    def runner(command, **kwargs):
        cmd = [str(part) for part in command]
        for candidate, origin in (
            (own, REMOTE),
            (foreign, "https://github.com/seathatflowsinourveins/sextant-archive.git"),
        ):
            if cmd[:3] == ["git", "-C", str(candidate)]:
                if cmd[3:] == ["rev-parse", "--show-toplevel"]:
                    return doctor.Result(0, f"{candidate}\n", "")
                if cmd[3:] == ["remote", "get-url", "origin"]:
                    return doctor.Result(0, origin + "\n", "")
        return fake(command, **kwargs)

    host = doctor.Host(world.home, world.repo, world.prefix, runner)

    def repository_findings(values):
        _set_agy(world, trustedWorkspaces=values)
        found = doctor.check_antigravity(host)
        return [
            finding for row in found.values() for finding in row if finding.check == "repository"
        ]

    assert repository_findings([str(world.repo), str(own)]) == []
    missing = repository_findings([str(world.repo), "/srv/another-checkout"])
    assert len(missing) == 1 and "no longer exist" in missing[0].message
    assert "/srv/another-checkout" in missing[0].message
    assert len(repository_findings([str(world.repo), str(plain)])) == 1
    assert len(repository_findings([str(world.repo), str(foreign)])) == 1


def test_watch_skips_an_unobservable_provider_and_reports_it(tmp_path):
    world = World(tmp_path)
    world.watch_screen_confirm = "running"
    world.set_watch_unobservable()
    report = inspect(world)
    assert "watch.turn_started" not in codes(report)
    note = next(note for note in report.notes if "ctx_fixture" in note)
    assert "unobservable" in note
    assert "running" in note


def test_watch_alerts_when_an_observable_dispatch_has_not_started(tmp_path):
    world = World(tmp_path)
    world.set_watch_turn_start("unobserved")
    report = inspect(world)
    assert "watch.turn_started" in codes(report)
    message = next(f.message for f in report.findings if f.code == "watch.turn_started")
    assert "ctx_fixture" in message
    assert "60" in message


def test_watch_skips_a_dispatch_with_no_start_receipt(tmp_path):
    world = World(tmp_path)
    world.remove_worker_start_receipt()
    report = inspect(world)
    assert "watch.turn_started" not in codes(report)


def test_historical_plugin_records_for_other_checkouts_are_not_drift(tmp_path):
    world = World(tmp_path)
    world.plugins.append(
        {
            "id": "old@archive",
            "version": "1.0.0",
            "scope": "local",
            "enabled": True,
            "installPath": str(world.home / ".claude" / "plugins" / "old"),
            "installedAt": "2026-11-09T00:00:00Z",
            "projectPath": "/home/sextant/sextant",
            "projectEnabled": True,
        }
    )
    report = inspect(world)
    assert "claude.repository" not in codes(report)
    assert "claude.parity" not in codes(report)


def test_main_checkout_is_the_first_worktree(tmp_path):
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)

    class MainOnly:
        def __call__(self, command, **kwargs):
            del command, kwargs
            return doctor.Result(0, f"worktree {world.repo}\n", "")

    host = doctor.Host(world.home, tmp_path / "clone", world.prefix, MainOnly())
    assert doctor._main_checkout(host) == world.repo
    assert doctor._current_repository(host, str(world.repo / ".claude"))
    assert not doctor._current_repository(host, "/srv/old-sextant")


def test_router_reply_is_read_after_a_bracketed_banner(tmp_path):
    doctor = _load_doctor(ROOT)
    banner = "[dotenv@17.2.1] injecting env (0) from .env -- tip: set override\n"
    reply = {"combos": [{"id": "sextant-gpt", "models": ["codex/gpt-6.1-sol-max"]}]}
    assert doctor._json_text(banner + json.dumps(reply, indent=2)) == reply


def test_main_checkout_survives_an_ao_clone(tmp_path):
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)
    clone = tmp_path / "ao-clone"
    clone.mkdir()

    class CloneRunner:
        def __call__(self, command, **kwargs):
            del kwargs
            if command[:2] == ["git", "-C"] and "remote" in command:
                return doctor.Result(0, REMOTE + "\n", "")
            if "worktree" in command:
                if command[2] == str(world.repo):
                    return doctor.Result(0, f"worktree {world.repo}\n", "")
                return doctor.Result(0, f"worktree {clone}\n", "")
            return doctor.Result(1, "", "")

    host = doctor.Host(world.home, clone, world.prefix, CloneRunner())
    assert doctor._main_checkout(host) == world.repo


def test_a_linked_worktree_is_not_the_permanent_checkout(tmp_path):
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)
    linked = tmp_path / "linked-worktree"
    linked.mkdir()
    (world.prefix / "repository-path").write_text(str(linked))
    fake = Fake(world)

    def runner(command, **kwargs):
        cmd = [str(part) for part in command]
        if cmd[:3] == ["git", "-C", str(linked)] and "worktree" in command:
            return doctor.Result(0, f"worktree {world.repo}\nworktree {linked}\n", "")
        return fake(command, **kwargs)

    host = doctor.Host(world.home, linked, world.prefix, runner)
    assert doctor._main_checkout(host) == world.repo
    assert not doctor._current_repository(host, str(linked))


def test_claude_requires_the_fable_floor(tmp_path):
    world = World(tmp_path)
    world.versions["claude"] = "2.1.320"
    report = inspect(world)
    assert "claude.version" in codes(report)
    message = next(f.message for f in report.findings if f.code == "claude.version")
    assert "2.1.321" in message


def test_claude_project_effort_matches_the_policy(tmp_path):
    world = World(tmp_path)
    report = inspect(world)
    assert "claude.model_effort" not in codes(report), [
        f.message for f in report.findings if f.code == "claude.model_effort"
    ]


def test_claude_project_effort_mismatch_fails(tmp_path):
    world = World(tmp_path)
    _set_settings(world, effortLevel="max")
    report = inspect(world)
    assert "claude.model_effort" in codes(report)


def test_claude_env_effort_pin_is_a_finding(tmp_path):
    world = World(tmp_path)
    _set_settings(world, env={"CLAUDE_CODE_EFFORT_LEVEL": "high"})
    report = inspect(world)
    assert "claude.model_effort" in codes(report)


def test_dsh_compares_the_provider_effort(tmp_path):
    world = World(tmp_path)
    world.dsh_dump = world.dsh_dump.replace(
        "    thinking: enabled\n    reasoningEffort: max",
        "    thinking: enabled\n    reasoningEffort: high",
    )
    report = inspect(world)
    assert "dsh.model_effort" in codes(report)


def test_dsh_probes_the_home_whose_manifests_it_reads(tmp_path):
    world = World(tmp_path)
    _write(world.home / ".dsh-full/profiles/acp/package.json", "{}")
    doctor = _load_doctor(world.repo)
    fake = Fake(world)
    report = doctor.inspect_host(doctor.Host(world.home, world.repo, world.prefix, fake))
    assert "dsh.parity" not in codes(report), [
        f.message for f in report.findings if f.code == "dsh.parity"
    ]
    probes = [
        (call, kwargs)
        for call, kwargs in zip(fake.calls, fake.kwargs, strict=True)
        if call[:2] == ["dsh", "--profile"] and call[-1] == "--dump-config"
    ]
    expected = {"DSH_HOME": str(world.home / ".dsh")}
    assert probes and all(kwargs.get("env") == expected for _, kwargs in probes)


def test_renewal_checks_only_retained_router_runtimes(tmp_path):
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)
    fake = Fake(world)
    doctor.check_omniroute(doctor.Host(world.home, world.repo, world.prefix, fake))
    due = [
        call
        for call in fake.calls
        if call[:3] == ["python3", "-I", str(world.repo / "scripts" / "omni_keys.py")]
    ]
    assert due and due[0][-2:] == ["due", "codex"], due


def test_ao_parity_accepts_the_pins_ready_state(tmp_path):
    world = World(tmp_path)
    report = inspect(world)
    assert "ao.parity" not in codes(report), [
        f.message for f in report.findings if f.code == "ao.parity"
    ]


@pytest.mark.parametrize("state", ["stopped", "stale", "unhealthy", "not_ready"])
def test_ao_parity_names_every_state_other_than_ready(state, tmp_path):
    world = World(tmp_path)
    world.ao_state = state
    report = inspect(world)
    message = next(f.message for f in report.findings if f.code == "ao.parity")
    assert state in message


def test_ao_parity_names_a_missing_state(tmp_path):
    world = World(tmp_path)
    world.ao_state = None
    report = inspect(world)
    message = next(f.message for f in report.findings if f.code == "ao.parity")
    assert "unknown" in message


def test_ao_guard_reads_the_tracked_parameterized_script(tmp_path):
    world = World(tmp_path)
    report = inspect(world)
    assert "ao.guard" not in codes(report), [
        f.message for f in report.findings if f.code == "ao.guard"
    ]


def test_codex_launcher_wires_the_pool_and_effort_from_its_recipe(tmp_path):
    world = World(tmp_path)
    report = inspect(world)
    assert "codex.model_effort" not in codes(report), [
        f.message for f in report.findings if f.code == "codex.model_effort"
    ]


def _set_settings(world: World, **changes) -> None:
    path = world.repo / ".claude/settings.json"
    settings = json.loads(path.read_text())
    settings.update(changes)
    path.write_text(json.dumps(settings))


def _set_muse(world: World, **changes) -> None:
    path = world.home / ".config/muse/settings.json"
    settings = json.loads(path.read_text())
    settings.update(changes)
    path.write_text(json.dumps(settings))


def _set_agy(world: World, **changes) -> None:
    path = world.home / ".gemini/antigravity-cli/settings.json"
    settings = json.loads(path.read_text())
    settings.update(changes)
    path.write_text(json.dumps(settings))


def _set_repository(world: World, value: str) -> None:
    (world.prefix / "repository-path").write_text(value)


def _set_dsh_profile(world: World, profile: str, change) -> None:
    path = world.home / ".dsh/profiles" / profile / "package.json"
    package = json.loads(path.read_text())
    change(package)
    path.write_text(json.dumps(package))


DEFECTS = [
    ("claude.version", lambda w: w.versions.__setitem__("claude", "2.0.0")),
    ("claude.model_effort", lambda w: _set_settings(w, model="claude-wrong")),
    (
        "claude.parity",
        lambda w: _set_settings(
            w,
            enabledPlugins={
                "superpowers@superpowers-dev": True,
                "compound-engineering@compound-engineering-plugin": True,
                "pyright-lsp@sextant-lsp": True,
                "typescript-lsp@sextant-lsp": True,
            },
        ),
    ),
    (
        "claude.guard",
        lambda w: _set_settings(
            w, permissions={"defaultMode": "bypassPermissions", "deny": ["Bash(rm)"]}
        ),
    ),
    (
        "claude.repository",
        lambda w: w.automations[0]["runContext"].__setitem__("path", "/srv/old-sextant"),
    ),
    ("dsh.version", lambda w: w.versions.__setitem__("dsh", "0.2.1")),
    (
        "dsh.model_effort",
        lambda w: setattr(
            w, "dsh_dump", w.dsh_dump.replace("model: deepseek-flash", "model: deepseek-other")
        ),
    ),
    (
        "dsh.parity",
        lambda w: _set_dsh_profile(
            w, "acp", lambda package: package["dependencies"].pop("sextant-dsh-mcp")
        ),
    ),
    (
        "dsh.guard",
        lambda w: setattr(
            w, "dsh_dump", w.dsh_dump.replace("- id: sextant-hard-lines", "- id: not-the-guard")
        ),
    ),
    ("dsh.repository", lambda w: _set_repository(w, "/srv/old-sextant")),
    ("codex.version", lambda w: w.versions.__setitem__("codex", "0.166.0")),
    (
        "codex.model_effort",
        lambda w: (w.repo / "deploy/wsl/lane-runtimes/routing.json").write_text(
            json.dumps({"models": ["codex/other"]})
        ),
    ),
    ("codex.parity", lambda w: (w.prefix / "codex-home/config.toml").write_text("[otel]\n")),
    ("codex.guard", lambda w: (w.prefix / "codex-home/rules/sextant-hard-lines.rules").unlink()),
    ("codex.repository", lambda w: _set_repository(w, "/srv/old-sextant")),
    ("antigravity.version", lambda w: w.versions.__setitem__("agy", "1.4.5")),
    (
        "antigravity.model_effort",
        lambda w: (w.prefix / "antigravity-launch.sh").write_text("#!/bin/sh\n"),
    ),
    ("antigravity.parity", lambda w: w.agy_mcp.pop(3)),
    ("antigravity.guard", lambda w: _set_agy(w, permissions={"deny": [r"command(.*wsl\.exe.*)"]})),
    ("antigravity.repository", lambda w: _set_agy(w, trustedWorkspaces=["/srv/old-sextant"])),
    ("muse.version", lambda w: w.versions.__setitem__("muse", "1.4.5")),
    ("muse.model_effort", lambda w: _set_muse(w, reasoning_effort="low")),
    ("muse.parity", lambda w: w.muse_plugins.remove("sextant-mcp")),
    ("muse.guard", lambda w: (w.prefix / "muse-launch.sh").write_text("#!/bin/sh\n")),
    ("muse.repository", lambda w: _set_repository(w, "/srv/old-sextant")),
    ("omniroute.version", lambda w: w.versions.__setitem__("omniroute", "3.8.52")),
    (
        "omniroute.model_effort",
        lambda w: w.combo["combos"][0].__setitem__(
            "models", [{"kind": "model", "model": "codex/other"}]
        ),
    ),
    ("omniroute.parity", lambda w: setattr(w, "unit_exec", str(w.repo / "router-start.sh"))),
    (
        "omniroute.guard",
        lambda w: setattr(
            w, "bind", 'LISTEN 0 4096 0.0.0.0:22128 0.0.0.0:* users:(("omniroute",pid=1,fd=1))'
        ),
    ),
    ("omniroute.repository", lambda w: setattr(w, "unit_working", "/srv/old-sextant")),
    ("orca.version", lambda w: w.versions.__setitem__("orca", "1.4.250")),
    (
        "orca.model_effort",
        lambda w: w.automations[1].__setitem__(
            "extraAgentArgs", "--model claude-opus-5-5 --effort max"
        ),
    ),
    ("orca.parity", lambda w: w.automations[0].__setitem__("prompt", "old prompt")),
    (
        "orca.guard",
        lambda w: w.automations[0].__setitem__(
            "precheck", {"command": "bash /bin/true", "timeoutSeconds": 1}
        ),
    ),
    (
        "orca.repository",
        lambda w: w.automations[0]["runContext"].__setitem__("path", "/srv/old-sextant"),
    ),
    ("ao.version", lambda w: w.versions.__setitem__("ao", "0.14.9")),
    ("ao.model_effort", lambda w: _set_ao(w, model="claude-wrong")),
    ("ao.parity", lambda w: setattr(w, "ao_state", "stopped")),
    ("ao.guard", lambda w: (w.repo / "deploy/wsl/ao.sh").write_text("pin_version=0.14.10\n")),
    ("ao.repository", lambda w: _set_ao(w, path="/srv/old-sextant")),
]


def _set_ao(world: World, **changes) -> None:
    connection = sqlite3.connect(world.home / ".ao/data/ao.db")
    config = json.loads(connection.execute("select config from projects").fetchone()[0])
    if "model" in changes:
        config["agentConfig"]["model"] = changes["model"]
    path = changes.get("path", str(world.repo))
    connection.execute("update projects set path = ?, config = ?", (path, json.dumps(config)))
    connection.commit()
    connection.close()


@pytest.mark.parametrize("code,mutate", DEFECTS, ids=[code for code, _ in DEFECTS])
def test_one_defect_per_cell_is_named(code, mutate, tmp_path):
    world = World(tmp_path)
    mutate(world)
    report = inspect(world)
    assert code in codes(report), [
        f"{finding.code}: {finding.message}" for finding in report.findings
    ]


def test_session_start_runs_the_doctor_between_the_other_two_checks() -> None:
    justfile = (ROOT / "justfile").read_text()
    start = justfile.split("session-start:", 1)[1].split("\n\n", 1)[0]
    assert (
        start.index("dsh_profile_doctor.py")
        < start.index("runtime_doctor.py")
        < start.index("ecosystem_index.py")
    )


def test_cli_prints_json_and_exits_two_on_drift(tmp_path, capsys, monkeypatch) -> None:
    world = World(tmp_path)
    doctor = _load_doctor(world.repo)

    green = doctor.Report()
    green.checked = [(row, check) for row in doctor.ROWS for check in doctor.CHECKS]
    green.checked.append(doctor.WATCH_CHECK)
    monkeypatch.setattr(doctor, "inspect_host", lambda host: green)
    assert doctor.main(["--home", str(world.home), "--repo", str(world.repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert len(payload["checked"]) == 41
    assert payload["findings"] == []

    green.add(doctor.Finding("codex", "guard", "the lane rules are missing"))
    assert doctor.main(["--home", str(world.home), "--repo", str(world.repo), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "codex.guard"

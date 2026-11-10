"""Proof: compaction keeps the session's own context without a stale summary.

Source: code.claude.com/docs/en/hooks-guide.md, "Re-inject context after
compaction"; code.claude.com/docs/en/hooks.md, SessionStart and PreCompact;
code.claude.com/docs/en/context-window.md, "What survives compaction". All
read 2026-11-09. Authority: LEAD-2228 section N1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "compact_context.py"
CAP = 10_000
TS = 1_700_000_000
SENTINEL = "STATE-CONTENT-MUST-NOT-BE-PRINTED"

ROLES = ("lead", "dispatcher", "lander", "tracker", "worker")
ROLE_FILES = {
    "lead": Path("sextant-data/handoffs/LEAD-STATE.md"),
    "dispatcher": Path("sextant-data/roster-ops/claude-successor/STATE-2206-roster-ops.md"),
    "lander": Path("sextant-data/landing/STATE-2211-landing.md"),
    "tracker": Path("sextant-data/handoffs/practice-tracker/STATE-2236.md"),
}


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    for rel in ROLE_FILES.values():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SENTINEL + "\n")
        os.utime(path, (TS, TS))
    return home


def _run(*args: str, home: Path, stdin: str = "") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _pointer(role: str) -> str:
    return "~/" + str(ROLE_FILES[role])


def _mtime() -> str:
    return datetime.fromtimestamp(TS).astimezone().strftime("%Y-%m-%d %H:%M")


def test_claude_md_keeps_the_shared_compact_instructions_to_eight_lines() -> None:
    text = (ROOT / "CLAUDE.md").read_text()
    marker = "# Compact instructions"
    assert marker in text
    section = text.split(marker, 1)[1].split("\n# ", 1)[0]
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    assert 0 < len(lines) <= 8, lines
    joined = " ".join(lines).lower()
    for phrase in (
        "owner's words",
        "role",
        "state-file",
        "peer",
        "open tasks",
        "waits on the owner",
        "sha-256",
        "tool output",
        "fetched pages",
        "finished work",
    ):
        assert phrase in joined, phrase


def test_settings_declare_the_two_documented_compaction_hooks() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    hooks = settings["hooks"]
    assert set(hooks) == {"SessionStart", "PreCompact"}

    (start,) = hooks["SessionStart"]
    assert start["matcher"] == "compact"
    (start_hook,) = start["hooks"]
    assert start_hook["type"] == "command"
    assert "scripts/compact_context.py" in start_hook["command"]
    assert "session-start" in start_hook["command"]
    assert start_hook["command"].rstrip().endswith("|| true")

    (pre,) = hooks["PreCompact"]
    assert "matcher" not in pre
    (pre_hook,) = pre["hooks"]
    assert pre_hook["type"] == "command"
    assert "scripts/compact_context.py" in pre_hook["command"]
    assert "pre-compact" in pre_hook["command"]
    assert pre_hook["command"].rstrip().endswith("|| true")


def test_each_role_gets_a_pointer_and_its_modification_time(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for role in ("lead", "dispatcher", "lander", "tracker"):
        out = _run("session-start", "--role", role, home=home)
        assert out.returncode == 0, out.stderr
        assert out.stdout.count("Reminder:") == 1
        assert role in out.stdout
        assert _pointer(role) in out.stdout
        assert _mtime() in out.stdout
        assert SENTINEL not in out.stdout


def test_worker_names_no_state_file(tmp_path: Path) -> None:
    out = _run("session-start", "--role", "worker", home=_home(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "no state file" in out.stdout.lower()
    assert "LEAD-STATE.md" not in out.stdout


def test_hook_input_agent_type_selects_the_role(tmp_path: Path) -> None:
    home = _home(tmp_path)
    stdin = json.dumps(
        {"hook_event_name": "SessionStart", "source": "compact", "agent_type": "tracker"}
    )
    out = _run("session-start", home=home, stdin=stdin)
    assert out.returncode == 0, out.stderr
    assert _pointer("tracker") in out.stdout
    assert "LEAD-STATE.md" not in out.stdout


def test_unknown_role_lists_every_known_role(tmp_path: Path) -> None:
    home = _home(tmp_path)
    out = _run("session-start", home=home, stdin="{}")
    assert out.returncode == 0, out.stderr
    for role in ("lead", "dispatcher", "lander", "tracker"):
        assert _pointer(role) in out.stdout
    assert "worker" in out.stdout
    assert len(out.stdout) < CAP


def test_pre_compact_prints_the_roles_extra_keep_lines_under_the_cap(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for role in ROLES:
        out = _run("pre-compact", "--role", role, home=home)
        assert out.returncode == 0, out.stderr
        assert 0 < len(out.stdout) < CAP
        assert role in out.stdout.lower()
    out = _run("pre-compact", home=home, stdin="{}")
    assert out.returncode == 0, out.stderr
    assert 0 < len(out.stdout) < CAP
    for role in ROLES:
        assert role in out.stdout.lower()


def test_hook_output_never_carries_state_file_contents(tmp_path: Path) -> None:
    home = _home(tmp_path)
    outputs = [_run("session-start", home=home, stdin="{}").stdout]
    outputs += [_run("session-start", "--role", role, home=home).stdout for role in ROLES]
    outputs += [_run("pre-compact", "--role", role, home=home).stdout for role in ROLES]
    assert all(text.strip() for text in outputs)
    assert all(SENTINEL not in text for text in outputs)


def test_hook_modes_exit_zero_on_bad_input_and_an_empty_home(tmp_path: Path) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    for mode in ("session-start", "pre-compact"):
        out = _run(mode, home=home, stdin="not json")
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip()
        assert "Traceback" not in out.stderr


def test_script_has_no_network_repository_or_subprocess_call() -> None:
    source = SCRIPT.read_text()
    for forbidden in (
        "import subprocess",
        "import socket",
        "import urllib",
        "import requests",
        "os.system",
        "os.environ",
        "os.getenv",
    ):
        assert forbidden not in source, forbidden
    assert "git " not in source


def test_check_passes_and_names_its_checks(tmp_path: Path) -> None:
    out = _run("--check", home=_home(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Compact instructions" in out.stdout
    assert "SessionStart" in out.stdout
    assert "PreCompact" in out.stdout


def test_just_session_start_runs_the_compact_check() -> None:
    lines = (ROOT / "justfile").read_text().splitlines()
    start = lines.index("session-start:")
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith((" ", "\t")):
            recipe.append(line.strip())
        elif line.strip():
            break
    assert any(line.endswith("scripts/compact_context.py --check") for line in recipe), recipe


def test_manifest_and_adr_record_the_decision() -> None:
    manifest = (ROOT / "docs/manifest.md").read_text()
    assert "| Compaction is native |" in manifest
    assert "2026-11-09" in manifest
    adr = (ROOT / "docs/adr/0022-memory-rag-and-enhanced-dsh.md").read_text()
    assert "Amended 2026-11-09" in adr
    assert "compact" in adr.lower()


def test_the_shelf_note_records_the_project_hooks() -> None:
    note = (ROOT / "docs/research/2026-11-06-claude-shelf.md").read_text()
    assert "Amended 2026-11-09" in note
    assert "compact_context.py" in note

"""The session-start contract: the lock, the drift doctor and the gate recipe agree."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
DOCTOR = ROOT / "scripts" / "dsh_profile_doctor.py"
LOCK = ROOT / "config" / "dsh" / "profile.lock.json"
GATE = ROOT / ".github" / "gate" / "dsh-profile.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _write_link(root: Path, rel: str, name: str) -> Path:
    target = root / rel
    target.mkdir(parents=True)
    (target / "package.json").write_text(
        json.dumps({"name": name, "version": "0.0.0"}) + "\n", encoding="utf-8"
    )
    (target / "patch.yml").write_text("id: fixture\n", encoding="utf-8")
    return target


def _gate(lock: dict[str, Any]) -> dict[str, Any]:
    bundles = []
    for entry in lock["headless"]["bundles"]:
        spec = entry["spec"]
        bundles.append(
            {"package": entry["package"], "spec": spec[5:] if spec.startswith("link:") else spec}
        )
    return {
        "lock": lock["lock"],
        "source": lock["source"],
        "engine": lock["engine"],
        "engine_authority": lock["engine_authority"],
        "pnpm": lock["pnpm"],
        "bundles": bundles,
        "github_plugin": lock["headless"]["github_plugin"],
    }


def _fixture(
    tmp_path: Path, *, with_link: bool = False, relative_link: bool = False
) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    dependencies: list[dict[str, Any]] = [{"package": "pkg-a", "spec": "1.0.0"}]
    bundles = ["pkg-a"]
    headless: list[dict[str, Any]] = [{"package": "pkg-a", "spec": "pkg-a@1.0.0"}]
    live_dependencies = {"pkg-a": "1.0.0"}
    if with_link:
        _write_link(root, "bundle/link", "pkg-link")
        dependencies.append(
            {
                "package": "pkg-link",
                "spec": "link:bundle/link",
                "link": "bundle/link",
                "version": "0.0.0",
            }
        )
        bundles.append("pkg-link")
        headless.append(
            {
                "package": "pkg-link",
                "spec": "link:bundle/link",
                "link": "bundle/link",
                "version": "0.0.0",
            }
        )
        live = root / "live" / "pkg-link"
        live.mkdir(parents=True)
        (live / "package.json").write_text(
            (root / "bundle" / "link" / "package.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (live / "patch.yml").write_text(
            (root / "bundle" / "link" / "patch.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        live_dependencies["pkg-link"] = (
            "link:repo/live/pkg-link" if relative_link else f"link:{live}"
        )

    lock: dict[str, Any] = {
        "schema": 1,
        "lock": "lock.json",
        "source": "fixture",
        "engine": "0.2.2-rc.1",
        "engine_authority": "fixture",
        "pnpm": "11.28.8",
        "interactive": {
            "profile": "dsh-tui",
            "bundles": bundles,
            "dependencies": dependencies,
        },
        "headless": {
            "profile": "dsh-headless",
            "github_plugin": "github:fixture/plugin#0000000000000000000000000000000000000000",
            "bundles": headless,
        },
    }
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    profile = {
        "name": "fixture",
        "engines": {"dsh": "0.2.2-rc.1"},
        "dependencies": live_dependencies,
        "dsh": {"profile": {"bundles": bundles}},
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(_gate(lock)), encoding="utf-8")
    return root, lock_path, profile_path, gate_path


def _doctor(root: Path, lock: Path, profile: Path, gate: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(DOCTOR),
        "--root",
        str(root),
        "--lock",
        str(lock),
        "--profile",
        str(profile),
        "--gate",
        str(gate),
    )


def test_lock_shape() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["schema"] == 1
    assert len(lock["interactive"]["dependencies"]) == 25
    assert len(lock["interactive"]["bundles"]) == 24
    assert len(lock["headless"]["bundles"]) == 24
    assert lock["headless"]["github_plugin"].startswith("github:PerryLink/dsh-github#")


def test_every_link_target_is_repo_relative_and_exists() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for variant in ("interactive", "headless"):
        for entry in lock[variant][f"{'dependencies' if variant == 'interactive' else 'bundles'}"]:
            spec = entry["spec"]
            if not spec.startswith("link:"):
                continue
            link = entry["link"]
            assert not Path(link).is_absolute(), entry
            assert ".." not in Path(link).parts, entry
            assert (ROOT / link / "package.json").is_file(), entry


def test_render_gate_matches_committed_recipe() -> None:
    result = _run(str(DOCTOR), "--render-gate", "--lock", str(LOCK), "--root", str(ROOT))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(GATE.read_text(encoding="utf-8"))


def test_fixture_profile_passes(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path)
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_missing_dependency_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path)
    data = json.loads(profile.read_text(encoding="utf-8"))
    del data["dependencies"]["pkg-a"]
    profile.write_text(json.dumps(data), encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "missing" in result.stderr.lower()


def test_version_drift_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path)
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["dependencies"]["pkg-a"] = "2.0.0"
    profile.write_text(json.dumps(data), encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "pkg-a" in result.stderr


def test_bundle_list_drift_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path)
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["dsh"]["profile"]["bundles"] = []
    profile.write_text(json.dumps(data), encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "bundles" in result.stderr.lower()


def test_gate_drift_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path)
    data = json.loads(gate.read_text(encoding="utf-8"))
    data["pnpm"] = "0.0.0"
    gate.write_text(json.dumps(data), encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "gate" in result.stderr.lower()


def test_relative_live_link_resolves_against_the_profile_directory(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True, relative_link=True)
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_external_live_link_is_compared_byte_for_byte(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True)
    live = root / "live" / "pkg-link"
    external = tmp_path / "external" / "pkg-link"
    shutil.copytree(live, external)
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["dependencies"]["pkg-link"] = f"link:{external}"
    profile.write_text(json.dumps(data), encoding="utf-8")
    assert _doctor(root, lock, profile, gate).returncode == 0
    (external / "patch.yml").write_text("id: changed\n", encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "differs" in result.stderr.lower()


def test_link_content_drift_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True)
    live = Path(json.loads(profile.read_text(encoding="utf-8"))["dependencies"]["pkg-link"][5:])
    (live / "patch.yml").write_text("id: changed\n", encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "differs" in result.stderr.lower() or "drift" in result.stderr.lower()


def test_extra_live_file_fails(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True)
    live = Path(json.loads(profile.read_text(encoding="utf-8"))["dependencies"]["pkg-link"][5:])
    (live / "extra.yml").write_text("id: extra\n", encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "extra live file" in result.stderr.lower()


def test_declared_extra_live_file_passes(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True)
    data = json.loads(lock.read_text(encoding="utf-8"))
    entry = next(item for item in data["interactive"]["dependencies"] if item.get("link"))
    entry["extra_live"] = ["extra.yml"]
    lock.write_text(json.dumps(data), encoding="utf-8")
    live = Path(json.loads(profile.read_text(encoding="utf-8"))["dependencies"]["pkg-link"][5:])
    (live / "extra.yml").write_text("id: extra\n", encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 0, result.stderr


def test_absolute_link_is_rejected(tmp_path: Path) -> None:
    root, lock, profile, gate = _fixture(tmp_path, with_link=True)
    data = json.loads(lock.read_text(encoding="utf-8"))
    entry = data["interactive"]["dependencies"][1]
    entry["spec"] = "link:/absolute/elsewhere"
    entry["link"] = "/absolute/elsewhere"
    lock.write_text(json.dumps(data), encoding="utf-8")
    result = _doctor(root, lock, profile, gate)
    assert result.returncode == 2
    assert "absolute" in result.stderr.lower()


@pytest.mark.local
def test_live_profile_passes_the_doctor() -> None:
    result = _run(str(DOCTOR))
    assert result.returncode == 0, result.stderr


def test_agents_names_the_session_start() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "llms.txt" in text
    assert "just session-start" in text
    assert "docs/handbook/ecosystem.md" in text


def test_manifest_records_the_contract() -> None:
    text = (ROOT / "docs" / "manifest.md").read_text(encoding="utf-8")
    assert "profile lock" in text.lower()
    assert "ecosystem index" in text.lower()

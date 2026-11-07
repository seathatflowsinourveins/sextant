"""Frozen FIXTURE_ONLY inputs and explicit draft-code provenance for MODELED S.

Registry construction uses the owning ranking/entry/custody/re-entry modules;
no source fixture supplies deployment, live-feed or canonical-ledger authority.
"""

import importlib
import json
import re
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import sextant
from sextant.exits.policy import ExitParams
from sextant.ranking.registry import ROWS, Registry, RegistryRow
from sextant.reentry.policy import Params
from sextant.risk.controls import Controls
from sextant.sandbox.handoff import digest


def load_profile(path: Path) -> dict:
    profile = json.loads(path.read_text())
    if (
        profile["schema"] != "sextant.sandbox.replay-fixture/1"
        or profile["scope"] != "FIXTURE_ONLY"
    ):
        raise ValueError("explicit fixture-only replay profile required")
    for group in ("entry", "controls", "ranking", "exit", "reentry", "execution", "tape"):
        rows = profile[group]
        if len({row["name"] for row in rows}) != len(rows):
            raise ValueError("duplicate fixture control")
        if any(
            row["scope"] != "FIXTURE_ONLY"
            or not all(row.get(k) for k in ("source", "unit", "last_change", "calibration"))
            for row in rows
        ):
            raise ValueError("fixture registry provenance required")
    digest(profile)  # Reject a float/nonfinite identity before any runtime construction.
    return profile


def values(profile: dict, group: str) -> dict:
    return {row["name"]: row["value"] for row in profile[group]}


def enable_entry_witness(repo: Path, profile: dict, root: Path | None) -> dict[str, str]:
    """Only explicitly selected, byte-verified source may supplement an unmerged module."""
    if root is None:
        module = importlib.import_module("sextant.entry.signals")
        if module.__file__ is None:
            raise ValueError("entry source has no file identity")
        package = Path(module.__file__).parent
    else:
        pin = profile["entry_pin"]
        files = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", pin, "src/sextant/entry"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()
        if not files:
            raise ValueError("pinned entry source missing")
        for name in files:
            expected = subprocess.run(
                ["git", "show", f"{pin}:{name}"],
                cwd=repo,
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            if (root / name).read_bytes() != expected:
                raise ValueError("draft entry source hash differs from its pin")
        path = str((root / "src/sextant").resolve())
        if path not in sextant.__path__:
            sextant.__path__.append(path)
        package = root / "src/sextant/entry"
    return {f"entry/{p.name}": digest(p.read_bytes()) for p in sorted(package.glob("*.py"))}


def enable_session_witness(repo: Path, pin: str, root: Path | None) -> dict[str, str]:
    if root is None:
        file = importlib.import_module("sextant.paper.sessions").__file__
        if file is None:
            raise ValueError("session source has no file identity")
        package = Path(file).parent
    else:
        for name in ("__init__.py", "sessions.py"):
            relative = f"src/sextant/paper/{name}"
            expected = subprocess.run(
                ["git", "show", f"{pin}:{relative}"],
                cwd=repo,
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            if (root / relative).read_bytes() != expected:
                raise ValueError("session source differs from its frozen pin")
        path = str((root / "src/sextant").resolve())
        if path not in sextant.__path__:
            sextant.__path__.append(path)
        package = root / "src/sextant/paper"
    return {
        f"paper/{name}": digest((package / name).read_bytes())
        for name in ("__init__.py", "sessions.py")
    }


def controls(profile: dict) -> Controls:
    return Controls.from_rows(profile["controls"], fixture=True)


def entry_parameters(profile: dict):
    return importlib.import_module("sextant.entry.parameters").EntryParameters.from_rows(
        profile["entry"], fixture=True
    )


def ranking_registry(profile: dict) -> Registry:
    return Registry(
        tuple(
            RegistryRow(
                row["name"],
                ROWS[row["name"]][1],
                ROWS[row["name"]][0](row["value"]),
                row["source"],
                "UNCALIBRATED",
                date.fromisoformat(row["last_change"]),
            )
            for row in profile["ranking"]
        )
    )


def exit_parameters(profile: dict) -> ExitParams:
    fields: dict[str, Any] = {
        k: v if k == "breach_persist_count" else Decimal(v)
        for k, v in values(profile, "exit").items()
    }
    return ExitParams(**fields)


def reentry_parameters(profile: dict) -> Params:
    counts = {"retry_rank_band", "rotation_rank_band", "whipsaw_stopouts_max"}
    fields: dict[str, Any] = {
        k: v if k in counts else Decimal(v) for k, v in values(profile, "reentry").items()
    }
    return Params(**fields)


def source_identity(repo: Path, profile: dict, entry_source: dict[str, str]) -> dict:
    files = {
        str(path.relative_to(repo)): digest(path.read_bytes())
        for path in sorted((repo / "src/sextant").rglob("*.py"))
    }
    runtime = {name: digest((repo / name).read_bytes()) for name in ("pyproject.toml", "uv.lock")}
    return dict(files=files, entry=entry_source, fixture_profile=digest(profile), runtime=runtime)


def verify_implementation(repo: Path, pin: str, profile: Path):
    """Require the frozen source/runtime/profile to be present in the named commit."""
    if not re.fullmatch("[0-9a-f]{40}", pin):
        raise ValueError("concrete implementation commit required")
    selected = [
        "src/sextant",
        "pyproject.toml",
        "uv.lock",
        str(profile.resolve().relative_to(repo.resolve())),
    ]
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", pin, "--", *selected],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    actual = {str(path.relative_to(repo)) for path in (repo / "src/sextant").rglob("*.py")}
    actual.update(selected[1:])
    if actual != {name for name in tree if name.endswith(".py") or name in selected[1:]}:
        raise ValueError("source/profile must be committed at the implementation pin")
    changed = subprocess.run(
        ["git", "diff", "--quiet", pin, "--", *selected],
        cwd=repo,
        capture_output=True,
        timeout=30,
    )
    if changed.returncode:
        raise ValueError("source/runtime/profile differs from the committed implementation")

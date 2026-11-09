"""The ecosystem index: llms.txt stays current, every link resolves, every page is mapped."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
INDEX = ROOT / "scripts" / "ecosystem_index.py"
LLMS = ROOT / "llms.txt"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def test_llms_txt_is_current() -> None:
    result = _run(str(INDEX), "--check")
    assert result.returncode == 0, result.stderr


def test_llms_links_resolve_and_are_relative() -> None:
    text = LLMS.read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)]+)\)", text)
    assert links, "llms.txt has no links"
    for link in links:
        assert not link.startswith("/"), link
        assert "://" not in link, link
        assert (ROOT / link).is_file(), link
    assert "/home/" not in text


def test_llms_covers_every_adr_lane_and_handbook_page() -> None:
    text = LLMS.read_text(encoding="utf-8")
    paths = [
        *sorted((ROOT / "docs" / "adr").glob("*.md")),
        *sorted((ROOT / "lanes").glob("*/README.md")),
        *sorted((ROOT / "docs" / "handbook").glob("*.md")),
    ]
    for path in paths:
        assert path.relative_to(ROOT).as_posix() in text, path


def test_every_entry_has_a_description() -> None:
    lines = LLMS.read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines if line.startswith("- [")]
    assert len(entries) >= 50
    for line in entries:
        assert " \u2014 " in line, line
        assert line.split(" \u2014 ", 1)[1].strip(), line


def test_ecosystem_map_routes_every_domain() -> None:
    text = (ROOT / "docs" / "handbook" / "ecosystem.md").read_text(encoding="utf-8")
    for token in (
        "docs/design.md",
        "docs/adr",
        "lanes/",
        "docs/manifest.md",
        "gh pr view",
        "orca orchestration",
        "session_search",
        "Context7",
        "Cite",
        "just session-start",
    ):
        assert token in text, token

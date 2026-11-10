"""One upstream owns each surface: the page and the gate must say the same thing."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
DANGER = ROOT / "dangerfile.js"
PAGE = ROOT / "docs/handbook/sources.md"
SHA = "c" * 40
MANIFEST = (
    "| Practice or pick | Source, pinned | How it is applied | Proof |\n"
    "|---|---|---|---|\n"
    "| Real row | source | applied | proof |\n"
)
HARNESS = """
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const fails = [];
const pending = [];
const danger = {
  github: {
    pr: { body: input.body, user: { login: input.login } },
    utils: { fileContents: async () => input.manifest },
  },
  git: { created_files: input.created, modified_files: [] },
};
const api = { danger, fail: (m) => fails.push(m), schedule: (p) => pending.push(p()) };
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), { require: () => api });
Promise.all(pending).then(() => process.stdout.write(JSON.stringify(fails) + "\\n"));
"""


def _body(sources: str) -> str:
    return (
        "## What changed\nx\n"
        '## Manifest row\n"Real row"\n'
        f"## Upstream references\n{sources}\n"
        "## How verified\ny\n"
        "## How to revert\nz\n"
    )


def _failures(sources: str, created: tuple[str, ...]) -> list[str]:
    done = subprocess.run(
        ["node", "-e", HARNESS, str(DANGER)],
        input=json.dumps(
            {
                "body": _body(sources),
                "login": "someone",
                "created": list(created),
                "manifest": MANIFEST,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def _danger() -> dict[str, dict[str, set[str]]]:
    block = DANGER.read_text().split("const AUTHORITY = {", 1)[1].split("\n};\n", 1)[0]
    surfaces: dict[str, dict[str, set[str]]] = {}
    current = ""
    for line in block.splitlines():
        match = re.match(r"  (\w+): \{", line)
        if match:
            current = match.group(1)
            surfaces[current] = {"paths": set(), "owners": set()}
            continue
        for quoted in re.findall(r'"([^"]+)"', line):
            key = "paths" if quoted.endswith("/") else "owners"
            surfaces[current][key].add(quoted)
    return surfaces


def _page() -> dict[str, dict[str, set[str]]]:
    surfaces: dict[str, dict[str, set[str]]] = {}
    for line in PAGE.read_text().splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Surface", "---"}:
            continue
        surface = cells[0].strip("`")
        pin = cells[2]
        assert re.search(r"\b[0-9a-f]{40}\b", pin) or re.search(r"read 20\d\d-\d\d-\d\d", pin), (
            surface
        )
        paths = set(re.findall(r"`([^`]+)`", cells[3]))
        assert paths and all((ROOT / path).is_dir() for path in paths), surface
        surfaces[surface] = {
            "owners": set(re.findall(r"`([^`]+)`", cells[1])),
            "paths": paths,
        }
    return surfaces


def _sample(paths: set[str]) -> str:
    return sorted(paths, key=lambda path: (not path.startswith("src/"), len(path)))[0] + "x"


def _cite(owner: str) -> str:
    return f"{owner}@v1 {SHA}" if "/" in owner else f"https://{owner}/page, read 2026-11-09"


def test_the_page_and_the_dangerfile_name_the_same_surfaces() -> None:
    assert set(_page()) == set(_danger())


def test_every_surface_has_the_same_owners_and_paths_on_page_and_gate() -> None:
    page, danger = _page(), _danger()
    for surface, rule in danger.items():
        assert page[surface]["owners"] == rule["owners"], surface
        assert page[surface]["paths"] == rule["paths"], surface


def test_a_fork_on_a_governed_path_fails_the_gate() -> None:
    for surface, rule in _danger().items():
        found = _failures(f"example/fork@v1 {SHA}", (_sample(rule["paths"]),))
        assert any(surface in failure and "authority" in failure.lower() for failure in found), (
            surface
        )


def test_every_owner_on_its_own_path_passes_the_gate() -> None:
    for surface, rule in _danger().items():
        for owner in rule["owners"]:
            assert _failures(_cite(owner), (_sample(rule["paths"]),)) == [], (surface, owner)


def test_ao_owner_on_its_claim_path_passes_the_gate() -> None:
    sources = "OrchestratorInc/agent-orchestrator@v0.14.10 033d597032e448a0ea16c298350e36b099f74106"
    assert _failures(sources, ("deploy/wsl/ao.sh",)) == []


def test_an_ao_fork_on_the_claim_path_fails_the_gate() -> None:
    sources = "example/agent-orchestrator@v0.14.10 033d597032e448a0ea16c298350e36b099f74106"
    found = _failures(sources, ("deploy/wsl/ao.sh",))
    assert any("harness" in failure and "authority" in failure.lower() for failure in found)


def test_a_pinned_blob_url_cites_its_owner() -> None:
    sources = (
        f"https://github.com/nautechsystems/nautilus_trader/blob/{SHA}/engine.py, read 2026-11-09"
    )
    assert _failures(sources, ("src/sextant/exits/engine.py",)) == []


def test_every_pin_and_owner_is_already_in_the_manifest() -> None:
    manifest = (ROOT / "docs/manifest.md").read_text().lower()
    for pin in set(re.findall(r"\b[0-9a-f]{40}\b", PAGE.read_text())):
        assert pin in manifest, pin
    for rule in _page().values():
        for owner in rule["owners"]:
            assert owner.lower() in manifest, owner

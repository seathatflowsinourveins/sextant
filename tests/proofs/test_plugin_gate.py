"""Third-party plugin admission: the screen is recorded and every admitted row discloses itself."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
PLUGINS = ROOT / "docs/handbook/plugins.md"
MANIFEST = ROOT / "docs/manifest.md"
TRUST_CHECK = "787912e37367e3b0e5cbe5a259253a88f3afd502"
CATALOG = "668c3fa6e759f413da6b90e3f3af9a3e6b0f6ee9"


def _register_rows() -> list[str]:
    sections = re.split(r"^## ", MANIFEST.read_text(), flags=re.M)
    register = next(part for part in sections if part.startswith("Third-party plugins\n"))
    return [
        row
        for row in register.splitlines()
        if row.startswith("| ")
        and not row.startswith("| Practice or pick |")
        and not row.startswith("|---")
    ]


def test_the_plugin_page_records_the_screen_and_the_gate() -> None:
    page = PLUGINS.read_text()
    for marker in ("**Pin.**", "**Disclosure.**", "**Owner.**", "**Proof.**", "**Removal.**"):
        assert marker in page
    assert TRUST_CHECK in page
    assert CATALOG in page
    assert "No row, no install" in page


def test_the_screen_records_all_five_verdicts() -> None:
    page = PLUGINS.read_text()
    for verdict in (
        "Adopt the gate",
        "Pattern only",
        "Watch [eve1329/dsh-shared-handoff]",
        "Watch [kenz1117/dsh-engram]",
        "Reject [pengpengyi92/dsh-quant]",
    ):
        assert verdict in page


def test_the_gate_has_its_manifest_row() -> None:
    name = "Third-party plugin admission: capability disclosure before a row"
    assert f"| {name} |" in MANIFEST.read_text()


def test_every_admitted_register_row_is_pinned_and_disclosed() -> None:
    rows = _register_rows()
    assert rows, "the register section has no table"
    for row in rows:
        if "none admitted" in row:
            continue
        assert re.search(r"\b[0-9a-f]{40}\b", row), row
        assert re.search(r"capabilit", row, re.I), row
        assert re.search(r"red.line", row, re.I), row

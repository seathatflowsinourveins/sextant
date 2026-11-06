"""The harvested decision records: pinned sources, and the owner's limits carried exactly."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
PINS = {
    "northstar": "b384d298d217d3f8d9aa83356994629536a34795",
    "northstar-lanes": "00203275944a22655b3e14b221cfde9a265d549a",
    "northstar-trading": "8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa",
}


def test_every_harvested_record_names_a_pinned_source() -> None:
    records = [
        record
        for record in sorted((ROOT / "docs" / "adr").glob("[0-9]*.md"))
        if "Harvested from" in record.read_text()
    ]
    assert records
    for record in records:
        cited = re.findall(
            r"\b(northstar(?:-lanes|-trading)?)@([0-9a-f]{7,40})\b",
            record.read_text(),
        )
        assert cited, record.name
        for repo, pin in cited:
            assert PINS[repo].startswith(pin), f"{record.name}: {repo}@{pin}"


def test_the_pins_are_the_ones_the_manifest_names() -> None:
    manifest = (ROOT / "docs" / "manifest.md").read_text()
    for pin in PINS.values():
        assert pin in manifest


def _owner_limit(name: str) -> int:
    limits = (ROOT / "lanes" / "limits.yaml").read_text()
    found = re.search(rf"^  {name}: (\d+)$", limits, re.MULTILINE)
    assert found, name
    return int(found[1])


def test_owner_limits_are_carried_exactly() -> None:
    assert _owner_limit("alpaca_live") == 1000
    assert _owner_limit("alpaca_paper") == 200
    assert _owner_limit("ibkr_paper_and_live") == 3000

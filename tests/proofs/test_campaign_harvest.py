"""#61: every old record has a verdict, and the adopted corrections are carried."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
NOTE = ROOT / "docs" / "research" / "2026-11-06-campaign-harvest.md"
VERDICTS = {"Adopted", "Carried", "Left behind"}
# Records at the re-read pins: harness 73 numbered (68 live, 5 superseded), trading 20, lanes 11.
EXPECTED = {"harness": 73, "trading": 20, "lanes": 11}


def _rows() -> list[tuple[str, str, str]]:
    found = re.findall(
        r"^\| `(harness|trading|lanes):\d{4}` [^|]+\| ([^|]+?) \| ([^\n]+) \|$",
        NOTE.read_text(),
        re.MULTILINE,
    )
    return found


def test_every_old_record_has_one_verdict() -> None:
    rows = _rows()
    for repo, count in EXPECTED.items():
        assert sum(1 for row in rows if row[0] == repo) == count, repo
    assert {verdict for _, verdict, _ in rows} <= VERDICTS


def test_every_linked_home_exists() -> None:
    for _, _, home in _rows():
        for target in re.findall(r"\]\(([^)#]+)", home):
            assert (NOTE.parent / target).resolve().is_file(), target


def test_adopted_corrections_are_in_the_carried_records() -> None:
    adr = lambda name: next((ROOT / "docs" / "adr").glob(f"{name}-*.md")).read_text()  # noqa: E731
    assert "0029-second-family-corrections.md) C1" in adr("0003")
    assert "`time_in_force` `day` or `gtc`" in adr("0004")
    assert "`HALTED` engine denies emulated stops" in adr("0010")
    record = adr("0029")
    for claim in ("C1", "C2", "C3"):
        assert f"**{claim}," in record
    assert "d53849b216e20f2c122ca01b4dd0da377638b186" in record

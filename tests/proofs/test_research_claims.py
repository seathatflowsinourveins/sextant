"""#109: published claims stay source-bound; absent #129 syntheses cannot become verdicts.

Format: ADR-0015/0022 Evidence tables and the #91 reconciliation, not a research runner.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
NOTE = ROOT / "docs/research/2026-11-06-research-claims.md"


def test_every_reconciled_job_has_an_explicit_sourced_verdict() -> None:
    assert NOTE.is_file(), "#109's published research claim ledger is missing"
    rows = re.findall(
        r"^\| `(91-[ML]\d{2})` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$",
        NOTE.read_text(),
        re.MULTILINE,
    )
    expected = {f"91-M{i:02d}" for i in range(1, 4)} | {
        f"91-L{i:02d}" for i in range(1, 12) if i != 9
    }
    assert len(rows) == len(expected)
    assert {row[0] for row in rows} == expected
    for claim, statement, verdict, source, limits in rows:
        assert statement.strip() and limits.strip(), claim
        assert verdict.strip() in {"HOLD", "REPLACE → ADOPT"}, claim
        assert "C:" in source and "G:" in source and "D:" in source, claim
        assert "Primary:" in source, claim
        assert "NOT_RUN" in limits or "UNVERIFIED" in limits, claim


def test_the_owner_no_shared_memory_ruling_is_carried_with_its_receipt() -> None:
    owner_receipt = "issues/58#issuecomment-6690931913"
    for path in (NOTE, ROOT / "docs/adr/0022-memory-rag-and-enhanced-dsh.md"):
        text = path.read_text()
        assert "No shared memory for now" in text, path
        assert owner_receipt in text, path
    lane = (ROOT / "lanes/research/README.md").read_text()
    assert "2026-11-06-research-claims.md" in lane


def test_input_hashes_match_the_published_reconciliation() -> None:
    source = ROOT / "docs/research/2026-11-06-legs-convergence.md"
    published = source.read_text()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "127551a9ae8c8e9013da6236b187df6c9740167d4c9bc177100e4773055252a8"
    )
    inputs = re.findall(
        r"^\| `(\S+-leg-\S+\.md)` \| [^\n]+? \| `([a-f0-9]{64})` \|",
        NOTE.read_text(),
        re.MULTILINE,
    )
    assert len(inputs) == 5
    for name, digest in inputs:
        assert re.search(rf"^\| `{re.escape(name)}`[^\n]+`{digest}`", published, re.MULTILINE)
    assert "127551a9ae8c8e9013da6236b187df6c9740167d4c9bc177100e4773055252a8" in NOTE.read_text()


def test_129_scope_and_synthesis_slots_remain_awaiting_real_publications() -> None:
    text = NOTE.read_text()
    rows = re.findall(
        r"^\| `(129-N\d{2})` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$",
        text,
        re.MULTILINE,
    )
    assert len(rows) == 6 and {row[0] for row in rows} == {f"129-N{i:02d}" for i in range(1, 7)}
    for claim, scope, verdict, source, missing in rows:
        assert scope.strip() and missing.strip(), claim
        assert verdict.strip() == "AWAITING_PUBLISHED_SYNTHESES", claim
        assert "[8]" in source, claim
    slots = re.findall(r"^\| `(129-S\d{2})` \| [^|]+ \| ([^|]+) \| ([^|]+) \|$", text, re.MULTILINE)
    assert {row[0] for row in slots} == {"129-S01", "129-S02"} and len(slots) == 2
    for _, verdict, evidence in slots:
        assert verdict.strip() == "AWAITING_PUBLISHED_SYNTHESIS"
        assert "Source/family/hash unavailable" in evidence
    assert "343b407e803983bebf98968e9aaccb3f96d9ecf6654dcd70a3d19f53fae9047e" in text
    assert "issues/129#issuecomment-6692530548" in text
    assert "0d4a180525130eb79a510eb3604db1b9faca02bd2c1adef86ef34603a16a5128" in text


def test_conflicts_and_not_run_evidence_have_not_been_smoothed_away() -> None:
    text = NOTE.read_text()
    conflicts = re.findall(r"^\| `(91-C\d{2})` \| ([^\n]+) \|$", text, re.MULTILINE)
    assert len(conflicts) == 10 and {row[0] for row in conflicts} == {
        f"91-C{i:02d}" for i in range(1, 11)
    }
    for _, row in conflicts:
        assert len(row.split(" | ")) == 4
    assert "MISSING_SOURCE" in text and "UNRESOLVED_CONFLICT" in text and "NOT_RUN" in text
    assert "not reset to zero" in text
    for target in re.findall(r"\]\(([^)#]+)", text):
        if not target.startswith("https://"):
            assert (NOTE.parent / target).resolve().is_file(), target

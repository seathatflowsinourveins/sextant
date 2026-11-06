"""#83: the live gate tracker, the promotion-record drafts and the no-endpoint rule (ADR-0020)."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
LIVE = ROOT / "lanes" / "live"
NOTE = ROOT / "docs" / "research" / "2026-11-06-live-gates.md"
# northstar-trading@dd1dc5cd0eb9f5b70d09e98876ca8652aab99ca6 and its `live` head 78da99ba.
PROMOTION = "86bdd514baac95ecf9d2c66296c14d201735ca59bfe7fb4503b834a0d24babee"
DEPLOYMENTS = "e78e62f7aa64fc602164510aec498969ad20e5ecc56e071914af7a3c34761a2e"
UPSTREAM = {"promotion-record.schema.json": PROMOTION, "deployments.schema.json": DEPLOYMENTS}
GATES = [f"P{i}" for i in range(1, 14)] + ["S0", "S1", "S2", "S3"]


def test_schemas_are_the_pinned_upstream_bytes() -> None:
    for name, digest in UPSTREAM.items():
        assert hashlib.sha256((LIVE / "schema" / name).read_bytes()).hexdigest() == digest, name


def test_template_covers_the_schema_and_cannot_pass_as_a_promotion() -> None:
    schema = json.loads((LIVE / "schema" / "promotion-record.schema.json").read_text())
    template = json.loads((LIVE / "promotion-record.template.json").read_text())
    assert set(schema["required"]) <= set(template)
    assert template["schema"] == schema["properties"]["schema"]["const"]
    for key in ("head_sha", "kind", "stage", "promotion_id"):
        assert template[key] is None, key
    assert template["verify"]["verdict"] is None
    assert len(template["gates"]) == 8  # ADR-0053 section 2a's gate table


def test_every_gate_is_tracked_and_none_is_met() -> None:
    text = NOTE.read_text()
    assert "no gate is met" in text
    for gate in GATES:
        row = re.search(rf"^\| {gate} \|.*\| (NOT MET|NOT STARTED)[^|]*\|$", text, re.MULTILINE)
        assert row, gate


def test_main_carries_no_promotion_and_no_live_deployment() -> None:
    assert not (ROOT / "deployments" / "live.json").exists()
    assert not (ROOT / "reports" / "live" / "promotions").exists()
    assert not (ROOT / "scripts" / "live.sh").exists()


def test_no_live_endpoint_in_code() -> None:
    live = re.compile(r"(?<!paper-)api\.alpaca\.markets|:(4001|7496)\b")
    for path in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").glob("*")]:
        assert not live.search(path.read_text()), path

"""ADR-0015 metadata uses the pinned validator; unknown clocks grant no compute authority."""

import hashlib
import json
import runpy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
VALIDATOR = ROOT / "tests/proofs/reference/research-registry.py.txt"


def test_source_cards_use_the_upstream_registry_and_preserve_unknown_availability() -> None:
    assert hashlib.sha256(VALIDATOR.read_bytes()).hexdigest() == (
        "d9df78e9d88006d2d088dc8cf24fec6bb7334b989e501cd713937df32b440672"
    )
    upstream = runpy.run_path(str(VALIDATOR))
    registry = json.loads((ROOT / "research/sources.yaml").read_text())
    sources = upstream["validate_registry"](registry)
    receipt = json.loads(
        (ROOT / "docs/research/2026-11-06-research-source-receipt.json").read_text()
    )
    assert sources and set(sources) == {card["id"] for card in receipt["cards"]}
    assert next(iter(sources.values())).pin.repo.endswith("nautilus_trader")
    assert receipt["new_strategy_trials"] == 0
    assert receipt["historical_trial_count"] is None
    observed = datetime.fromisoformat(receipt["recorded_at"])
    assert observed.utcoffset() is not None
    for card in receipt["cards"]:
        source = sources[card["id"]]
        assert source.status == "candidate"
        assert card["data_knowable_at"] is None and card["compute_admitted"] is False
        known = datetime.fromisoformat(card["source_knowable_at"])
        assert known.utcoffset() is not None and known <= observed
        text = (ROOT / card["path"]).read_text()
        assert card["id"] in text and card["source_knowable_at"] in text
        assert hashlib.sha256((ROOT / card["path"]).read_bytes()).hexdigest() == card["sha256"]


def test_deepseek_leg_receipts_bind_completed_reports_without_upgrading_provisional_gpt() -> None:
    receipt = json.loads((ROOT / "docs/research/2026-11-06-research-leg-receipt.json").read_text())
    assert receipt["dsh"]["configured_effort"] == "max"
    patch = ROOT / receipt["dsh"]["patch_path"]
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == receipt["dsh"]["patch_sha256"]
    assert {leg["job"] for leg in receipt["legs"]} == {"landscape", "memory"}
    for leg in receipt["legs"]:
        report = ROOT / leg["path"]
        assert leg["family"] == "DeepSeek" and leg["process_exit_code"] == 0
        assert hashlib.sha256(report.read_bytes()).hexdigest() == leg["sha256"]
        assert len(report.read_text().splitlines()) == leg["lines"] <= leg["line_budget"]
        assert leg["other_report_paths_in_tool_calls"] == []
        assert leg["new_synthesis_ADR_text_seen"] is False
    provisional = [x for x in receipt["release_inputs"] if x["asset"].endswith("-gpt.md")]
    assert len(provisional) == 2 and all(x["qualifying_GPT_leg"] is False for x in provisional)

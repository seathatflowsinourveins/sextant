"""Proof: the committed row-4 receipt keeps the measured result; read-only, no key (#42)."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "docs/research/2026-11-06-pit-acceptance-receipt.json"
REGISTRATION = ROOT / "docs/research/2026-11-06-delisted-sample-registration.json"
MASTER = ROOT / "src/sextant/data/sharadar_master.py"

TEN_EXITS = {
    "ATVI",
    "BBBY",
    "CELG",
    "FRC",
    "LK",
    "LNKD",
    "SIVB",
    "TWTR",
    "XLNX",
    "YHOO",
}


def test_the_recorded_receipt_keeps_the_measured_result() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert receipt["schema_version"] == 2
    assert receipt["issue"] == 42
    assert receipt["scope"] == "SEP+SFP"
    assert receipt["window"] == ["2016-01-01", "2026-11-05"]
    assert receipt["probe_sha256"] == (
        "3f759c293bc33f697355fdd621abb3866043c8c5a80fb8927154da82eab3ca89"
    )
    assert receipt["survivor_only"] is True
    assert receipt["pit_verified"] is False
    assert receipt["historical_known_at"] is None
    assert receipt["members_manifest_rows"] == 24503
    assert receipt["members_manifest_sha256"] == (
        "e8394fb26f58ea19c0125de4af0ced5cb235d6a23bbb015a168d76adc32389da"
    )
    assert receipt["acceptance_json_sha256"] == (
        "dbef19b7d15dea1dc6240e023e64ec14ff69fb6db2360d4fe6289f269168bc47"
    )
    assert receipt["carried_from"] == (
        "seathatflowsinourveins/northstar-trading@"
        "8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:"
        "src/northstar_trading/data/sharadar.py"
    )

    capture = receipt["capture"]
    assert capture["capture_asof"] == "2026-11-06T16:58:52+00:00"
    assert capture["capture_sha256"] == (
        "cd158d7932f58190b2ffddf2f380d0c2bbd235b5aad3789e079b08afc1ea7de3"
    )
    assert capture["actions_coverage_start"] == "2016-09-30"

    coverage = receipt["coverage"]
    assert coverage["dated_interval_count"] == 24503
    assert coverage["input_security_count"] == 31079
    assert coverage["excluded_security_count"] == 11460
    assert coverage["included_security_count"] == 19619
    assert coverage["exclusion_counts"]["ended_before_actions_coverage"] == 10273
    assert coverage["membership_policy"] == "layered-v1"
    assert coverage["scope"] == "SEP+SFP"

    acceptance = receipt["acceptance"]
    ten_exits = acceptance["ten_exits"]
    assert ten_exits["status"] == "PASS"
    assert ten_exits["covered"] == 10
    assert set(ten_exits["names"]) == TEN_EXITS

    sample = acceptance["independent_delisted_sample"]
    assert sample["status"] == "FAIL"
    assert sample["covered"] == 27
    assert sample["n"] == 40
    assert sample["pass_at_least"] == 38
    assert sample["registration"] == "2026-11-06-delisted-sample-registration.json"
    assert sample["registration_sha256"] == (
        "ba970d724edbae06f086d134e834c32cc8fecd3297e108756d302d0d6bfebd3a"
    )
    assert len(sample["rows"]) == 40
    misses = [row for row in sample["rows"] if not row["covered"]]
    assert len(misses) == 13
    assert sum(row["reason"] == "no Sharadar CIK match" for row in misses) == 5
    assert sum("tickerchange_target_mismatch" in row["reason"] for row in misses) == 4
    assert sum("ended_before_actions_coverage" in row["reason"] for row in misses) == 1
    assert sum("no explicit exit by filing + 10 days" in row["reason"] for row in misses) == 4

    recycled = acceptance["recycled_ticker"]
    assert recycled["meta_fb_2021_12_01_distinct"] is True
    assert recycled["bbby_issuer_count"] == 2
    assert recycled["each_lookup_resolves_one_member"] is True
    assert set(recycled["bbby_security_ids"]) == {"sharadar:195902", "sharadar:197799"}
    assert "UNVERIFIED" in recycled["adr_three_bbby_issuers"]

    asof = acceptance["asof_bars_match_issuer"]
    assert asof["status"] == "PASS"
    assert asof["feed"] == "sip"
    assert asof["adjustment"] == "raw"
    assert len(asof["rows"]) == 4
    assert all(row["match_at_cent"] is True for row in asof["rows"])

    assert acceptance["replacement_backtest"]["status"] == "NOT_RUN"
    assert acceptance["float_history"]["status"] == "UNVERIFIED"

    implementation = receipt["implementation_source_sha256"]
    assert (
        implementation["src/sextant/data/sharadar_master.py"]
        == hashlib.sha256(MASTER.read_bytes()).hexdigest()
    )
    assert implementation["src/sextant/research/pit_acceptance.py"] == (
        "066ef58b6a7c3e2d1a1f380b2de87f7820ce81e1c7a54ed12804e7c05a452181"
    )
    assert implementation["src/sextant/research/delisted_sample.py"] == (
        "6a802753237477e295dd0de11620f8ec51c49f3301bc4b6767926a362f8af8be"
    )
    assert hashlib.sha256(REGISTRATION.read_bytes()).hexdigest() == (sample["registration_sha256"])

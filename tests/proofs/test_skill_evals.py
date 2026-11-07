"""Offline contract for native Claude plugin eval cases; no sign-in or model run in CI.

Source: https://code.claude.com/docs/en/plugin-evals.md, read 2026-11-06.
Actual routing is established only by the native local run receipts, not this test.
"""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[2]
CASES = ROOT / "evals" / "skill-routing" / "cases"
RECEIPTS = ROOT / "evals" / "skill-routing" / "receipts" / "2026-11-06"
SKILLS = {
    "research-draft": "edge-strategy-designer",
    "sim-backtest": "backtest-expert",
    "paper-entry": "pre-trade-discipline-gate",
    "live-draft-review": "edge-strategy-reviewer",
    "options-research": "options-strategy-advisor",
    "tradingview-ticket": "pre-trade-discipline-gate",
    "paper-journal": "trader-memory-core",
    "sim-postmortem": "signal-postmortem",
    "support-pr": "ce-commit-push-pr",
}


def test_lane_cases_use_native_graders_without_leaking_the_skill_into_the_prompt() -> None:
    paths = list(CASES.glob("*/*/case.yaml"))
    assert paths, "native per-lane eval suite is missing"
    cases = {p.parent.name: json.loads(p.read_text()) for p in paths}
    assert set(SKILLS) <= cases.keys()
    lanes = set()
    for name, skill in SKILLS.items():
        case = cases[name]
        assert case["schema_version"] == "1.1" and case["name"] == name
        lanes.update(case["tags"])
        execution = case["execution"]
        assert set(execution["allowed_tools"]) == {"Read", "Glob", "Grep", "Skill"}
        assert not case.get("context"), "routing cases need no shell scaffold or real services"
        prompt = execution["prompt"] + execution.get("append_system_prompt", "")
        assert all(target not in prompt for target in SKILLS.values()), name
        grader = next(g for g in case["graders"] if g["tool"] == "Skill")
        assert grader["type"] == "tool_used" and grader.get("min", 1) >= 1
        pattern = grader["input_match"]
        for called in (skill, f"plugin:{skill}"):
            assert re.search(pattern, json.dumps({"skill": called})), name
        assert not re.search(pattern, json.dumps({"skill": "unrelated"})), name
    assert {"research", "sim", "paper", "live", "options", "tradingview"} <= lanes


def test_each_plugin_has_an_unrelated_request_control() -> None:
    for plugin in ("trading", "compound"):
        path = CASES / plugin / "unrelated-request" / "case.yaml"
        assert path.is_file(), f"{plugin} has no false-positive control"
        case = json.loads(path.read_text())
        grader = next(g for g in case["graders"] if g["type"] == "tool_used")
        assert grader["tool"] == "Skill" and grader["min"] == grader["max"] == 0
        assert grader["arm"] == "both"


def _native_case_is_complete(case: dict, authored: dict) -> None:
    assert case["promptMarkdown"] == authored["execution"]["prompt"]
    assert case["runsPerCase"] == 3
    assert case["timeoutSeconds"] == authored["execution"]["timeout_seconds"]
    assert case["maxTurns"] == authored["execution"].get("max_turns", 10)
    graders = {grader["name"]: grader for grader in case["graders"]}
    assert graders.keys() == {grader["name"] for grader in authored["graders"]}
    for expected in authored["graders"]:
        actual = graders[expected["name"]]
        assert actual["type"] == expected["type"]
        for key, value in expected.items():
            if key not in ("name", "type", "weight"):
                assert actual["config"][key] == value
    for arm in ("with", "without"):
        runs = case["arms"][arm]
        assert len(runs) == 3
        for run in runs:
            assert run["error"] is None, (case["name"], arm, run["error"])
            assert run.get("aborted") is None and not run["skippedPaidGraders"]
            # Positive baselines must not fire. Unrelated controls pass both arms.
            passed = arm == "with" or case["name"] == "unrelated-request"
            assert {g["name"] for g in run["graders"]} == graders.keys()
            assert all(g["passed"] is passed for g in run["graders"])


def test_native_receipts_complete_every_case_without_treating_timeouts_as_success() -> None:
    lock = json.loads((ROOT / ".claude/shelf.lock.json").read_text())
    captured_path = RECEIPTS / "shelf.lock.json"
    assert captured_path.is_file(), "native matrix provenance is not captured yet"
    captured = json.loads(captured_path.read_text())
    assert captured["skills"] == lock["skills"]
    plugin = "compound-engineering@compound-engineering-plugin"
    assert captured["plugins"][plugin] == lock["plugins"][plugin]
    for target in ("trading", "compound"):
        path = RECEIPTS / f"{target}.json"
        assert path.is_file(), f"{target} native matrix has not completed"
        result = json.loads(path.read_text(), parse_float=Decimal)
        assert result["schemaVersion"] == 1 and result["partial"] is False
        assert result["claudeVersion"] == "2.1.318"
        expected = {
            p.parent.name: json.loads(p.read_text()) for p in (CASES / target).glob("*/case.yaml")
        }
        assert {case["name"] for case in result["cases"]} == expected.keys()
        for case in result["cases"]:
            if target == "trading" and case["name"] == "paper-journal":
                # Preserve the original failed case; accept only its complete, whole-case retest.
                assert case["maxTurns"] == 10
                failures = [r for r in case["arms"]["with"] if r["error"]]
                assert len(failures) == 1 and "maximum number of turns (10)" in failures[0]["error"]
                retest = json.loads((RECEIPTS / "paper-journal-retest.json").read_text())
                assert retest["claudeVersion"] == result["claudeVersion"]
                assert retest["partial"] is False and len(retest["cases"]) == 1
                revised = retest["cases"][0]
                assert revised["name"] == case["name"]
                assert revised["promptMarkdown"] == case["promptMarkdown"]
                assert revised["graders"] == case["graders"]
                assert revised["maxTurns"] == 200
                _native_case_is_complete(revised, expected[case["name"]])
            else:
                _native_case_is_complete(case, expected[case["name"]])


def test_failed_pilot_receipt_is_retained_even_though_its_firing_grader_passed() -> None:
    pilot = json.loads((RECEIPTS / "pilot-timeout.json").read_text())
    assert pilot["claudeVersion"] == "2.1.319"
    case = pilot["cases"][0]
    assert all(r["error"] for runs in case["arms"].values() for r in runs)
    assert case["arms"]["with"][0]["graders"][0]["passed"] is True
    ledger = json.loads((RECEIPTS / "attempts.json").read_text())
    assert sum(attempt["nativeChildRuns"] for attempt in ledger["attempts"]) == 75
    for attempt in ledger["attempts"]:
        path = RECEIPTS / attempt["result"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == attempt["sha256"]
        result = json.loads(path.read_text())
        actual_runs = sum(len(runs) for c in result["cases"] for runs in c["arms"].values())
        assert actual_runs == attempt["nativeChildRuns"]

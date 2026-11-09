"""Offline review-eval proofs; synthetic unit-test receipts never establish model quality.

Sources: CR-Bench 2603.11078, CR-Bench-v2 2611.02566 and statsmodels Wilson docs,
all read 2026-11-09; see the manifest's Receipt-only known-defect review evaluation row.
"""

import ast
import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
DIRECTORY = ROOT / "evals" / "review"
SCRIPT = ROOT / "scripts" / "review_eval.py"
SPEC = importlib.util.spec_from_file_location("review_eval", SCRIPT)
assert SPEC and SPEC.loader
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)
PARAMS = EVAL.load_parameters(DIRECTORY)
CASES = EVAL.load_cases(DIRECTORY, PARAMS)


def test_corpus_has_twenty_real_defects_three_controls_and_pinned_citations() -> None:
    assert len(CASES) >= 23
    controls = [c for c in CASES.values() if c["expected"]["false_block_control"]]
    assert len(controls) >= 3 and len(CASES) - len(controls) >= 20
    assert all(
        c["source"]["commit"] != c["source"]["fix_commit"]
        for c in CASES.values()
        if not c["expected"]["false_block_control"]
    )
    assert "control-pr55-default-branch-guard" in CASES
    target = CASES["pr79-relative-profile-link"]
    assert target["source"]["commit"] == "69ef6887b7b977dd91e0e48ee32188f31b1b4b8e"
    assert target["expected"]["defects"][0]["line"] == 226
    assert any("discussion_r4516655850" in url for url in target["source"]["citations"])
    for case in CASES.values():
        for defect in case["expected"]["defects"]:
            assert all(EVAL.citation(url) for url in defect["citations"])
            assert any(f"#L{defect['line']}" in url for url in defect["citations"])


def test_corpus_and_receipts_have_no_secret_material() -> None:
    # Token shapes, not words such as "secret" in a historical workflow variable name.
    secret = re.compile(
        r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"
        r"|\bsk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    )
    for path in DIRECTORY.rglob("*"):
        if path.is_file():
            assert not secret.search(path.read_text()), path
    imports = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text())):
        if isinstance(node, ast.Import):
            imports.update(item.name.split(".")[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
    assert imports <= sys.stdlib_module_names
    assert not imports & {"subprocess", "socket", "urllib", "http", "ctypes"}


@pytest.mark.parametrize("failure", ["count", "controls", "citation", "excerpt"])
def test_offline_check_rejects_invalid_corpus(tmp_path: Path, failure: str) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(DIRECTORY, corpus)
    if failure == "count":
        for path in list((corpus / "cases").glob("*.json"))[19:]:
            path.unlink()
    elif failure == "controls":
        (corpus / "cases" / "control-exact-family-marker.json").unlink()
    else:
        path = corpus / "cases" / "pr79-relative-profile-link.json"
        data = json.loads(path.read_text())
        if failure == "citation":
            data["source"]["citations"] = []
        else:
            data["input"]["excerpts"][0]["text"] += "changed"
        path.write_text(json.dumps(data))
    output, md = tmp_path / "report.json", tmp_path / "report.md"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--check",
            "--corpus",
            str(corpus),
            "--json-output",
            str(output),
            "--markdown-output",
            str(md),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 1, done.stderr
    assert json.loads(output.read_text())["status"] == "invalid"
    assert "validation failed" in md.read_text()


@pytest.mark.parametrize(
    ("successes", "total", "expected"),
    [
        (5, 10, (0.236593090512564, 0.763406909487436)),
        (0, 10, (0.0, 0.277532799862889)),
        (10, 10, (0.722467200137111, 1.0)),
    ],
)
def test_wilson_against_known_score_interval_examples(
    successes: int,
    total: int,
    expected: tuple[float, float],
) -> None:
    # Values from the Wilson score formula at the 0.975 standard-normal quantile.
    assert EVAL.wilson(successes, total, 0.95) == pytest.approx(expected, abs=1e-12)


def test_empty_and_invalid_binomial_samples_are_not_successes() -> None:
    assert EVAL.wilson(0, 0, 0.95) is None
    assert EVAL.rate(0, 0, 0.95)["rate"] is None
    for successes, total in ((-1, 10), (11, 10), (True, 10)):
        with pytest.raises(ValueError):
            EVAL.wilson(successes, total, 0.95)


@pytest.fixture
def fixture_receipt() -> tuple[dict, dict]:
    names = [
        "pr79-relative-profile-link",
        "family-marker-suffix",
        "chase-unsourced-start",
        "control-pr55-default-branch-guard",
        "control-exact-family-marker",
        "control-linked-manifest-source",
    ]
    cases = copy.deepcopy({name: CASES[name] for name in names})
    # Exercise the multi-defect denominator using an explicit synthetic target, never the corpus.
    second = copy.deepcopy(cases[names[0]]["expected"]["defects"][0])
    second.update(id="D2", claim="Synthetic second target for rate accounting only")
    cases[names[0]]["expected"]["defects"].append(second)
    attempts = []
    for index, name in enumerate(names):
        failed = index in (2, 5)
        detected = index == 0
        findings = [{"id": "F1", "claim": "Synthetic unit-test finding, not review evidence"}]
        attempts.append(
            {
                "case_id": name,
                "case_sha256": EVAL.fingerprint(cases[name]),
                "status": "timeout" if index == 2 else "error" if index == 5 else "completed",
                "error": "synthetic coverage failure" if failed else None,
                "blocked": index in (3, 5),
                "review_text": "Synthetic unit-test receipt only",
                "review_reference": "tests/proofs/test_review_eval.py::fixture_receipt",
                "findings": findings,
                "judgments": []
                if failed
                else [
                    {
                        "defect_id": d["id"],
                        "detected": detected,
                        "finding_ids": ["F1"] if detected else [],
                        "reason": "Synthetic semantic decision for deterministic accounting",
                    }
                    for d in cases[name]["expected"]["defects"]
                ],
            }
        )
    return cases, {
        "schema_version": "1.1",
        "id": "unit-test-only",
        "kind": "evaluation",
        "reviewer": {
            "family": "fixture",
            "model": "fixture",
            "runtime": "fixture",
            "effort": "fixture",
        },
        "adjudicator": {"name": "fixture", "method": "semantic-manual", "reference": __file__},
        "attempts": attempts,
    }


def test_kddr_false_blocks_coverage_and_per_defect_detection(fixture_receipt: tuple) -> None:
    cases, receipt = fixture_receipt
    report = EVAL.score(receipt, cases, PARAMS)
    metrics = report["metrics"]
    assert (metrics["kddr"]["numerator"], metrics["kddr"]["denominator"]) == (2, 4)
    assert metrics["kddr"]["rate"] == 0.5
    assert metrics["false_block_rate"]["rate"] == pytest.approx(2 / 3)
    assert metrics["coverage_failure_rate"]["rate"] == pytest.approx(2 / 6)
    rows = {row["case_id"]: row for row in report["cases"]}
    assert rows["pr79-relative-profile-link"]["detected"] == {"D1": True, "D2": True}
    assert rows["chase-unsourced-start"]["detected"] == {"D1": False}
    assert any("half-width exceeds 15" in reason for reason in report["stop_reasons"])


def test_missing_cases_and_unknown_block_decisions_stay_unavailable(fixture_receipt: tuple) -> None:
    cases, receipt = fixture_receipt
    receipt["attempts"].pop(5)  # unattempted, not an error or a clean pass
    receipt["attempts"][3]["blocked"] = None  # completed, but no gate decision recorded
    report = EVAL.score(receipt, cases, PARAMS)
    assert report["controls_without_block_decision"] == 1
    assert report["metrics"]["false_block_rate"]["denominator"] == 1
    assert report["metrics"]["coverage_failure_rate"]["denominator"] == 5
    assert report["unattempted_cases"] == ["control-linked-manifest-source"]


@pytest.mark.parametrize(
    "failure", ["hash", "duplicate", "unjudged", "unsupported-hit", "timeout-hit"]
)
def test_invalid_or_unbound_judgments_are_refused(fixture_receipt: tuple, failure: str) -> None:
    cases, receipt = fixture_receipt
    first = receipt["attempts"][0]
    if failure == "hash":
        first["case_sha256"] = "0" * 64
    elif failure == "duplicate":
        receipt["attempts"].append(copy.deepcopy(first))
    elif failure == "unjudged":
        first["judgments"].pop()
    elif failure == "unsupported-hit":
        first["judgments"][0]["finding_ids"] = []
    else:
        receipt["attempts"][2]["judgments"] = copy.deepcopy(first["judgments"])
    with pytest.raises(ValueError):
        EVAL.score(receipt, cases, PARAMS)


def test_semantic_judgment_does_not_reward_word_overlap(fixture_receipt: tuple) -> None:
    cases, receipt = fixture_receipt
    missed = receipt["attempts"][1]
    missed["findings"][0]["claim"] = cases[missed["case_id"]]["expected"]["defects"][0]["claim"]
    # The semantic adjudication remains a miss; string similarity is never substituted for it.
    report = EVAL.score(receipt, cases, PARAMS)
    assert report["metrics"]["kddr"]["numerator"] == 2


def test_timeout_before_any_output_is_preserved_as_a_coverage_failure(
    fixture_receipt: tuple,
) -> None:
    cases, receipt = fixture_receipt
    receipt["attempts"][2].update(review_text="", findings=[])
    report = EVAL.score(receipt, cases, PARAMS)
    assert report["metrics"]["coverage_failure_rate"]["numerator"] == 2
    assert report["metrics"]["kddr"]["numerator"] == 2


def test_historical_evidence_is_bound_unpooled_and_not_a_clean_pr55_claim() -> None:
    report = EVAL.evaluate(DIRECTORY)
    assert report["model_execution"] is False and report["required_check"] is False
    assert report["receipt_count"] >= 2
    assert "metrics" not in report  # no pooled score across reviewers or historical attempts
    for cohort in report["cohorts"]:
        if cohort["receipt_id"] not in {"historical-pr55-codex", "historical-pr79-dsh"}:
            continue
        assert cohort["kind"] == "historical"
        assert cohort["reviewer"]["model"] == cohort["reviewer"]["effort"] == "unavailable"
        assert any("retrospective" in reason for reason in cohort["stop_reasons"])
    incident = EVAL.read_json(DIRECTORY / "incidents" / "pr55-coverage-block.json")
    assert incident["diff_characters"] == 60492 and incident["blocked"] is True
    assert incident["status"] == "error" and incident["scored"] is False
    assert "independent code defects" in incident["reason"]


def test_cli_emits_json_markdown_and_hides_ground_truth(tmp_path: Path) -> None:
    output, md = tmp_path / "report.json", tmp_path / "report.md"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--check",
            "--json-output",
            str(output),
            "--markdown-output",
            str(md),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(output.read_text())["case_count"] == len(CASES)
    assert "Wilson 95% interval" in md.read_text() and "No model executes in CI" in md.read_text()
    shown = subprocess.run(
        [sys.executable, str(SCRIPT), "--review-input", "pr79-relative-profile-link"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert shown.returncode == 0
    assert set(json.loads(shown.stdout)) == {"case_sha256", "repository", "commit", "input"}
    assert "discussion_r4516655850" not in shown.stdout
    control = subprocess.run(
        [sys.executable, str(SCRIPT), "--review-input", "control-exact-family-marker"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert control.returncode == 0
    assert "control-exact-family-marker" not in control.stdout
    assert "false_block_control" not in control.stdout


def test_workflow_is_weekly_manual_default_branch_hosted_and_receipt_only() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/review-eval.yml").read_text())
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch", "schedule"}
    assert events["schedule"] == [{"cron": "23 7 * * 1"}]
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["receipt"]
    assert job["if"] == (
        "${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"])
    checkout = job["steps"][0]
    assert checkout["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    command = next(s["run"] for s in job["steps"] if "run" in s)
    assert "scripts/review_eval.py --check" in command and "--markdown-output" in command
    post = job["steps"][-1]
    assert post["if"] == "${{ !cancelled() }}"
    assert "github.paginate" in post["with"]["script"]
    assert "github.rest.issues.update" in post["with"]["script"]
    assert "github.rest.issues.create" in post["with"]["script"]


def test_review_eval_workflow_is_not_required_or_connected_to_pr_statuses() -> None:
    for path in (ROOT / ".github/rulesets").glob("*.json"):
        rules = json.loads(path.read_text())
        for rule in rules["rules"]:
            if rule["type"] == "required_status_checks":
                assert not any(
                    "review-eval" in check["context"]
                    for check in rule["parameters"]["required_status_checks"]
                )
    gate = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    assert gate.get("on", gate.get(True))["workflow_run"]["workflows"] == ["ci"]
    workflow = (ROOT / ".github/workflows/review-eval.yml").read_text()
    assert "createCommitStatus" not in workflow and "checks.create" not in workflow
    assert "secrets." not in workflow
    assert "OPENAI_API_KEY" not in workflow and "DEEPSEEK_API_KEY" not in workflow

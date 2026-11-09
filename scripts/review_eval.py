#!/usr/bin/env python3
"""Offline CR-Bench-style semantic receipt accounting; never calls a reviewer or a model.

Sources and operational bounds: evals/review/README.md and parameters.json.
"""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "evals" / "review"
SHA = re.compile(r"[0-9a-f]{40}")
IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-JSON numeric constant in {path.name}")

    data = json.loads(path.read_text(), parse_constant=invalid_constant)
    require(isinstance(data, dict), f"{path.name}: expected a JSON object")
    return data


def fingerprint(case: dict) -> str:
    return hashlib.sha256(
        json.dumps(case, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def citation(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/(?:pull|commit|blob)/[^\s]+", value)
    )


def load_parameters(directory: Path) -> dict:
    params = read_json(directory / "parameters.json")
    for key in ("min_cases", "min_defect_cases", "min_controls"):
        row = params[key]
        require(type(row["value"]) is int and row["value"] > 0, f"invalid parameter: {key}")
        require(text(row["source"]), f"missing parameter authority: {key}")
    for key in ("confidence", "max_wilson_half_width"):
        row = params[key]
        require(type(row["value"]) in (int, float) and 0 < row["value"] < 1, f"invalid {key}")
        require(text(row["source"]), f"missing parameter authority: {key}")
    return {key: row["value"] for key, row in params.items()}


def load_cases(directory: Path, params: dict) -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for path in sorted((directory / "cases").glob("*.json")):
        case = read_json(path)
        name = case["id"]
        require(isinstance(name, str) and bool(IDENTIFIER.fullmatch(name)), "invalid case id")
        require(name not in cases, f"duplicate case: {name}")
        require(case["schema_version"] == "1.1", f"{name}: unsupported schema")
        source, expected, task = case["source"], case["expected"], case["input"]
        require(bool(SHA.fullmatch(source["commit"])), f"{name}: missing source SHA")
        require(bool(SHA.fullmatch(source["fix_commit"])), f"{name}: missing fix SHA")
        require(re.fullmatch(r"[\w.-]+/[\w.-]+", source["repository"]) is not None, name)
        require(source["pr"] is None or citation(source["pr"]), f"{name}: invalid PR")
        require(source["citations"] and all(map(citation, source["citations"])), name)
        fix_url = f"https://github.com/{source['repository']}/commit/{source['fix_commit']}"
        require(fix_url in source["citations"], f"{name}: missing pinned fix citation")
        prefix = f"https://github.com/{source['repository']}/blob/{source['commit']}/"
        require(task["format"] == "bounded-file-excerpts" and text(task["context"]), name)
        require(bool(task["excerpts"]), f"{name}: no input")
        for excerpt in task["excerpts"]:
            file = PurePosixPath(excerpt["path"])
            require(not file.is_absolute() and ".." not in file.parts, f"{name}: invalid path")
            start, end = excerpt["start_line"], excerpt["end_line"]
            require(type(start) is int and type(end) is int and 0 < start <= end, name)
            require(
                text(excerpt["text"]) and len(excerpt["text"].splitlines()) == end - start + 1,
                f"{name}: excerpt line range differs",
            )
            digest = hashlib.sha256(excerpt["text"].encode()).hexdigest()
            require(digest == excerpt["sha256"], f"{name}: excerpt hash differs")
            require(
                any(url.startswith(prefix + str(file) + "#L") for url in source["citations"]),
                f"{name}: no pinned file-line citation",
            )
        control = expected["false_block_control"]
        require(type(control) is bool, f"{name}: control label must be boolean")
        defects = expected["defects"]
        require(isinstance(defects, list) and bool(defects) != control, name)
        require(len({d["id"] for d in defects}) == len(defects), f"{name}: duplicate defect")
        if control:
            require(expected["severity"] == "none" and text(expected["control_rationale"]), name)
        for defect in defects:
            require(
                text(defect["id"]) and text(defect["claim"]) and "\n" not in defect["claim"],
                f"{name}: missing one-line defect claim",
            )
            require(defect["severity"] in {"P0", "P1", "P2", "P3"}, name)
            require(expected["severity"] in {"P0", "P1", "P2", "P3"}, name)
            require(
                type(defect["line"]) is int
                and any(
                    e["path"] == defect["path"]
                    and e["start_line"] <= defect["line"] <= e["end_line"]
                    for e in task["excerpts"]
                ),
                f"{name}: defect outside input",
            )
            require(defect["citations"] and all(map(citation, defect["citations"])), name)
            require(
                prefix + defect["path"] + f"#L{defect['line']}" in defect["citations"],
                f"{name}: missing exact defect line citation",
            )
        cases[name] = case
    controls = sum(c["expected"]["false_block_control"] for c in cases.values())
    require(len(cases) >= params["min_cases"], "fewer than minimum cases")
    require(len(cases) - controls >= params["min_defect_cases"], "fewer than minimum defect cases")
    require(controls >= params["min_controls"], "fewer than minimum clean controls")
    return cases


def validate_receipt(receipt: dict, cases: dict[str, dict]) -> None:
    require(receipt["schema_version"] == "1.1" and text(receipt["id"]), "invalid receipt")
    require(receipt["kind"] in {"historical", "evaluation"}, "invalid receipt kind")
    for key in ("family", "runtime", "model", "effort"):
        require(
            text(receipt["reviewer"][key]), f"missing reviewer {key}; use unavailable explicitly"
        )
    judge = receipt["adjudicator"]
    require(
        judge["method"] == "semantic-manual" and text(judge["name"]) and text(judge["reference"]),
        "semantic adjudication provenance is required",
    )
    seen = set()
    require(bool(receipt["attempts"]), "empty receipt; omit the file until an attempt exists")
    for attempt in receipt["attempts"]:
        name = attempt["case_id"]
        require(name in cases and name not in seen, f"unknown or repeated receipt case: {name}")
        seen.add(name)
        require(attempt["case_sha256"] == fingerprint(cases[name]), f"{name}: stale receipt")
        require(attempt["status"] in {"completed", "error", "timeout"}, f"{name}: invalid status")
        require(isinstance(attempt["review_text"], str) and text(attempt["review_reference"]), name)
        require(type(attempt["blocked"]) is bool or attempt["blocked"] is None, name)
        findings = attempt["findings"]
        ids = {f["id"] for f in findings}
        require(len(ids) == len(findings) and all(text(i) for i in ids), f"{name}: finding ids")
        require(all(text(f["claim"]) for f in findings), f"{name}: empty finding")
        judgments = attempt["judgments"]
        if attempt["status"] != "completed":
            require(text(attempt["error"]) and not judgments, f"{name}: incomplete review graded")
            continue
        require(attempt["error"] is None and text(attempt["review_text"]), name)
        known = {d["id"] for d in cases[name]["expected"]["defects"]}
        require(
            len(judgments) == len(known) and {j["defect_id"] for j in judgments} == known,
            f"{name}: every known defect needs one semantic judgment",
        )
        for judgment in judgments:
            require(type(judgment["detected"]) is bool and text(judgment["reason"]), name)
            matches = judgment["finding_ids"]
            require(isinstance(matches, list) and set(matches) <= ids, f"{name}: invalid match")
            require(bool(matches) == judgment["detected"], f"{name}: detection needs evidence")


def wilson(successes: int, total: int, confidence: float) -> tuple[float, float] | None:
    """Wilson score interval, statsmodels proportion_confint(method='wilson')."""
    require(
        type(successes) is int and type(total) is int and 0 <= successes <= total,
        "invalid binomial counts",
    )
    require(0 < confidence < 1, "invalid confidence")
    if not total:
        return None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(successes: int, total: int, confidence: float) -> dict:
    interval = wilson(successes, total, confidence)
    return {
        "numerator": successes,
        "denominator": total,
        "rate": successes / total if total else None,
        "wilson_interval": list(interval) if interval else None,
        "wilson_half_width": (interval[1] - interval[0]) / 2 if interval else None,
    }


def score(receipt: dict, cases: dict[str, dict], params: dict) -> dict:
    validate_receipt(receipt, cases)
    attempts = {a["case_id"]: a for a in receipt["attempts"]}
    detected = opportunities = blocks = control_decisions = failures = 0
    rows = []
    for name, case in cases.items():
        attempt = attempts.get(name)
        defects = case["expected"]["defects"]
        judgments = {j["defect_id"]: j["detected"] for j in attempt["judgments"]} if attempt else {}
        complete = attempt is not None and attempt["status"] == "completed"
        detections = {
            d["id"]: judgments[d["id"]] if complete else False if attempt else None for d in defects
        }
        if attempt:
            opportunities += len(defects)  # failed attempts count as misses, never successes
            detected += sum(value is True for value in detections.values())
            failures += not complete
            if case["expected"]["false_block_control"] and attempt["blocked"] is not None:
                control_decisions += 1
                blocks += attempt["blocked"]
        rows.append(
            {
                "case_id": name,
                "status": attempt["status"] if attempt else "unattempted",
                "detected": detections,
                "blocked": attempt["blocked"] if attempt else None,
                "false_block_control": case["expected"]["false_block_control"],
            }
        )
    metrics = {
        "kddr": rate(detected, opportunities, params["confidence"]),
        "false_block_rate": rate(blocks, control_decisions, params["confidence"]),
        "coverage_failure_rate": rate(failures, len(attempts), params["confidence"]),
    }
    missing = sorted(set(cases) - attempts.keys())
    stops = []
    if missing:
        stops.append(f"{len(missing)} cases unattempted; absent receipts are unavailable")
    for name, metric in metrics.items():
        if metric["rate"] is None:
            stops.append(f"{name}: unavailable (zero denominator)")
        elif metric["wilson_half_width"] > params["max_wilson_half_width"]:
            bound = 100 * params["max_wilson_half_width"]
            stops.append(f"{name}: Wilson half-width exceeds {bound:g} percentage points")
    if receipt["kind"] == "historical":
        stops.append("retrospective evidence; no blind evaluation or model comparison")
    if any(value == "unavailable" for value in receipt["reviewer"].values()):
        stops.append("reviewer metadata unavailable; no attributable performance conclusion")
    return {
        "receipt_id": receipt["id"],
        "kind": receipt["kind"],
        "reviewer": receipt["reviewer"],
        "adjudicator": receipt["adjudicator"],
        "metrics": metrics,
        "cases": rows,
        "unattempted_cases": missing,
        "controls_without_block_decision": sum(
            r["false_block_control"] and r["status"] != "unattempted" and r["blocked"] is None
            for r in rows
        ),
        "stop_reasons": stops,
    }


def evaluate(directory: Path) -> dict:
    params = load_parameters(directory)
    cases = load_cases(directory, params)
    receipts = directory / "receipts"
    require(receipts.is_dir(), "receipt directory is missing")
    cohorts = [score(read_json(path), cases, params) for path in sorted(receipts.glob("*.json"))]
    require(len({c["receipt_id"] for c in cohorts}) == len(cohorts), "duplicate receipt id")
    controls = sum(c["expected"]["false_block_control"] for c in cases.values())
    return {
        "schema_version": "1.1",
        "status": "validated",
        "receipt_only": True,
        "model_execution": False,
        "required_check": False,
        "parameters": params,
        "case_count": len(cases),
        "known_defect_cases": len(cases) - controls,
        "control_count": controls,
        "receipt_count": len(cohorts),
        "cohorts": cohorts,
    }


def markdown(report: dict) -> str:
    lines = [
        "<!-- review-eval-receipt -->",
        "# Review evaluation receipts",
        "",
        "Receipt only: offline corpus validation and committed semantic judgments. "
        "No model executes in CI. This is not a required check and cannot block PRs.",
        "",
    ]
    if report["status"] != "validated":
        return "\n".join([*lines, "Corpus/receipt validation failed: " + report["error"], ""])
    lines += [
        f"Cases: {report['case_count']} ({report['known_defect_cases']} known-defect, "
        f"{report['control_count']} clean controls). Receipts: {report['receipt_count']}.",
        "Cohorts and failed attempts are retained separately; no pooled reviewer score.",
        "",
    ]
    if not report["cohorts"]:
        lines += ["No reviews recorded: all rates and intervals are unavailable.", ""]
    for cohort in report["cohorts"]:
        reviewer = cohort["reviewer"]
        lines += [
            f"## {cohort['receipt_id']} ({cohort['kind']})",
            "",
            f"Reviewer: {reviewer['family']}; runtime: {reviewer['runtime']}; "
            f"model: {reviewer['model']}; effort: {reviewer['effort']}.",
            "",
            f"| Metric | Count | Rate | Wilson {report['parameters']['confidence']:.0%} interval |",
            "|---|---:|---:|---:|",
        ]
        for name, metric in cohort["metrics"].items():
            n, d = metric["numerator"], metric["denominator"]
            value, interval = metric["rate"], metric["wilson_interval"]
            estimate = "unavailable" if value is None else f"{value:.1%}"
            bounds = "unavailable" if interval is None else f"{interval[0]:.1%}-{interval[1]:.1%}"
            lines.append(f"| {name} | {n}/{d} | {estimate} | {bounds} |")
        lines += [
            "",
            "Interpretation stopped: " + "; ".join(cohort["stop_reasons"])
            if cohort["stop_reasons"]
            else "Receipt complete; advisory evidence only.",
            "",
            "| Case | Status | Known defects detected | Blocked |",
            "|---|---|---|---|",
        ]
        for row in cohort["cases"]:
            hits = ", ".join(f"{k}={v}" for k, v in row["detected"].items()) or "clean control"
            lines.append(f"| {row['case_id']} | {row['status']} | {hits} | {row['blocked']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT)
    parser.add_argument("--check", action="store_true", help="validate offline; never run a model")
    utility = parser.add_mutually_exclusive_group()
    utility.add_argument("--case-hash", metavar="ID", help="print the canonical receipt binding")
    utility.add_argument("--review-input", metavar="ID", help="emit input with ground truth hidden")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    try:
        if args.case_hash or args.review_input:
            cases = load_cases(args.corpus, load_parameters(args.corpus))
            case = cases[args.case_hash or args.review_input]
            if args.case_hash:
                print(fingerprint(case))
            else:
                print(
                    json.dumps(
                        {
                            "case_sha256": fingerprint(case),
                            "repository": case["source"]["repository"],
                            "commit": case["source"]["commit"],
                            "input": case["input"],
                        },
                        indent=2,
                    )
                )
            return 0
        report = evaluate(args.corpus)
        result = 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        report = {"status": "invalid", "receipt_only": True, "error": str(error)}
        result = 1
    encoded = json.dumps(report, indent=2) + "\n"
    if args.json_output:
        args.json_output.write_text(encoded)
    if args.markdown_output:
        args.markdown_output.write_text(markdown(report))
    if not args.json_output and not args.markdown_output:
        print(encoded, end="")
    return result


if __name__ == "__main__":
    sys.exit(main())

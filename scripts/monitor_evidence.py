"""L6 evidence-integrity collector: resolve every manifest proof reference.

Sources: github/issue-metrics@v5.0.3
(`671528652402b9b8a33da44b5c693b3161bc090f`) for the scoreboard contract;
`tests/repo/test_budgets.py` for the budgets; `src/sextant/validation/trials.py`
for the TrialLog witness. Every proof reference in `docs/manifest.md` must name an
existing test module and function, so a picked practice cannot outlive its proof.

This collector is offline by default: it reads the checkout and `git log`, writes
local JSON, and only posts to a loopback OTLP endpoint when asked. A missing
witness or report is `UNAVAILABLE`, never zero: zero would look like a measured
success and would hide that the evidence never existed.
"""

from __future__ import annotations

import argparse
import ast
import http.client
import json
import re
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

OTLP_ENDPOINT = "http://127.0.0.1:4318"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}")
CODE_SPAN = re.compile(r"`([^`]+)`")
BARE_TEST = re.compile(r"\b(test_[A-Za-z0-9_]+)(?:\[([^\]]+)\])?")
FUNCTION_REF = re.compile(r"^(test_[A-Za-z0-9_]+)(?:\[([^\]]+)\])?$")
MODULE_NAME = re.compile(r"^(?:[\w.-]+/)*test_[A-Za-z0-9_]+\.py$")
BUILTIN = re.compile(r"^(?:tests/)?(?:proofs|repo|host)/")

# tests/repo/test_budgets.py hardcodes these; it exposes no constants to import.
BUDGETS = {
    "src_lines": ("src/**/*.py", 26_500, "lines"),
    "justfile_lines": ("justfile", 105, "lines"),
    "agent_docs_lines": (("AGENTS.md", "CLAUDE.md"), 120, "lines"),
    "design_lines": ("docs/design.md", 220, "lines"),
    "practices_lines": ("docs/handbook/practices.md", 80, "lines"),
    "adr_count": ("docs/adr/*.md", 30, "files"),
    "adr_lines": ("docs/adr/*.md", 80, "lines"),
    "research_count": ("docs/research/*.md", 30, "files"),
    "lane_readme_lines": ("lanes/*/README.md", 60, "lines"),
}

# A recursive source budget measures the whole tree; per-file budgets take the max.
TOTAL_BUDGETS = frozenset({"src_lines"})


@dataclass(frozen=True)
class Row:
    line: int
    name: str
    source: str
    applied: str
    proof: str


@dataclass(frozen=True)
class Ref:
    row_line: int
    raw: str
    module: str | None
    function: str | None
    param: str | None
    kind: str


@dataclass
class TestModule:
    path: Path
    functions: set[str] = field(default_factory=set)


def split_table_row(line: str) -> list[str] | None:
    """Split one markdown table row, ignoring pipes inside backtick code spans."""
    stripped = line.rstrip("\n")
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    body = stripped[1:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    for character in body:
        if character == "`":
            in_code = not in_code
            current.append(character)
        elif character == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def parse_manifest(path: Path) -> list[Row]:
    """Every four-cell data row of docs/manifest.md, with its 1-based line."""
    rows: list[Row] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        cells = split_table_row(line)
        if cells is None or len(cells) != 4:
            continue
        name = cells[0].strip("` ").strip()
        if not name or name.lower() == "practice or pick" or TABLE_SEPARATOR.match(line):
            continue
        if set(cells[0]) <= {"-", ":", " "}:
            continue
        rows.append(
            Row(
                line=number,
                name=name,
                source=cells[1],
                applied=cells[2],
                proof=cells[3],
            )
        )
    return rows


def _module_token(token: str) -> str | None:
    cleaned = token.strip().strip("`").strip()
    if "::" in cleaned:
        left = cleaned.split("::", 1)[0].strip()
        return left if MODULE_NAME.match(left) else None
    if MODULE_NAME.match(cleaned):
        return cleaned
    return None


def _function_match(token: str) -> tuple[str, str | None] | None:
    cleaned = token.strip().strip("`").strip()
    if cleaned.startswith("::"):
        cleaned = cleaned[2:]
    match = FUNCTION_REF.match(cleaned)
    if not match:
        return None
    return match.group(1), match.group(2)


def _refs_from_tokens(proof: str, row_line: int) -> list[Ref]:
    refs: list[Ref] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    last_module: str | None = None

    def add(
        raw: str,
        module: str | None,
        function: str | None,
        param: str | None,
        kind: str,
    ) -> None:
        key = (module, function, param)
        if key in seen:
            return
        seen.add(key)
        refs.append(Ref(row_line, raw, module, function, param, kind))

    def add_bare_text(text: str, module: str | None) -> None:
        for match in BARE_TEST.finditer(text):
            add(match.group(0), module, match.group(1), match.group(2), "bare_function")

    position = 0
    for span in CODE_SPAN.finditer(proof):
        add_bare_text(proof[position : span.start()], last_module)
        token = span.group(1).strip()
        position = span.end()
        if "::" in token:
            left, right = token.split("::", 1)
            left = left.strip()
            module = left if MODULE_NAME.match(left) else last_module
            function = _function_match(right)
            if function is None:
                continue
            if MODULE_NAME.match(left):
                last_module = left
            kind = "full" if module == left else "shorthand"
            add(token, module, function[0], function[1], kind)
        elif _module_token(token):
            last_module = _module_token(token)
            add(token, last_module, None, None, "module")
        else:
            function = _function_match(token)
            if function is not None:
                add(token, last_module, function[0], function[1], "backticked_function")
    add_bare_text(proof[position:], last_module)
    return refs


def extract_refs(rows: Iterable[Row]) -> list[Ref]:
    refs: list[Ref] = []
    for row in rows:
        refs.extend(_refs_from_tokens(row.proof, row.line))
    return refs


def _module_constant(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if name in targets:
                return _literal(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return _literal(node.value)
    return None


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _parametrize_ids(decorator: ast.AST, tree: ast.Module) -> list[str]:
    if not isinstance(decorator, ast.Call):
        return []
    target = decorator.func
    name = ""
    if isinstance(target, ast.Attribute):
        name = target.attr
    elif isinstance(target, ast.Name):
        name = target.id
    if name != "parametrize" or len(decorator.args) < 2:
        return []
    names = _literal(decorator.args[0])
    values = _literal(decorator.args[1])
    if values is None and isinstance(decorator.args[1], ast.Name):
        values = _module_constant(tree, decorator.args[1].id)
    if values is None:
        return []
    if isinstance(names, str):
        names = [part.strip() for part in names.split(",")]
    if not isinstance(names, (list, tuple)) or not isinstance(values, (list, tuple)):
        return []
    ids: list[str] = []
    for value in values:
        parts = value if isinstance(value, (list, tuple)) else [value]
        if not parts:
            # An empty parameter tuple/list carries no pytest id; skip it
            # instead of indexing past the end of the value.
            continue
        if len(names) == 1:
            ids.append(str(parts[0]))
        elif len(parts) == len(names):
            ids.append("-".join(str(part) for part in parts))
    return ids


def enumerate_tests(tests_root: Path) -> dict[Path, TestModule]:
    """AST-enumerate every test function and parametrized id under tests/."""
    modules: dict[Path, TestModule] = {}
    if not tests_root.exists():
        return modules
    for path in sorted(tests_root.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        module = TestModule(path=path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            module.functions.add(node.name)
            for decorator in node.decorator_list:
                for param_id in _parametrize_ids(decorator, tree):
                    module.functions.add(f"{node.name}[{param_id}]")
        modules[path] = module
    return modules


def _module_candidates(root: Path, module: str, modules: Mapping[Path, TestModule]) -> list[Path]:
    direct = root / module
    if direct in modules:
        return [direct]
    basename = Path(module).name
    return sorted(path for path in modules if path.name == basename)


def resolve(manifest: Path, tests_root: Path) -> dict[str, Any]:
    rows = parse_manifest(manifest)
    refs = extract_refs(rows)
    modules = enumerate_tests(tests_root)
    root = manifest.parent.parent
    by_function: dict[str, set[Path]] = {}
    for path, module in modules.items():
        for function in module.functions:
            by_function.setdefault(function.split("[", 1)[0], set()).add(path)
    by_function = {name: sorted(paths) for name, paths in by_function.items()}
    unparsed = 0
    missing_functions = 0
    missing_modules = 0
    ambiguous = 0
    resolved = 0
    by_suite: dict[str, int] = {}
    problems: list[dict[str, Any]] = []
    for ref in refs:
        module_path: Path | None = None
        if ref.module:
            candidates = _module_candidates(root, ref.module, modules)
            if not candidates:
                missing_modules += 1
                problems.append(
                    {"line": ref.row_line, "ref": ref.raw, "problem": "module not found"}
                )
                continue
            if len(candidates) > 1 and ref.function is not None:
                candidates = [
                    path for path in candidates if ref.function in modules[path].functions
                ]
            if len(candidates) == 1:
                module_path = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                resolved += 1
                continue
            elif ref.function is None:
                ambiguous += 1
                resolved += 1
                continue
            else:
                module_path = None
        if ref.function is None:
            resolved += 1
            continue
        qualified = f"{ref.function}[{ref.param}]" if ref.param else ref.function
        if module_path is not None and qualified not in modules[module_path].functions:
            global_candidates = by_function.get(ref.function, [])
            if len(global_candidates) == 1:
                module_path = global_candidates[0]
        if module_path is None:
            candidates = by_function.get(ref.function, [])
            if len(candidates) == 1:
                module_path = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                resolved += 1
                continue
            else:
                unparsed += 1
                problems.append(
                    {"line": ref.row_line, "ref": ref.raw, "problem": "unresolved function"}
                )
                continue
        suite = "tests"
        try:
            relative = module_path.relative_to(root)
            if len(relative.parts) > 1:
                suite = relative.parts[1]
        except ValueError:
            pass
        by_suite[suite] = by_suite.get(suite, 0) + 1
        if qualified not in modules[module_path].functions:
            missing_functions += 1
            problems.append({"line": ref.row_line, "ref": ref.raw, "problem": "function not found"})
            continue
        resolved += 1
    return {
        "manifest": str(manifest),
        "rows": len(rows),
        "refs": len(refs),
        "resolved": resolved,
        "unparsed": unparsed,
        "missing_functions": missing_functions,
        "missing_modules": missing_modules,
        "ambiguous": ambiguous,
        "by_suite": dict(sorted(by_suite.items())),
        "test_modules": len(modules),
        "problems": problems,
    }


def doc_ages(root: Path, now: datetime | None = None) -> dict[str, Any]:
    """Last commit timestamp per ADR and research note, from one git log call."""
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                "--format=%ct",
                "--name-only",
                "--",
                "docs/adr",
                "docs/research",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "UNAVAILABLE", "error": str(error)[:300]}
    if completed.returncode != 0:
        return {"status": "UNAVAILABLE", "error": completed.stderr.strip()[:300]}
    stamps: dict[str, int] = {}
    current: int | None = None
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            current = int(stripped)
        elif current is not None and stripped not in stamps:
            stamps[stripped] = current
    moment = now or datetime.now(UTC)
    ages: dict[str, float] = {}
    for relative, timestamp in stamps.items():
        ages[relative] = round((moment.timestamp() - timestamp) / 86400, 2)
    return {"status": "OK", "ages_days": dict(sorted(ages.items())), "files": len(ages)}


def _expand(root: Path, pattern: str) -> list[Path]:
    return sorted(root.glob(pattern))


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def budget_utilization(root: Path) -> dict[str, Any]:
    """The same hardcoded budgets as tests/repo/test_budgets.py, as utilization."""
    results: dict[str, Any] = {}
    for key, (pattern, limit, unit) in BUDGETS.items():
        if isinstance(pattern, tuple):
            value = sum(_line_count(root / name) for name in pattern if (root / name).exists())
        else:
            paths = _expand(root, pattern)
            if unit == "files":
                value = len(paths)
            elif key in TOTAL_BUDGETS:
                value = sum(_line_count(path) for path in paths)
            else:
                value = max((_line_count(path) for path in paths), default=0)
        results[key] = {
            "value": value,
            "limit": limit,
            "unit": unit,
            "utilization": round(value / limit, 4),
        }
    return results


def trial_ledger(root: Path) -> dict[str, Any]:
    """TrialLog witness summary; UNAVAILABLE when the Parquet has not been written."""
    path = root / "reports/research/trials.parquet"
    if not path.exists():
        return {
            "status": "UNAVAILABLE",
            "path": str(path.relative_to(root)),
            "reason": "witness file absent",
        }
    try:
        import pyarrow.parquet as parquet

        metadata = parquet.ParquetFile(path).metadata
        return {
            "status": "OK",
            "path": str(path.relative_to(root)),
            "rows": metadata.num_rows,
            "columns": list(metadata.schema.names),
        }
    except Exception as error:
        return {
            "status": "UNAVAILABLE",
            "path": str(path.relative_to(root)),
            "reason": type(error).__name__,
        }


def build_summary(root: Path) -> dict[str, Any]:
    evidence = resolve(root / "docs/manifest.md", root / "tests")
    return {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "network": "disabled",
        "evidence": evidence,
        "doc_ages": doc_ages(root),
        "budgets": budget_utilization(root),
        "trial_ledger": trial_ledger(root),
    }


def is_loopback_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and parts.hostname in LOOPBACK_HOSTS
        and parts.username is None
        and parts.password is None
    )


def _attribute(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _gauges(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = summary.get("evidence", {})
    metrics: list[tuple[str, str, float, dict[str, str]]] = [
        ("sextant_manifest_rows", "rows", float(evidence.get("rows", 0)), {}),
        ("sextant_manifest_proof_refs", "refs", float(evidence.get("refs", 0)), {}),
        ("sextant_manifest_unparsed", "refs", float(evidence.get("unparsed", 0)), {}),
        (
            "sextant_manifest_missing_functions",
            "functions",
            float(evidence.get("missing_functions", 0)),
            {},
        ),
        (
            "sextant_manifest_missing_modules",
            "modules",
            float(evidence.get("missing_modules", 0)),
            {},
        ),
    ]
    for key, budget in summary.get("budgets", {}).items():
        metrics.append(
            (
                "sextant_budget_utilization",
                "ratio",
                float(budget.get("utilization", 0)),
                {"budget": key},
            )
        )
    for path, age in summary.get("doc_ages", {}).get("ages_days", {}).items():
        metrics.append(("sextant_doc_age_days", "days", float(age), {"document": path}))
    ledger = summary.get("trial_ledger", {})
    if ledger.get("status") == "OK":
        metrics.append(("sextant_trial_ledger_rows", "rows", float(ledger.get("rows", 0)), {}))
    now = str(time.time_ns())
    return [
        {
            "name": name,
            "unit": unit,
            "gauge": {
                "dataPoints": [
                    {
                        "asDouble": value,
                        "timeUnixNano": now,
                        "attributes": [
                            _attribute(key, item) for key, item in sorted(attrs.items())
                        ],
                    }
                ]
            },
        }
        for name, unit, value, attrs in metrics
    ]


def otlp_payload(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", "sextant-monitor-l6"),
                        _attribute("telemetry.sdk.language", "python"),
                    ]
                },
                "scopeMetrics": [
                    {"scope": {"name": "sextant.monitor.evidence"}, "metrics": _gauges(summary)}
                ],
            }
        ]
    }


def post_otlp(endpoint: str, payload: Mapping[str, Any]) -> int:
    if not is_loopback_url(endpoint):
        raise ValueError(f"OTLP endpoint must be loopback http, got {endpoint!r}")
    parts = urlsplit(endpoint)
    connection = http.client.HTTPConnection(
        parts.hostname or "127.0.0.1", parts.port or 4318, timeout=3
    )
    connection.request(
        "POST",
        parts.path or "/v1/metrics",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    status = response.status
    connection.close()
    if status >= 300:
        raise RuntimeError(f"OTLP endpoint returned HTTP {status}")
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize manifest/proof evidence once.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--otlp", action="store_true")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    summary = build_summary(args.root)
    evidence = summary["evidence"]
    if args.otlp:
        try:
            post_otlp(OTLP_ENDPOINT, otlp_payload(summary))
        except (OSError, RuntimeError, ValueError) as error:
            summary["otlp_error"] = str(error)[:300]
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.fail_on_error and (
        evidence["unparsed"] or evidence["missing_functions"] or evidence["missing_modules"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

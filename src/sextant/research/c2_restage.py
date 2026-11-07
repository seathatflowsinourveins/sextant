"""Re-stage the C2 outcome hand-off in the ledger inbox's shape.

The ledger's TrialLog stores ``daily_net_returns`` and ``condition_returns``
as float64 JSON numbers (``src/sextant/validation/trials.py:71`` calls
``math.isfinite`` on them); ``result`` must stay float-free with the exact
Decimal strings. Hold-flat rows have no position and no fill, so their
``result.kind`` is ``no-position``, matching C1's trials 157/163/169.

This rewrites those two series and the hold-flat kind in place under
``~/sextant-data/scenario-130/c2/outcome`` and writes a fresh manifest.
It never re-runs an arm and never touches ``result`` numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

DEFAULT = Path.home() / "sextant-data" / "scenario-130" / "c2" / "outcome"


def _numbers(values: list[str]) -> list[float]:
    return [float(Decimal(value)) for value in values]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    directory = Path(args.dir).expanduser()
    rows = [
        json.loads(line)
        for line in (directory / "rows.jsonl").read_text().splitlines()
        if line.strip()
    ]

    for row in rows:
        row["daily_net_returns"] = _numbers(row["daily_net_returns"])
        row["condition_returns"] = {
            key: _numbers(values) for key, values in row["condition_returns"].items()
        }
        if row["result"]["arm"] == "hold-flat":
            row["result"]["kind"] = "no-position"

    body = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    rows_sha256 = hashlib.sha256(body).hexdigest()

    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["count"] = len(rows)
    manifest["rows_sha256"] = rows_sha256
    manifest_body = (
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    ).encode()
    manifest_sha256 = hashlib.sha256(manifest_body).hexdigest()

    if not args.dry_run:
        (directory / "rows.jsonl").write_bytes(body)
        (directory / "manifest.json").write_bytes(manifest_body)

    print(f"rows_sha256 {rows_sha256}")
    print(f"manifest_sha256 {manifest_sha256}")
    print(f"count {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The `sextant.ledger.handoff/1` inbox batch: one writer for every arm.

The inbox (#102) is `<lane>-<issue>/<attempt>/<reserve|outcome>/` with `rows.jsonl` — canonical
finite JSON, one row per line — and a `manifest.json` that binds lane, issue, kind, count and the
rows' SHA-256. #110's `sextant.validation.ledger.apply_handoff` is the reader; this module only
writes a fresh directory and returns both receipts.

`indent` is the recorded shape of a batch, not a style choice: #141's reservation and outcome
manifests are compact, while #130's outcome manifest is two-space indented (220 bytes,
`acb54f78…`). One serializer carries both byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def write_batch(
    directory: Path,
    kind: str,
    rows: list[dict[str, Any]],
    *,
    lane: str,
    issue: int,
    indent: int | None = None,
) -> dict[str, str]:
    """Write one handoff batch into a new directory and return both SHA-256 receipts."""
    directory.mkdir(parents=True, exist_ok=False)
    raw = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows).encode()
    (directory / "rows.jsonl").write_bytes(raw)
    manifest = {
        "format": "sextant.ledger.handoff/1",
        "lane": lane,
        "issue": issue,
        "kind": kind,
        "count": len(rows),
        "rows_sha256": hashlib.sha256(raw).hexdigest(),
        "tier": "MODELED",
    }
    data = (json.dumps(manifest, sort_keys=True, indent=indent) + "\n").encode()
    (directory / "manifest.json").write_bytes(data)
    return {
        "rows_sha256": manifest["rows_sha256"],
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
    }

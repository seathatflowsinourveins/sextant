import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

root = Path("/mnt/wsl/ns-scanner/scanner/snapshots")
rows = []
for day in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"):
    paths = sorted(p for p in (root / day).iterdir() if p.name.endswith((".json", ".json.gz")))
    boundary = day.replace("-", "") + "T143600"
    before = [p for p in paths if p.name[:15] < boundary]
    after = [p for p in paths if p.name[:15] >= boundary]
    for path in before[-1:] + after[:1]:
        raw = path.read_bytes()
        doc = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
        span = datetime.fromisoformat(doc["generated_at"]) - datetime.fromisoformat(doc["as_of"])
        rows.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "symbols": len(doc["symbols"]),
                "as_of": doc["as_of"],
                "generated_at": doc["generated_at"],
                "as_of_to_generated_at_us": (span.days * 86400 + span.seconds) * 1000000
                + span.microseconds,
                "missing_top_level_clocks": [
                    k
                    for k in ("published_at", "received_at", "capture_completed_at", "known_at")
                    if k not in doc
                ],
            }
        )
print(
    json.dumps(
        {"label": "PARTIAL OBSERVATIONAL WITNESS; not capture-to-receipt latency", "rows": rows},
        sort_keys=True,
        indent=2,
    )
)

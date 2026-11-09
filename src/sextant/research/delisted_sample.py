"""Pre-register #42's independent delisted sample from SEC EDGAR Form 25-NSE; checks nothing.

Lead, #42 (2026-11-06): Form 25-NSE common-stock filings 2016-10 to 2025-12, a fixed seed,
N=40; "at least 95%" is 38 of 40. The list, its rule and its SHA-256 are posted before any
check against the master.
- Quarters, form.idx reader and cache-off client under EDGAR_IDENTITY: EdgarTools as main adopts
  it (lanes/research/edgartools.md), dgunning/edgartools@9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d
  edgar/dates.py, edgar/_filings.py, edgar/httprequests.py, tests/conftest.py. A row's file is
  edgar/data/<its CIK>/<accession>.txt (https://www.sec.gov/os/accessing-edgar-data, 2026-11-06).
- Form 25 tags and rule provisions: northstar-trading@455e8f0bd36538e1dcab5a29f9aedaaf273124e1:
  docs/research/2026-10-21-point-in-time-universe-sources.md; 17 CFR 240.12d2-2. Pacing, 2/s:
  northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa catalysts/sources/sec_edgar.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

BASE = "https://www.sec.gov/Archives/"
PER_SECOND = 2
FORM = "25-NSE"
WINDOW = (date(2016, 10, 1), date(2025, 12, 31))
SEED = 20261106  # Fixed before the draw; the registration date (#42).
N = 40
# Selection rule, fixed before the draw: the class names common stock or common shares and is
# none of the other classes a Form 25 can carry.
COMMON = re.compile(r"\bcommon\b", re.I)
OTHER = re.compile(
    r"preferred|warrant|right|\bunits?\b|note|debenture|depositary|\bbond|trust preferred", re.I
)
Fetch = Callable[[str], bytes]


def quarters(start: date, end: date) -> list[str]:
    from edgar.dates import filing_date_to_year_quarters

    pairs = filing_date_to_year_quarters(f"{start}:{end}")
    return [f"edgar/full-index/{year}/QTR{quarter}/form.idx" for year, quarter in pairs]


def parse_index(body: bytes) -> list[dict[str, str]]:
    from edgar._filings import read_form_index_file

    return [
        {
            "company": row["company"],
            "cik": str(row["cik"]),
            "filed": row["filing_date"].isoformat(),
            "path": f"edgar/data/{row['cik']}/{row['accession_number']}.txt",
        }
        for row in read_form_index_file(body.decode("latin-1")).to_pylist()
        if row["form"] == FORM
    ]


def _tag(text: str, name: str) -> str | None:
    match = re.search(rf"<(?:\w+:)?{name}>\s*(.*?)\s*</(?:\w+:)?{name}>", text, re.S | re.I)
    return re.sub(r"\s+", " ", match[1]) if match else None


def is_common(description: str | None) -> bool:
    return bool(description and COMMON.search(description) and not OTHER.search(description))


def draw(fetch: Fetch, raw: Path) -> dict[str, Any]:
    raw.mkdir(parents=True, exist_ok=False)
    indexes, candidates = [], []
    for path in quarters(*WINDOW):
        body = fetch(path)
        indexes.append({"path": path, "sha256": hashlib.sha256(body).hexdigest()})
        candidates += [
            row
            for row in parse_index(body)
            if WINDOW[0] <= date.fromisoformat(row["filed"]) <= WINDOW[1]
        ]
    # form.idx lists a 25-NSE under both the subject issuer and the filing exchange: one per filing.
    # The same accession file sits under each CIK's directory, so key by accession number.
    unique: dict[str, dict[str, str]] = {}
    for row in sorted(candidates, key=lambda r: r["path"]):
        unique.setdefault(row["path"].rsplit("/", 1)[-1], row)
    order = [unique[name] for name in sorted(unique)]
    random.Random(SEED).shuffle(order)  # noqa: S311 - a reproducible draw, not a secret
    drawn, skipped = [], []
    for row in order:
        if len(drawn) == N:
            break
        body = fetch(row["path"])
        text = body.decode("utf-8", "replace")
        name = row["path"].rsplit("/", 1)[-1]
        (raw / name).write_bytes(body)
        issuer = re.search(r"<issuer>(.*?)</issuer>", text, re.S | re.I)
        block = issuer[1] if issuer else ""
        entry = {
            "filed": row["filed"],
            "path": row["path"],
            "issuer_cik": _tag(block, "cik"),
            "issuer_name": _tag(block, "entityName"),
            "accession": name.removesuffix(".txt"),
            "class": _tag(text, "descriptionClassSecurity"),
            "rule_provision": _tag(text, "ruleProvision"),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        (drawn if is_common(entry["class"]) else skipped).append(entry)
    if len(drawn) != N:
        raise ValueError(f"Only {len(drawn)} common-stock filings in the window")
    return {
        "issue": 42,
        "source": "SEC EDGAR full-index form.idx, Form 25-NSE",
        "window": [d.isoformat() for d in WINDOW],
        "seed": SEED,
        "n": N,
        "pass_at_least": 38,
        "rule": {
            "common": COMMON.pattern,
            "excluded": OTHER.pattern,
            "order": "unique accession number",
            "issuer": "<issuer> block",
        },
        "candidates": len(unique),
        "index_rows": len(candidates),
        "indexes": indexes,
        "walked": len(drawn) + len(skipped),
        "skipped_non_common": [{k: s[k] for k in ("accession", "class")} for s in skipped],
        "sample": drawn,
    }


def sec_fetch() -> Fetch:
    if not os.environ.get("EDGAR_IDENTITY"):
        raise SystemExit("Set EDGAR_IDENTITY, the documented SEC contact, before any request")
    from edgar import httpclient
    from edgar.httprequests import get_with_retry

    httpclient.close_clients()
    httpclient.HTTP_MGR = httpclient.get_http_mgr(
        cache_enabled=False, request_per_sec_limit=PER_SECOND
    )

    def fetch(path: str) -> bytes:
        response = get_with_retry(BASE + path)
        response.raise_for_status()
        return response.content

    return fetch


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-register #42's delisted sample")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    os.environ["EDGAR_LOCAL_DATA_DIR"] = str(args.output / "edgar")  # Task-owned, before import.
    registration = draw(sec_fetch(), args.output / "raw")
    body = (json.dumps(registration, indent=2, sort_keys=True) + "\n").encode()
    (args.output / "registration.json").write_bytes(body)
    print(hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    main()

"""The ranking mode's prior closes and asset security types, as one verified data step (N2b-3).

Prior closes are exactly the display producer's (``tradingview/prestage.py``): the SIP
split-adjusted daily close of the prior XNYS session through ``AlpacaDailyBars`` on the paced
transport, refused when the universe has none, known at 16:00 New York of that session.
Security types come from the listing files main's listings job stages, checked against its
own receipt and validator, and classified by main's operating-company filter
(``tradingview/bars.py``): kept rows are "common", others "test", "etf" or "excluded"; an
absent symbol has no row. The step writes ``references.json`` and ``assets.json``, then
``manifest.json`` last with each file's sha256, the baselines' commit rule. A refusal leaves
the previous files in place. DESIGN-N2B3.md holds the cited reasoning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sextant.data.alpaca_history import Pacer
from sextant.data.baseline_recipe import MANIFEST_NAME, load_universe
from sextant.execution.state import write_atomic
from sextant.tradingview import listings
from sextant.tradingview.bars import MAX_BATCH, PacedStockBars, _keeps, parse_directory
from sextant.tradingview.prestage import (
    ASSET_SOURCE,
    REFERENCE_SOURCE,
    AlpacaDailyBars,
    _at,
    collect_references,
    prior_sessions,
)

FILES = ("references.json", "assets.json")


class InputsRefused(ValueError):
    """The step refuses; the message names the input; earlier files stay."""


class Daily(Protocol):
    def daily_closes(self, symbols: Any, *, day: date) -> dict[str, Decimal]: ...


def _listing_texts(directory: Path) -> tuple[dict[str, str], str]:
    """Both directory files, only as the listings job's receipt and validator accept them."""
    try:
        receipt = json.loads((directory / listings.RECEIPT).read_text(encoding="utf-8"))
        expected = {row["file"]: row["sha256"] for row in receipt["files"]}
        staged_at = str(receipt["staged_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InputsRefused(f"listings receipt unreadable in {directory}: {exc}") from exc
    texts = {}
    for name in listings.HEADERS:
        data = (directory / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected.get(name):
            raise InputsRefused(f"{name} does not match the listings receipt")
        listings.validate(name, data)
        texts[name] = data.decode("utf-8")
    return texts, staged_at


def _types(texts: dict[str, str], symbols: tuple[str, ...]) -> dict[str, dict[str, str]]:
    rows = {}
    for name, text in texts.items():
        status = _financial_status(text) if name == "nasdaqlisted.txt" else {}
        for listing in parse_directory(text):
            kind = (
                "common"
                if _keeps(listing)
                else "test"
                if listing.test_issue
                else "etf"
                if listing.etf
                else "excluded"
            )
            rows[listing.symbol] = {
                "security_type": kind,
                "financial_status": status.get(listing.symbol, ""),
            }
    return {name: rows[name] for name in symbols if name in rows}


def _financial_status(text: str) -> dict[str, str]:
    lines = text.splitlines()
    header = lines[0].split("|")
    symbol, column = header.index("Symbol"), header.index("Financial Status")
    return {
        fields[symbol]: fields[column]
        for fields in (line.split("|") for line in lines[1:-1])
        if len(fields) == len(header)
    }


def produce(
    out: Path, *, universe_artifact: Path, listings_dir: Path, session: date, daily: Daily
) -> dict[str, Any]:
    symbols, digest = load_universe(Path(universe_artifact))
    texts, staged_at = _listing_texts(Path(listings_dir))
    reference_day = prior_sessions(session, 1)[-1]  # PRE and RTH (prestage.py)
    names, closes = collect_references(daily, day=reference_day, symbols=symbols)  # type: ignore[arg-type]
    known_at = _at(reference_day, 16)
    common = {
        "session": session.isoformat(),
        "reference_session": reference_day.isoformat(),
        "known_at": known_at,
        "universe_sha256": digest["sha256"],
    }
    bodies = {
        "references.json": {
            **common,
            "source": REFERENCE_SOURCE,
            "closes": {name: format(closes[name], "f") for name in names},
        },
        "assets.json": {
            **common,
            "source": f"{ASSET_SOURCE}; listings "
            + " / ".join(listings.creation_time(text) for text in texts.values()),
            "types": _types(texts, tuple(symbols)),
        },
    }
    out = Path(out)
    # No row bounds a listings receipt's age yet; its time is recorded (lead ruling 03:08).
    manifest: dict[str, Any] = {
        "session": session.isoformat(),
        "listings_staged_at": staged_at,
        "files": {},
    }
    for name in FILES:
        write_atomic(out / name, bodies[name])
        raw = (out / name).read_bytes()
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest()}
    write_atomic(out / MANIFEST_NAME, manifest)  # last: the commit record
    return manifest


def _calls_per_minute(path: Path) -> Decimal:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["rows"]
    return Decimal(rows["calls_per_minute"]["value"])  # the calibration job's own ceiling


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m sextant.data.ranking_inputs", allow_abbrev=False
    )
    required = parser.add_argument_group("required")
    for flag, kind in (
        ("--out", Path),
        ("--universe-artifact", Path),
        ("--listings-dir", Path),
        ("--session", date.fromisoformat),
        ("--api-key-env", str),
        ("--api-secret-env", str),
        ("--parameters", Path),
    ):
        required.add_argument(flag, type=kind, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = parse(argv)
    try:
        key, secret = os.environ[raw.api_key_env], os.environ[raw.api_secret_env]
    except KeyError as missing:
        raise InputsRefused(f"credential environment variable {missing} is not set") from None
    client = PacedStockBars(
        pacer=Pacer(_calls_per_minute(raw.parameters)), api_key=key, secret_key=secret
    )
    produce(
        raw.out,
        universe_artifact=raw.universe_artifact,
        listings_dir=raw.listings_dir,
        session=raw.session,
        daily=AlpacaDailyBars(client, batch=MAX_BATCH),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

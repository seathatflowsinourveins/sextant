"""Row 4 dated-master acceptance (#42) over #107's raw Sharadar capture; survivor_only stays.

The tests are ADR-0002 §6, "Universe and master", as carried by ADR-0013 (Universe):
northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:docs/adr/0002-data-api-stack.md:96.
- the master covers 100% of the ten probed exits (E16, 08u.1 probe at
  northstar-trading@80535ddb8a0906dcdb9a98af196de1e8a8aea1ea);
- >= 95% of a random delisted sample from an independent list, the sample and its source fixed
  before the test (NOT_RUN here: no fixed sample exists in either 08u.1 note);
- recycled tickers: META on 2021-12-01 and BBBY across its issuers resolve to distinct master
  ids, and bars fetched with asof match the master's issuer.
Intervals come from the carried sharadar_master; ACTIONS' coverage floor follows its upstream
_bulk_actions_start rule: only a complete {"years": "10"} bulk sets it, at its first action date.
The capture is read by #107's sharadar_coverage reader, which hash- and schema-checks every page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sextant.data.sharadar_master import IntervalCoverage, SharadarMember, interval_coverage
from sextant.research.delisted_sample import is_common
from sextant.research.sharadar_coverage import _read_capture as read_capture

# ADR-0002 E16; the 08u.1 probe JSON (sha256 3f759c29...) records each name trading on this asof.
PROBE_SHA256 = "3f759c293bc33f697355fdd621abb3866043c8c5a80fb8927154da82eab3ca89"
TEN_EXITS = {
    "LNKD": "2016-06-15",
    "YHOO": "2017-01-15",
    "CELG": "2019-06-15",
    "LK": "2020-03-15",
    "TWTR": "2022-06-15",
    "SIVB": "2023-02-15",
    "BBBY": "2023-02-15",
    "FRC": "2023-02-15",
    "ATVI": "2023-06-15",
    "XLNX": "2021-06-15",
}
# ADR-0002 §6 names META on 2021-12-01 and BBBY's issuers; FB is META's issuer on that date.
RECYCLED = (
    ("META", "2021-12-01"),
    ("FB", "2021-12-01"),
    ("BBBY", "2022-06-01"),
    ("BBBY", "2025-10-01"),
)
SCOPE = "SEP+SFP"  # The META ETF is a fund; SEP alone cannot see the recycled holder.


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_capture(root: Path) -> tuple[list[dict], list[dict], date, dict[str, Any]]:
    """#107's own reader checks every raw page's SHA-256 and schema; acceptance needs the bulks."""
    receipt, queries = read_capture(root)
    if receipt.get("mode") != "authenticated":
        raise ValueError("Acceptance needs an authenticated capture, not a fixture")

    def bulk(table: str) -> tuple[dict[str, Any], list[dict]]:
        found = [
            (q, rows) for q, rows in queries if q["table"] == table and "years" in q["filters"]
        ]
        if len(found) != 1 or found[0][0]["status"] != "complete" or len(found[0][0]["pages"]) != 1:
            raise ValueError(f"{table}: exactly one complete bulk receipt is required")
        return found[0]

    (tickers_query, tickers), (actions_query, actions) = bulk("TICKERS"), bulk("ACTIONS")
    if actions_query["filters"] != {"years": "10"}:
        raise ValueError("Only the complete 10-year ACTIONS bulk sets the coverage floor")
    floor = min(date.fromisoformat(row["date"]) for row in actions)
    clocks = {
        "capture_asof": receipt["asof"],
        "capture_sha256": _sha256(root / "capture.json"),
        "tickers_sha256": tickers_query["pages"][0]["sha256"],
        "tickers_received_at": tickers_query["pages"][0]["received_at"],
        "actions_sha256": actions_query["pages"][0]["sha256"],
        "actions_received_at": actions_query["pages"][0]["received_at"],
        "actions_coverage_start": floor.isoformat(),
    }
    return tickers, actions, floor, clocks


def _row(member: SharadarMember) -> dict[str, Any]:
    return {
        "symbol": member.symbol,
        "first_date": member.first_date.isoformat(),
        "last_date": member.last_date.isoformat() if member.last_date else None,
        "exit_reason": member.exit_reason,
        "security_id": member.security_id,
        "dataset_ticker": member.dataset_ticker,
        "exchange": member.exchange,
        "end_evidence": member.end_evidence,
    }


def ten_exits(cov: IntervalCoverage) -> dict[str, Any]:
    """The probe saw each name trading on its asof; that day picks the issuer under test.

    A probe day before ACTIONS coverage falls back to a sole holder of the name, and says so.
    An empty dated lookup inside coverage stays uncovered: a later recycled issuer is not the
    issuer that traded on the probe day.
    """
    result = {}
    for name, seen in TEN_EXITS.items():
        on = date.fromisoformat(seen)
        held = [m for m in cov.intervals if m.symbol == name]
        dated = {m.security_id for m in held if m.first_date <= on <= (m.last_date or date.max)}
        if dated:
            ids = dated
        elif cov.actions_start is not None and on < cov.actions_start:
            # The fallback exists only for a membership clipped at the coverage floor. An
            # interval that starts after the probe on explicit evidence arrived later.
            ids = {
                m.security_id for m in held if m.start_evidence == "pre_coverage_listing"
            }
        else:
            ids = set()
        if len(ids) != 1:
            result[name] = {"covered": False, "reason": f"{len(ids)} share classes held {name}"}
            continue
        (security,) = ids
        rows = sorted(
            (m for m in cov.intervals if m.security_id == security), key=lambda m: m.first_date
        )
        final = rows[-1]
        result[name] = {
            "covered": final.exit_reason is not None and final.end_evidence == "explicit_action",
            "security_id": security,
            "exit_date": final.last_date.isoformat() if final.last_date else None,
            "exit_reason": final.exit_reason,
            "exit_symbol": final.symbol,
            "probe_asof": seen,
            "probe_asof_inside_interval": bool(dated),
            "intervals": [_row(m) for m in rows],
        }
    return result


def recycled(cov: IntervalCoverage) -> dict[str, Any]:
    lookups = []
    for symbol, day in RECYCLED:
        on = date.fromisoformat(day)
        hits = [
            m
            for m in cov.intervals
            if m.symbol == symbol and m.first_date <= on <= (m.last_date or date.max)
        ]
        members = [{**_row(m), "table": cov.security_metadata[m.dataset_ticker][0]} for m in hits]
        lookups.append({"symbol": symbol, "day": day, "members": members})
    holders = sorted({m.security_id for m in cov.intervals if m.symbol == "BBBY"})
    pair = [row["members"] for row in lookups if row["symbol"] in {"META", "FB"}]
    return {
        "lookups": lookups,
        "meta_fb_2021_12_01_distinct": all(len(hits) == 1 for hits in pair)
        and pair[0][0]["security_id"] != pair[1][0]["security_id"],
        "bbby_security_ids": holders,
        "bbby_issuer_count": len(holders),
        "adr_expected_bbby_issuers": 3,
        "each_lookup_resolves_one_member": all(len(row["members"]) == 1 for row in lookups),
    }


EFFECTIVE = timedelta(days=10)  # 17 CFR 240.12d2-2(d)(1): a Form 25 takes effect 10 days on.


def independent_sample(
    cov: IntervalCoverage, tickers: Sequence[dict], registration: dict[str, Any]
) -> dict[str, Any]:
    """#42's pre-registered EDGAR sample against the master, by CIK (amended criterion, #42)."""
    by_cik: dict[str, set[str]] = {}
    for row in tickers:
        found = re.search(r"CIK=(\d+)", row.get("secfilings", ""))
        if found and row["table"] in {"SEP", "SFP"}:
            by_cik.setdefault(found[1].lstrip("0"), set()).add(row["ticker"])
    finals: dict[str, SharadarMember] = {}
    for member in sorted(cov.intervals, key=lambda m: m.first_date):
        finals[member.dataset_ticker] = member
    rows = []
    for entry in registration["sample"]:
        filed = date.fromisoformat(entry["filed"])
        dataset = sorted(by_cik.get(str(entry["issuer_cik"]).lstrip("0"), set()))
        # The draw admitted common stock only; a legacy entry without a class keeps that rule.
        # Sharadar keeps one class per issuer, so identity is the CIK plus the class family: a
        # preferred or unknown class is not the common security the filing covers, while
        # fund/ETF/ETN shares are their issuers' common equity.
        common_sample = entry.get("class") is None or is_common(entry["class"])

        def exit_by_effective(
            ticker: str, filed: date = filed, common_sample: bool = common_sample
        ) -> date | None:
            final = finals.get(ticker)
            if (
                final is None
                or not common_sample
                or final.instrument_type in {"preferred", "etn", "unsupported"}
                or final.exit_reason is None
                or final.end_evidence != "explicit_action"
            ):
                return None
            return (
                final.last_date
                if final.last_date and final.last_date <= filed + EFFECTIVE
                else None
            )

        def why(ticker: str, common_sample: bool = common_sample) -> str:
            if ticker in cov.exclusions:
                return cov.exclusions[ticker]
            final = finals.get(ticker)
            if final is None:
                return "outside window"
            if not common_sample:
                return "sample class is not common stock"
            if final.instrument_type in {"preferred", "etn", "unsupported"}:
                return (
                    f"{final.instrument_type} share class ({final.security_class}) "
                    "is not the sampled common stock"
                )
            return "no explicit exit by filing + 10 days"

        exits = [finals[t] for t in dataset if exit_by_effective(t) is not None]
        best = max(exits, key=lambda m: m.last_date or date.min, default=None)
        reason = None
        if best is None:
            reason = (
                "; ".join(f"{t}: {why(t)}" for t in dataset) if dataset else "no Sharadar CIK match"
            )
        rows.append(
            {
                "accession": entry["accession"],
                "issuer_cik": entry["issuer_cik"],
                "filed": entry["filed"],
                "covered": best is not None,
                "security_id": best.security_id if best else None,
                "dataset_ticker": best.dataset_ticker if best else None,
                "exit_date": best.last_date.isoformat() if best and best.last_date else None,
                "exit_reason": best.exit_reason if best else None,
                "lag_days": (filed - best.last_date).days if best and best.last_date else None,
                "reason": reason,
            }
        )
    covered = sum(row["covered"] for row in rows)
    return {
        "status": "PASS" if covered >= registration["pass_at_least"] else "FAIL",
        "covered": covered,
        "n": len(rows),
        "pass_at_least": registration["pass_at_least"],
        "rows": rows,
    }


def members_manifest(cov: IntervalCoverage, clocks: dict[str, Any]) -> dict[str, Any]:
    """Row 11's manifest_universe shape; survivor_only stays true until every test passes."""
    return {
        **clocks,
        "source": "sharadar",
        "survivor_only": True,
        "pit_verified": False,
        "historical_known_at": None,
        "members": [
            {
                "symbol": m.symbol,
                "first_date": m.first_date.isoformat(),
                "last_date": m.last_date.isoformat() if m.last_date else None,
                "exit_reason": m.exit_reason,
                "source": "sharadar",
                "security_id": m.security_id,
                "security_class": m.security_class,
            }
            for m in cov.intervals
        ],
    }


def evaluate(
    root: Path, *, start: date, end: date, registration: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    tickers, actions, floor, clocks = load_capture(root)
    cov = interval_coverage(
        tickers, actions, start=start, end=end, actions_start=floor, scope=SCOPE
    )
    exits = ten_exits(cov)
    recycle = recycled(cov)
    sample: dict[str, Any] = {
        "status": "NOT_RUN",
        "minimum_coverage": "0.95",
        "reason": "pass --sample with #42's pre-registered registration.json",
    }
    if registration is not None:
        body = registration.read_bytes()
        sample = {
            "registration_sha256": hashlib.sha256(body).hexdigest(),
            **independent_sample(cov, tickers, json.loads(body)),
        }
    report = {
        **clocks,
        "window": [start.isoformat(), end.isoformat()],
        "scope": SCOPE,
        "probe_sha256": PROBE_SHA256,
        "coverage": cov.summary,
        "acceptance": {
            "ten_exits": {
                "status": "PASS" if all(row["covered"] for row in exits.values()) else "FAIL",
                "covered": sum(row["covered"] for row in exits.values()),
                "names": exits,
            },
            "independent_delisted_sample": sample,
            "recycled_ticker": recycle,
            "asof_bars_match_issuer": {
                "status": "NOT_RUN",
                "reason": "see the asof-prices receipt",
            },
            "replacement_backtest": {"status": "NOT_RUN"},
        },
        "survivor_only": True,
        "pit_verified": False,
    }
    return report, members_manifest(cov, clocks)


CENT = Decimal("0.01")  # Reg NMS Rule 612, 17 CFR 242.612: the $0.01 increment at or above $1.


def asof_prices(
    lookups: Sequence[dict[str, Any]],
    raw: Path,
    *,
    alpaca: Callable[[str, date], tuple[str, ...]],
    sharadar: Callable[[str, dict[str, Any]], bytes],
) -> dict[str, Any]:
    """Alpaca's asof bar for the ticker against Sharadar's close for the master's issuer."""
    from sextant.research.sharadar_client import parse_response

    raw.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, lookup in enumerate(lookups):
        (member,) = lookup["members"]
        symbol, day = lookup["symbol"], lookup["day"]
        requested = datetime.now(UTC).isoformat()
        pages = alpaca(symbol, date.fromisoformat(day))
        body = sharadar(
            member["table"],
            {"ticker": member["dataset_ticker"], "from": day, "to": day, "format": "csv"},
        )
        received = datetime.now(UTC).isoformat()
        alpaca_path, sharadar_path = raw / f"{index}-alpaca.json", raw / f"{index}-sharadar.csv"
        alpaca_path.write_text(json.dumps(list(pages)))
        sharadar_path.write_bytes(body)
        bars = [
            bar
            for page in pages
            for bar in (json.loads(page, parse_float=Decimal).get("bars") or {}).get(symbol, [])
        ]
        _, prices = parse_response(body)
        alpaca_close = Decimal(bars[0]["c"]) if len(bars) == 1 else None
        vendor_close = Decimal(prices[0]["closeunadj"]) if len(prices) == 1 else None
        same = (
            alpaca_close is not None
            and vendor_close is not None
            and alpaca_close.quantize(CENT) == vendor_close.quantize(CENT)
        )
        rows.append(
            {
                "symbol": symbol,
                "day": day,
                "master_security_id": member["security_id"],
                "master_dataset_ticker": member["dataset_ticker"],
                "alpaca_asof_close": str(alpaca_close) if alpaca_close is not None else None,
                "sharadar_closeunadj": str(vendor_close) if vendor_close is not None else None,
                "match_at_cent": same,
                "requested_at": requested,
                "received_at": received,
                "alpaca_sha256": _sha256(alpaca_path),
                "sharadar_sha256": _sha256(sharadar_path),
            }
        )
    return {
        "status": "PASS" if rows and all(row["match_at_cent"] for row in rows) else "FAIL",
        "feed": "sip",
        "adjustment": "raw",
        "rows": rows,
    }


def _write(path: Path, value: dict[str, Any]) -> str:
    body = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Row 4 dated-master acceptance (#42)")
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--sample", type=Path, help="#42's pre-registered registration.json")
    parser.add_argument(
        "--asof-prices",
        action="store_true",
        help="also fetch the recycled lookups' bars; run only through scripts/with-keys.sh",
    )
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    report, manifest = evaluate(
        args.capture, start=args.start, end=args.end, registration=args.sample
    )
    if args.asof_prices:
        from sextant.data.alpaca_history import AlpacaHistory
        from sextant.research.sharadar_client import direct_client

        history = AlpacaHistory()
        try:
            report["acceptance"]["asof_bars_match_issuer"] = asof_prices(
                report["acceptance"]["recycled_ticker"]["lookups"],
                args.output / "raw",
                alpaca=lambda symbol, day: history.fetch(symbol, day, "1day"),
                sharadar=direct_client(),
            )
        finally:
            history.close()
    report["members_manifest_sha256"] = _write(args.output / "members.json", manifest)
    report["members_manifest_rows"] = len(manifest["members"])
    print(_write(args.output / "acceptance.json", report))


if __name__ == "__main__":
    main()

"""Row 4 acceptance over a synthetic, hash-bound capture; offline, no key (#42)."""

import csv
import hashlib
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from sextant.data.universe import manifest_universe
from sextant.research import pit_acceptance as acceptance
from sextant.research.sharadar_client import SOURCE

TICKERS = (
    "table",
    "permaticker",
    "ticker",
    "exchange",
    "category",
    "relatedtickers",
    "firstpricedate",
    "lastpricedate",
    "isdelisted",
    "secfilings",
)
ACTIONS = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")


def _ticker(table: str, pt: str, symbol: str, category: str, delisted: str) -> dict[str, str]:
    return dict(
        table=table,
        permaticker=pt,
        ticker=symbol,
        exchange="NYSE",
        category=category,
        relatedtickers="",
        firstpricedate="2017-01-03",
        lastpricedate="2026-11-05",
        isdelisted=delisted,
        secfilings=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=000000{pt}",
    )


def _action(day: str, kind: str, symbol: str, contra: str = "N/A") -> dict[str, str]:
    return dict(
        date=day,
        action=kind,
        ticker=symbol,
        name="SYN",
        value="",
        contraticker=contra,
        contraname="",
    )


def _rename(day: str, symbol: str, before: str, after: str) -> list[dict[str, str]]:
    return [
        _action(day, "tickerchangefrom", symbol, before),
        _action(day, "tickerchangeto", symbol, after),
    ]


def _zip(name: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    out = io.BytesIO()
    with ZipFile(out, "w") as archive:
        archive.writestr(ZipInfo(name), text.getvalue())  # Fixed stamp: the bytes are stable.
    return out.getvalue()


def _capture(tmp_path: Path, *, years: str = "10") -> Path:
    """META is the ETF on 2021-12-01 and FB is Meta; BBBY passes between two issuers."""
    tickers = [
        _ticker("SFP", "10", "METV", "ETF", "N"),
        _ticker("SEP", "20", "META", "Domestic Common Stock", "N"),
        _ticker("SEP", "30", "BBBYQ", "Domestic Common Stock", "Y"),
        _ticker("SEP", "40", "NXH", "Domestic Common Stock", "N"),
    ]
    actions = [
        _action("2021-06-30", "listed", "METV"),
        *_rename("2022-01-31", "METV", "META", "METV"),
        _action("2017-01-03", "listed", "META"),
        *_rename("2022-06-09", "META", "FB", "META"),
        _action("2017-01-03", "listed", "BBBYQ"),
        *_rename("2023-05-02", "BBBYQ", "BBBY", "BBBYQ"),
        _action("2023-05-02", "bankruptcyliquidation", "BBBYQ"),
        _action("2017-01-03", "listed", "NXH"),
        *_rename("2025-08-29", "NXH", "OSTK", "BBBY"),
        *_rename("2026-08-17", "NXH", "BBBY", "NXH"),
    ]
    return _write_capture(tmp_path / "capture", tickers, actions, years=years)


def _write_capture(
    root: Path,
    tickers: list[dict[str, str]],
    actions: list[dict[str, str]],
    *,
    years: str = "10",
) -> Path:
    (root / "raw").mkdir(parents=True)
    queries = []
    for index, (table, name, fields, rows, filters) in enumerate(
        [
            ("TICKERS", "tickers.csv", TICKERS, tickers, {"years": "full"}),
            ("ACTIONS", "actions-10Y.csv", ACTIONS, actions, {"years": years}),
        ]
    ):
        body = _zip(name, fields, rows)
        path = f"raw/{index:06d}-00000.zip"
        (root / path).write_bytes(body)
        page = {
            "path": path,
            "sha256": hashlib.sha256(body).hexdigest(),
            "received_at": "2026-11-06T16:59:18+00:00",
            "columns": list(fields),
        }
        queries.append({"table": table, "filters": filters, "status": "complete", "pages": [page]})
    receipt = {
        "asof": "2026-11-06T16:58:52+00:00",
        "client": SOURCE,
        "mode": "authenticated",
        "queries": queries,
    }
    (root / "capture.json").write_text(json.dumps(receipt))
    return root


def _evaluate(tmp_path: Path) -> tuple[dict, dict]:
    return acceptance.evaluate(_capture(tmp_path), start=date(2016, 1, 1), end=date(2026, 11, 5))


def test_recycled_tickers_resolve_to_the_dated_issuer(tmp_path: Path) -> None:
    report, _ = _evaluate(tmp_path)
    recycled = report["acceptance"]["recycled_ticker"]
    found = {(r["symbol"], r["day"]): r["members"] for r in recycled["lookups"]}
    assert [m["security_id"] for m in found["META", "2021-12-01"]] == ["sharadar:10"]
    assert [m["security_id"] for m in found["FB", "2021-12-01"]] == ["sharadar:20"]
    assert found["META", "2021-12-01"][0]["table"] == "SFP"
    assert [m["security_id"] for m in found["BBBY", "2022-06-01"]] == ["sharadar:30"]
    assert [m["security_id"] for m in found["BBBY", "2025-10-01"]] == ["sharadar:40"]
    assert recycled["meta_fb_2021_12_01_distinct"] is True
    assert recycled["bbby_issuer_count"] == 2  # Measured, not forced to the ADR's three.


def test_acceptance_is_never_claimed_without_every_test_and_survivor_only_stays(
    tmp_path: Path,
) -> None:
    report, manifest = _evaluate(tmp_path)
    exits = report["acceptance"]["ten_exits"]
    assert exits["status"] == "FAIL" and exits["covered"] == 1  # Only BBBY is in the fixture.
    assert exits["names"]["BBBY"]["exit_reason"] == "bankruptcyliquidation"
    assert exits["names"]["LNKD"] == {"covered": False, "reason": "0 share classes held LNKD"}
    assert report["acceptance"]["independent_delisted_sample"]["status"] == "NOT_RUN"
    assert report["acceptance"]["asof_bars_match_issuer"]["status"] == "NOT_RUN"
    assert report["survivor_only"] is True and report["pit_verified"] is False
    assert manifest["survivor_only"] is True and manifest["historical_known_at"] is None


def test_members_manifest_loads_in_row_11_at_its_hash(tmp_path: Path) -> None:
    _, manifest = _evaluate(tmp_path)
    path = tmp_path / "members.json"
    digest = acceptance._write(path, manifest)
    universe = manifest_universe(path, sha256=digest, start=date(2017, 1, 3), end=date(2026, 11, 5))
    selection = universe.universe_for_date(date(2021, 12, 1))
    assert {m.symbol: m.security_id for m in selection.members}["META"] == "sharadar:10"
    assert selection.provenance.report_fields()["survivor_only"] is True


def test_tampered_raw_or_a_partial_actions_bulk_refuses(tmp_path: Path) -> None:
    root = _capture(tmp_path / "a")
    (root / "raw/000001-00000.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        acceptance.load_capture(root)
    with pytest.raises(ValueError, match="10-year"):
        acceptance.load_capture(_capture(tmp_path / "b", years="5"))


def _bars(symbol: str, close: str) -> tuple[str, ...]:
    return (json.dumps({"bars": {symbol: [{"c": float(close)}]}, "next_page_token": None}),)


def test_asof_bars_must_match_the_master_issuer_at_the_cent(tmp_path: Path) -> None:
    report, _ = _evaluate(tmp_path)
    lookups = report["acceptance"]["recycled_ticker"]["lookups"]
    prices = {"METV": "15.47", "META": "310.60", "BBBYQ": "4.31", "NXH": "9.00"}
    calls: list[tuple[str, dict]] = []

    def sharadar(table: str, params: dict) -> bytes:
        calls.append((table, params))
        return f"ticker,closeunadj\n{params['ticker']},{prices[params['ticker']]}\n".encode()

    issuer = {"META": "15.47", "FB": "310.60", "BBBY": "4.31"}
    result = acceptance.asof_prices(
        lookups,
        tmp_path / "raw",
        alpaca=lambda symbol, day: _bars(symbol, "9.001" if day.year == 2025 else issuer[symbol]),
        sharadar=sharadar,
    )
    assert result["status"] == "PASS"
    assert [c[0] for c in calls] == ["SFP", "SEP", "SEP", "SEP"]
    assert result["rows"][0]["alpaca_asof_close"] == "15.47"
    wrong = acceptance.asof_prices(
        lookups,
        tmp_path / "raw2",
        alpaca=lambda symbol, _day: _bars(symbol, "310.60"),
        sharadar=sharadar,
    )
    assert wrong["status"] == "FAIL"
    assert Decimal(wrong["rows"][0]["alpaca_asof_close"]) == Decimal("310.60")


def test_the_registered_sample_counts_an_exit_by_its_effective_date(tmp_path: Path) -> None:
    registration = {
        "pass_at_least": 2,
        "sample": [
            {"accession": "a-1", "issuer_cik": "0000000030", "filed": "2023-05-10"},
            {"accession": "a-2", "issuer_cik": "999", "filed": "2023-05-10"},
        ],
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(registration))
    report, _ = acceptance.evaluate(
        _capture(tmp_path), start=date(2016, 1, 1), end=date(2026, 11, 5), registration=path
    )
    result = report["acceptance"]["independent_delisted_sample"]
    assert (result["status"], result["covered"], result["n"]) == ("FAIL", 1, 2)
    hit, miss = result["rows"]
    assert (hit["security_id"], hit["exit_date"], hit["lag_days"]) == (
        "sharadar:30",
        "2023-05-02",
        8,
    )
    assert miss["reason"] == "no Sharadar CIK match"
    assert result["registration_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def _ten_exit_capture(tmp_path: Path) -> Path:
    """All ten probes resolve; TWTR is only a later recycled issuer with no dated member."""
    plan = {
        "LNKD": ("1101", "2010-01-01", "2016-12-16", "acquisitionby"),
        "YHOO": ("1102", "2017-01-03", "2017-06-01", "acquisitionby"),
        "CELG": ("1103", "2018-01-03", "2019-12-01", "acquisitionby"),
        "LK": ("1104", "2019-01-03", "2020-06-01", "regulatorydelisting"),
        "TWTR": ("1105", "2024-01-02", "2024-10-31", "regulatorydelisting"),
        "SIVB": ("1106", "2022-01-03", "2023-03-15", "regulatorydelisting"),
        "BBBY": ("1107", "2022-01-03", "2023-05-02", "bankruptcyliquidation"),
        "FRC": ("1108", "2022-01-03", "2023-05-02", "bankruptcyliquidation"),
        "ATVI": ("1109", "2022-01-03", "2023-10-13", "acquisitionby"),
        "XLNX": ("1110", "2021-01-03", "2022-02-14", "acquisitionby"),
    }
    tickers = []
    actions = [_action("2016-09-30", "listed", "DUMMY")]  # ACTIONS coverage floor.
    for name, (pt, listed, exited, kind) in plan.items():
        tickers.append(_ticker("SEP", pt, name, "Domestic Common Stock", "Y"))
        if name != "LNKD":
            actions.append(_action(listed, "listed", name))
        actions.append(_action(exited, kind, name))
    # LNKD has no listing action: its sole interval starts at the floor, after its 2016-06-15 probe.
    tickers[0]["firstpricedate"] = "2010-01-01"
    return _write_capture(tmp_path / "ten-exits", tickers, actions)


def test_the_sole_holder_fallback_stays_before_actions_coverage(tmp_path: Path) -> None:
    report, _ = acceptance.evaluate(
        _ten_exit_capture(tmp_path), start=date(2016, 1, 1), end=date(2026, 11, 5)
    )
    exits = report["acceptance"]["ten_exits"]
    assert exits["names"]["TWTR"] == {"covered": False, "reason": "0 share classes held TWTR"}
    assert exits["names"]["LNKD"]["covered"] is True  # Pre-coverage probe: the fallback is legal.
    assert (exits["status"], exits["covered"]) == ("FAIL", 9)


def _preferred_capture(tmp_path: Path) -> Path:
    tickers = [_ticker("SEP", "77", "PFDA", "Domestic Preferred Stock", "Y")]
    actions = [
        _action("2017-01-03", "listed", "PFDA"),
        _action("2018-06-01", "regulatorydelisting", "PFDA"),
    ]
    return _write_capture(tmp_path / "preferred", tickers, actions)


def test_a_preferred_exit_never_credits_a_registered_common_stock_filing(tmp_path: Path) -> None:
    registration = {
        "pass_at_least": 1,
        "sample": [
            {
                "accession": "a-77",
                "issuer_cik": "77",
                "filed": "2025-02-17",
                "class": "Common Stock",
            }
        ],
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(registration))
    report, _ = acceptance.evaluate(
        _preferred_capture(tmp_path),
        start=date(2016, 1, 1),
        end=date(2026, 11, 5),
        registration=path,
    )
    result = report["acceptance"]["independent_delisted_sample"]
    assert (result["status"], result["covered"]) == ("FAIL", 0)
    row = result["rows"][0]
    assert row["covered"] is False and row["security_id"] is None
    assert "preferred" in row["reason"]


def _registered(tmp_path: Path) -> Path:
    path = tmp_path / "registration.json"
    sample = [
        {"accession": "a-1", "issuer_cik": "0000000030", "filed": "2023-05-10"},
        {"accession": "a-2", "issuer_cik": "999", "filed": "2023-05-10"},
    ]
    path.write_text(json.dumps({"pass_at_least": 2, "sample": sample}))
    return path


# The report and members manifest the replaced reader (_bulk's own ZIP/CSV/hash code, #133 at
# 2aac686) wrote for this capture and registration.
REPLACED_OUTPUT = (
    "2dcc2308e77cc481222c5eebe62a9b1df5ba6aac9d99a54776370f8e6db11de7",
    "bb600ecc675f344d990e334e72adfa6f6b60bd70e3cab06d19685ab66590e891",
)


def test_main_capture_reader_changes_no_acceptance_output(tmp_path: Path) -> None:
    """Zero difference: #107's _read_capture replaced the acceptance's own bulk reader."""
    report, manifest = acceptance.evaluate(
        _capture(tmp_path),
        start=date(2016, 1, 1),
        end=date(2026, 11, 5),
        registration=_registered(tmp_path),
    )
    digests = tuple(
        hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        for value in (report, manifest)
    )
    assert digests == REPLACED_OUTPUT

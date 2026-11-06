"""Seed audit, missingness and immutable receipts; fixtures grant no PIT authority."""

import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from sextant.research import candidate_history as history


def _csv(rows: list[dict[str, str]], fields: list[str], delimiter: str = ",") -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _members() -> dict[str, bytes]:
    """Synthetic identities, blank returns and an unselected date; no market data."""
    members = {
        history.CALENDAR: _csv(
            [{"Date": day} for day in ("2021-01-04", "2025-01-03", "2025-01-06")], ["Date"]
        )
    }
    events = [
        {"Date": "2021-01-04", "Ticker": "AAA", "Notes": "approx; unknown float\nsecond line"},
        {"Date": "2025-01-03", "Ticker": "AAA", "Notes": ""},
    ]
    for name in (*history.GAINERS, history.LOSERS):
        rows = []
        if "gainers-2021" in name:
            rows = [events[0]]
        elif "gainers-2025-2026" in name:
            rows = [events[1]]
        elif name == history.LOSERS:
            rows = [{"Date": "2025-01-03", "Ticker": "BBB", "Notes": "selected collapse"}]
        members[history.DATASETS + name] = _csv(
            rows, ["Date", "Ticker", "Notes"], "," if "gainers-2025-2026" in name else "|"
        )
    forward = [
        {
            "Date": event["Date"],
            "Ticker": event["Ticker"],
            "Status": "NO_DATA" if i == 0 else "OK",
            "Discrepancy_Flag": "",
            "Ret_T1_Pct": "",
            "Ret_T5_Pct": "",
            "Ret_T20_Pct": "",
        }
        for i, event in enumerate(events)
    ]
    members[history.DATASETS + history.OVERLAYS[0]] = _csv(forward, list(forward[0]))
    members[history.DATASETS + history.OVERLAYS[1]] = _csv(
        [{"Date": "2021-01-04", "Ticker": "AAA", "Outcome_Type": "renamed", "Alias_Symbol": "NEW"}],
        ["Date", "Ticker", "Outcome_Type", "Alias_Symbol"],
    )
    members[history.DATASETS + history.OVERLAYS[2]] = _csv([], ["Date", "Ticker", "T20_Pct"])
    members[history.DATASETS + history.CORRECTIONS] = _csv(
        [{"Notes": "keep original correction, no inferred join"}], ["Notes"]
    )
    return members


def _archive(members: dict[str, bytes]) -> bytes:
    body = io.BytesIO()
    with ZipFile(body, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return body.getvalue()


def _inspect(members: dict[str, bytes]) -> tuple[dict, list[dict], list[str]]:
    with ZipFile(io.BytesIO(_archive(members))) as archive:
        return history._inspect(archive)


def test_seed_reconciliation_preserves_selection_missingness_and_identities() -> None:
    summary, events, calendar = _inspect(_members())
    assert summary["events"] == {"selected_gainer": 2, "selected_loser": 1}
    assert len(calendar) == 3
    assert summary["forward_status"] == {"NO_DATA": 1, "OK": 1}
    assert summary["forward_observed_returns"] == {
        "Ret_T1_Pct": 0,
        "Ret_T5_Pct": 0,
        "Ret_T20_Pct": 0,
    }
    assert [e["selection"] for e in events] == [
        "weekly_leader",
        "daily_leader_collection",
        "selected_collapse",
    ]
    assert events[0]["symbol"] == "AAA"  # Alias NEW never rewrites the dated symbol.
    assert events[0]["raw_fields"]["Notes"] == "approx; unknown float\nsecond line"
    assert events[1]["raw_fields"]["Notes"] == ""
    assert events[0]["overlays"][history.OVERLAYS[0]]["Ret_T20_Pct"] == ""
    assert events[0]["overlays"][history.OVERLAYS[1]]["Alias_Symbol"] == "NEW"
    assert all(e["known_at"] is e["security_id"] is e["pre_ignition_label"] is None for e in events)
    assert summary["survivor_only"] is True and summary["pit_verified"] is False
    assert summary["ordinary_control_count"] is summary["pre_ignition_label_count"] is None
    assert summary["trial_accounting"]["inference_eligible"] is False
    assert summary["trial_accounting"]["cumulative_n"] is None


@pytest.mark.parametrize(
    "fault", ["duplicate", "foreign_overlay", "missing_forward", "calendar_gap"]
)
def test_bad_joins_and_unobserved_dates_refuse_instead_of_dropping_rows(fault: str) -> None:
    members = _members()
    if fault == "duplicate":
        name = history.DATASETS + history.GAINERS[0]
        members[name] += members[name].split(b"\r\n", 1)[1]
    elif fault == "foreign_overlay":
        members[history.DATASETS + history.OVERLAYS[2]] += b"2021-01-04,OTHER,\r\n"
    elif fault == "missing_forward":
        members[history.DATASETS + history.OVERLAYS[0]] = _csv(
            [], ["Date", "Ticker", "Status", "Discrepancy_Flag"]
        )
    else:
        members[history.CALENDAR] = _csv([{"Date": "2025-01-03"}], ["Date"])
    with pytest.raises(ValueError):
        _inspect(members)


@pytest.mark.parametrize("body", [b"Date,Ticker\n2021-01-04,AAA,extra\n", b"Date,Date\nX,Y\n"])
def test_malformed_csv_refuses(body: bytes) -> None:
    members = _members()
    members[history.DATASETS + history.OVERLAYS[0]] = body
    with pytest.raises(ValueError):
        _inspect(members)


def test_unpinned_archive_never_creates_receipts(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic.zip"
    archive.write_bytes(_archive(_members()))
    destination = tmp_path / "receipts"
    with pytest.raises(ValueError, match="SHA-256"):
        history.reconcile_seed(archive, destination, implementation_sha="a" * 40)
    assert not destination.exists()


def test_session_receipts_include_unselected_dates_and_hash_all_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the fixture's archive identity is substituted. Production exposes no pin override.
    raw = _archive(_members())
    monkeypatch.setattr(history, "SEED_SHA256", hashlib.sha256(raw).hexdigest())
    archive = tmp_path / "synthetic.zip"
    archive.write_bytes(raw)
    destination = tmp_path / "receipts"
    summary = history.reconcile_seed(archive, destination, implementation_sha="a" * 40)
    assert len(list((destination / "sessions").glob("*.json"))) == 3
    empty = json.loads((destination / "sessions/2025-01-06.json").read_text())
    assert empty["events"] == {}
    assert "never no_movers" in empty["absence_semantics"]
    assert empty["survivor_only"] is True
    assert empty["trial_accounting"]["ledger_binding"] is None
    assert empty["known_at"] is None
    for name, expected in summary["artifacts"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected
    assert history.reconcile_seed(archive, destination, implementation_sha="a" * 40) == summary
    original = (destination / "summary.json").read_bytes()
    with pytest.raises(ValueError, match="Conflicting immutable"):
        history.reconcile_seed(archive, destination, implementation_sha="b" * 40)
    assert (destination / "summary.json").read_bytes() == original


def test_duplicate_zip_members_refuse() -> None:
    raw = io.BytesIO(_archive(_members()))
    with ZipFile(raw, "a") as archive, pytest.warns(UserWarning, match="Duplicate name"):
        archive.writestr(history.CALENDAR, b"Date\n2021-01-04\n")
    with ZipFile(raw) as archive, pytest.raises(ValueError, match="Duplicate ZIP"):
        history._inspect(archive)

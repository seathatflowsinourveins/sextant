"""N2b-3: the ranking mode's prior closes and asset security types as a verified data step.

The closes come through prestage's own daily-close path (here a fixture source with its
``daily_closes`` shape); the types come from listing files staged by main's listings job
(``listings.stage`` with a fixture fetch), checked against its receipt.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from sextant.data import ranking_inputs
from sextant.tradingview import listings

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nasdaqtrader"
SESSION = date(2026, 11, 11)  # a Wednesday; its prior XNYS session is 2026-11-10


class Daily:
    def __init__(self, closes: dict[str, D]) -> None:
        self.closes, self.days = closes, []

    def daily_closes(self, symbols, *, day):
        self.days.append(day)
        return {name: close for name, close in self.closes.items() if name in symbols}


def staged(tmp_path: Path) -> Path:
    directory = tmp_path / "listings"
    listings.stage(
        directory, timeout=1, get=lambda url, _t: (FIXTURES / url.rsplit("/", 1)[1]).read_bytes()
    )
    return directory


def artifact(tmp_path: Path, *symbols: str) -> Path:
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"rows": [{"symbol": name} for name in symbols]}))
    return path


def produce(tmp_path: Path, daily: Daily | None = None, *, restage: bool = True) -> Path:
    out = tmp_path / "ranking-inputs"
    ranking_inputs.produce(
        out,
        universe_artifact=artifact(tmp_path, "AAPL", "IBM", "MTEST", "ZZZZ"),
        listings_dir=staged(tmp_path) if restage else tmp_path / "listings",
        session=SESSION,
        daily=daily or Daily({"AAPL": D("10.50"), "IBM": D("200.25")}),
    )
    return out


def test_the_step_writes_closes_and_types_under_a_manifest(tmp_path) -> None:
    daily = Daily({"AAPL": D("10.50"), "IBM": D("200.25")})
    out = produce(tmp_path, daily)
    assert daily.days == [date(2026, 11, 10)]  # prestage's reference: the prior session
    references = json.loads((out / "references.json").read_text())
    assert references["closes"] == {"AAPL": "10.50", "IBM": "200.25"}  # no close is invented
    assert references["reference_session"] == "2026-11-10" and references["session"] == "2026-11-11"
    assets = json.loads((out / "assets.json").read_text())
    types = {name: row["security_type"] for name, row in assets["types"].items()}
    assert types == {"AAPL": "common", "IBM": "common", "MTEST": "test"}  # ZZZZ: no row
    assert assets["types"]["AAPL"]["financial_status"] == "N"
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["files"]) == {"references.json", "assets.json"}
    assert references["universe_sha256"] == assets["universe_sha256"]


def test_listings_that_do_not_match_their_receipt_are_refused_and_nothing_changes(tmp_path) -> None:
    out = produce(tmp_path)
    before = (out / "manifest.json").read_bytes()
    listing = tmp_path / "listings" / "otherlisted.txt"
    listing.write_bytes(listing.read_bytes().replace(b"IBM|", b"IBN|"))
    with pytest.raises(ranking_inputs.InputsRefused, match=r"otherlisted\.txt"):
        produce(tmp_path, restage=False)
    assert (out / "manifest.json").read_bytes() == before


def test_no_close_for_the_universe_is_refused(tmp_path) -> None:
    with pytest.raises(Exception, match="no prior official close"):
        produce(tmp_path, Daily({}))
    assert not (tmp_path / "ranking-inputs" / "manifest.json").exists()


@pytest.mark.parametrize(
    "flag",
    [
        "--out",
        "--universe-artifact",
        "--listings-dir",
        "--session",
        "--api-key-env",
        "--api-secret-env",
        "--parameters",
    ],
)
def test_every_argument_is_required(tmp_path, flag: str) -> None:
    values = {
        "--out": str(tmp_path / "out"),
        "--universe-artifact": str(artifact(tmp_path, "AAPL")),
        "--listings-dir": str(tmp_path / "listings"),
        "--session": "2026-11-11",
        "--api-key-env": "FIXTURE_KEY_NAME",
        "--api-secret-env": "FIXTURE_SECRET_NAME",
        "--parameters": "deploy/calibration/parameters.json",
    }
    argv = [item for key, value in values.items() if key != flag for item in (key, value)]
    with pytest.raises(SystemExit):
        ranking_inputs.parse(argv)


ROOT = Path(__file__).parents[2]


def test_the_unit_runs_the_step_after_its_job_with_slot_2_names_only(tmp_path) -> None:
    import configparser
    import shlex
    import subprocess

    service = configparser.ConfigParser(interpolation=None)
    service.read(ROOT / "deploy/calibration/sextant-calibration-data.service")
    command = shlex.split(service["Service"]["ExecStartPost"])
    assert command[:8] == [
        "/usr/bin/bash",
        "%h/sextant/scripts/with-keys.sh",
        "--strict",
        "-k",
        "ALPACA_PAPER_2_API_KEY:APCA_API_KEY_ID",
        "-k",
        "ALPACA_PAPER_2_SECRET_KEY:APCA_API_SECRET_KEY",
        "--",
    ]
    assert command[8:] == [
        "/usr/bin/bash",
        "%h/sextant/scripts/ranking-inputs.sh",
        "%h/sextant-data/calibration",
        "%h/sextant-data/tradingview-prestage",
    ]
    fake, record = tmp_path / "uv", tmp_path / "arguments"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD"\n')
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ranking-inputs.sh"), str(tmp_path / "data"), "/listings"],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "RECORD": str(record)},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    argv = record.read_text().splitlines()
    assert argv[:5] == ["run", "--frozen", "python", "-m", "sextant.data.ranking_inputs"]
    assert argv[argv.index("--api-key-env") + 1] == "APCA_API_KEY_ID"  # a name, never a value
    assert argv[argv.index("--out") + 1] == str(tmp_path / "data/ranking-inputs")
    assert argv[argv.index("--listings-dir") + 1] == "/listings"

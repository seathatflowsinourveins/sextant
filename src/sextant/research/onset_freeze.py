"""Freeze the #130 Part 1 cohort, matched controls and session windows.

The rule is written before any minute bar is pulled. Identity comes only from the
Sharadar receipts already on disk: the event rows' resolved master candidates and
the complete SEP ticker table. No price, volume or intraday outcome is read, so a
control cannot be chosen for how it traded. ``survivor_only`` and
``pit_verified:false`` stay explicit: the cohort is hindsight-selected and a
recycled ticker is resolved by active-date and current-ticker match, not by an
exchange identity service.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

NS = 1_000_000_000
CLASSES = {
    "Domestic Common Stock": "common",
    "Domestic Common Stock Primary Class": "common",
    "ADR Common Stock": "adr",
    "ADR Common Stock Primary Class": "adr",
}
EXCHANGES = {
    "NYSE": "NYSE",
    "NASDAQ": "NASDAQ",
    "NYSEMKT": "AMEX",
    "AMEX": "AMEX",
    "NYSEARCA": "ARCA",
    "BATS": "BATS",
}
SCALES = {
    "1 - Nano": 1,
    "2 - Micro": 2,
    "3 - Small": 3,
    "4 - Mid": 4,
    "5 - Large": 5,
}
SCALE_RE = re.compile(r"^(\d) - ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(head: str) -> str:
    return subprocess.run(
        ["git", *head.split()], check=True, capture_output=True, text=True
    ).stdout.strip()


def class_group(category: str) -> str | None:
    return CLASSES.get(category)


def exchange_group(exchange: str) -> str | None:
    return EXCHANGES.get(exchange)


def scale_rank(value: str) -> int | None:
    if value in SCALES:
        return SCALES[value]
    match = SCALE_RE.match(value)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class Master:
    permaticker: str
    ticker: str
    exchange: str
    category: str
    sector: str
    industry: str
    scale: str
    first: date
    last: date

    @property
    def klass(self) -> str:
        group = class_group(self.category)
        assert group is not None
        return group


def load_tickers(path: Path) -> tuple[list[dict[str, str]], str]:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("tickers.csv")
    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")))
    return rows, sha256_bytes(raw)


def master_row(row: dict[str, str]) -> Master | None:
    try:
        first = date.fromisoformat(row["firstpricedate"])
        last = date.fromisoformat(row["lastpricedate"])
    except (KeyError, ValueError):
        return None
    if not row.get("permaticker") or not row.get("ticker"):
        return None
    return Master(
        row["permaticker"],
        row["ticker"],
        row.get("exchange", ""),
        row.get("category", ""),
        row.get("sector", ""),
        row.get("industry", ""),
        row.get("scalemarketcap", ""),
        first,
        last,
    )


def active_masters(event: dict[str, Any]) -> dict[str, Master]:
    day = date.fromisoformat(event["session_date"])
    found: dict[str, Master] = {}
    for candidate in event["master_candidates"]:
        master = master_row(candidate)
        if master is None or class_group(master.category) is None:
            continue
        if master.first <= day <= master.last:
            found.setdefault(master.permaticker, master)
    return found


def resolve_event(event: dict[str, Any]) -> tuple[Master | None, str]:
    candidates = list(active_masters(event).values())
    preferred = [m for m in candidates if m.ticker == event["symbol"]]
    if len(preferred) == 1:
        return preferred[0], "ticker_match"
    if len(preferred) > 1:
        return None, "ambiguous_ticker_match"
    if len(candidates) == 1:
        return candidates[0], "unique_active"
    return None, "ambiguous_active" if candidates else "no_active_master"


def load_events(path: Path) -> tuple[list[dict[str, Any]], str]:
    data = path.read_bytes()
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    return rows, sha256_bytes(data)


def event_id(event: dict[str, Any]) -> str:
    key = f"{event['cohort']}|{event['symbol']}|{event['session_date']}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def controls(
    events: list[dict[str, Any]],
    tickers: list[dict[str, str]],
    seed: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    by_day: dict[str, list[Master]] = {}
    ticker_rows: dict[str, list[dict[str, str]]] = {}
    for row in tickers:
        if row.get("table") != "SEP" or class_group(row.get("category", "")) is None:
            continue
        if row.get("currency") != "USD":
            continue
        # A renamed, recycled or delisted-Q ticker has no dated alias table here.
        # Allow only a currently unique symbol with no other Sharadar ticker alias.
        if row.get("relatedtickers", "").strip():
            continue
        if row.get("isdelisted") == "Y" and row["ticker"].endswith("Q"):
            continue
        ticker_rows.setdefault(row["ticker"], []).append(row)

    def universe(day: str) -> list[Master]:
        if day in by_day:
            return by_day[day]
        current = date.fromisoformat(day)
        unique: dict[str, dict[str, str]] = {}
        for rows in ticker_rows.values():
            if len(rows) == 1 and _active(rows[0], current):
                unique[rows[0]["ticker"]] = rows[0]
        result = [
            master
            for raw in unique.values()
            if (master := master_row(raw)) is not None
            and master.permaticker not in seed
            and exchange_group(master.exchange) is not None
        ]
        by_day[day] = result
        return result

    used: dict[str, set[str]] = {}
    event_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "events": 0,
        "with_primary": 0,
        "with_backup_1": 0,
        "with_backup_2": 0,
        "unavailable": 0,
        "identity": {},
        "classes": {},
        "exchanges": {},
    }
    for event in sorted(events, key=lambda r: (r["session_date"], r["symbol"])):
        eid = event_id(event)
        master, identity = resolve_event(event)
        stats["identity"][identity] = stats["identity"].get(identity, 0) + 1
        base = {
            "event_id": eid,
            "symbol": event["symbol"],
            "day": event["session_date"],
            "cohort": event["cohort"],
            "identity": identity,
            "first_print_ts": event.get("first_print_ts"),
            "flag_ts": event.get("flag_ts"),
            "master": None,
            "control_ids": [],
        }
        if master is None:
            stats["unavailable"] += 1
            event_rows.append({**base, "control_reason": identity})
            continue
        group = exchange_group(master.exchange)
        day = event["session_date"]
        chosen = [
            candidate
            for candidate in universe(day)
            if candidate.klass == master.klass
            and exchange_group(candidate.exchange) == group
            and candidate.permaticker not in used.get(day, set())
        ]
        score = partial(
            _score,
            eid=eid,
            sector=master.sector,
            industry=master.industry,
            scale=scale_rank(master.scale),
            exchange=master.exchange,
        )
        chosen.sort(key=score)
        picked = chosen[:3]
        base["master"] = {
            "permaticker": master.permaticker,
            "ticker": master.ticker,
            "exchange": master.exchange,
            "class": master.klass,
            "sector": master.sector,
            "industry": master.industry,
            "scale": master.scale,
        }
        base["control_reason"] = "matched" if picked else "no_eligible_control"
        for rank, candidate in enumerate(picked):
            role = "primary" if rank == 0 else f"backup_{rank}"
            cid = f"c-{eid}-{rank + 1}"
            base["control_ids"].append(cid)
            pick = score(candidate)
            control_rows.append(
                {
                    "control_id": cid,
                    "event_id": eid,
                    "day": day,
                    "role": role,
                    "permaticker": candidate.permaticker,
                    "ticker": candidate.ticker,
                    "exchange": candidate.exchange,
                    "class": candidate.klass,
                    "sector": candidate.sector,
                    "industry": candidate.industry,
                    "scale": candidate.scale,
                    "score": {
                        "sector_match": pick[0] == 0,
                        "industry_match": pick[1] == 0,
                        "scale_distance": pick[2],
                        "exchange_match": pick[3] == 0,
                    },
                }
            )
            used.setdefault(day, set()).add(candidate.permaticker)
        if picked:
            stats["with_primary"] += 1
        if len(picked) > 1:
            stats["with_backup_1"] += 1
        if len(picked) > 2:
            stats["with_backup_2"] += 1
        stats["classes"][master.klass] = stats["classes"].get(master.klass, 0) + 1
        stats["exchanges"][master.exchange] = stats["exchanges"].get(master.exchange, 0) + 1
        stats["events"] += 1
        event_rows.append(base)
    return event_rows, control_rows, stats


def _active(row: dict[str, str], day: date) -> bool:
    try:
        return (
            date.fromisoformat(row["firstpricedate"])
            <= day
            <= date.fromisoformat(row["lastpricedate"])
        )
    except (KeyError, ValueError):
        return False


def _score(
    candidate: Master,
    *,
    eid: str,
    sector: str,
    industry: str,
    scale: int | None,
    exchange: str,
) -> tuple[Any, ...]:
    candidate_scale = scale_rank(candidate.scale)
    distance = 9 if candidate_scale is None or scale is None else abs(candidate_scale - scale)
    return (
        0 if sector and candidate.sector == sector else 1,
        0 if industry and candidate.industry == industry else 1,
        distance,
        0 if candidate.exchange == exchange else 1,
        hashlib.sha256(f"{eid}|{candidate.permaticker}".encode()).hexdigest(),
    )


RULE = """# #130 Part 1 control rule (frozen before any pull)

Cohort: the 814 `selected_gainer` events whose Sharadar receipt has an observed
event-day SEP or SFP row. The 215 selected losers are a separate set and are not
controls. Event identity is the event row's master candidate active on
`session_date`; a single active candidate whose current ticker equals the event
symbol is preferred, otherwise exactly one active common/ADR candidate is used.
Two such candidates without a ticker match, or none, leave the event without a
control and are counted as such.

Control: a different `permaticker` on the same `session_date`, so it is an
ordinary day for that symbol. It is drawn from Sharadar's complete SEP ticker
table with `currency=="USD"`, a class group equal to the event's (`common` for
Domestic Common Stock/Primary Class; `adr` for ADR Common Stock/Primary Class),
the same exchange group (NYSE, NASDAQ or AMEX), `firstpricedate <= date <=
lastpricedate`, a ticker that maps to exactly one active permaticker that day,
and a permaticker that appears in no seed event candidate. A control ticker must
also have an empty Sharadar `relatedtickers` list and must not be a delisted `Q`
alias: the snapshot has no dated alias table, so a renamed or recycled ticker
could pull another company's bars. This excludes otherwise eligible names and is
a disclosed control-selection limit, not a claim that the remaining tickers never
changed. Each permaticker is used at most once per date.

Ranking, fixed before the pull: same sector, then same industry, then the
smallest ordinal `scalemarketcap` distance, then the same exchange, then the
lowest `sha256(event_id|permaticker)`. The first three are frozen as primary,
backup 1 and backup 2. A later pull may fall back only when an earlier candidate
has no bars; it may not re-rank. A missing backup means that control day is
missing, never replaced from the pulled data.

Limits: no pre-pull panel exists for price or prior-14-session liquidity, so
those cannot be match keys. `survivor_only: true`; `pit_verified: false`; event
`identity_verified` is false in the receipt. This is a hindsight-selected cohort
and matched ordinary days, never a hit rate for ranking every stock.
"""

WINDOWS = {
    "timezone": "America/New_York",
    "sessions": {
        "overnight": {"start": "20:00 previous session", "end": "04:00"},
        "pre": {"start": "04:00", "end": "09:30"},
        "rth": {
            "start": "09:30",
            "end": "16:00",
            "opening": {"start": "09:30", "end": "09:35"},
        },
        "post": {"start": "16:00", "end": "20:00"},
    },
    "flag_baseline": "latest completed official RTH close strictly before the minute",
    "rvol_denominator": "mean opening-window volume over the 14 prior completed sessions",
    "lookback_sessions": 14,
    "pull_sessions": 15,
    "rvol_min_prior_sessions": 14,
}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def freeze(events_path: Path, tickers_path: Path, out: Path) -> dict[str, Any]:
    """Write the frozen cohort, controls, rule, windows and closed manifest."""
    events, events_sha = load_events(events_path)
    tickers, tickers_sha = load_tickers(tickers_path)
    cohort = [
        e
        for e in events
        if e["cohort"] == "selected_gainer"
        and any(p["status"] == "observed" for p in e["prices"].values())
    ]
    seed = {
        candidate["permaticker"]
        for event in events
        for candidate in event["master_candidates"]
        if candidate.get("permaticker")
    }
    event_rows, control_rows, stats = controls(cohort, tickers, seed)

    out.mkdir(parents=True, exist_ok=False)
    (out / "events.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in event_rows)
    )
    (out / "controls.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in control_rows)
    )
    (out / "rule.md").write_text(RULE)
    write_json(out / "windows.json", WINDOWS)
    script_sha = sha256_file(Path(__file__))
    manifest = {
        "format": "sextant.onset.freeze/1",
        "issue": 130,
        "part": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "cohort": "selected_gainer",
        "counts": {
            "cohort": len(event_rows),
            "controls": len(control_rows),
            "events_with_control": stats["with_primary"],
            "events_without_control": stats["unavailable"],
            "backup_1": stats["with_backup_1"],
            "backup_2": stats["with_backup_2"],
            **{f"identity_{key}": value for key, value in sorted(stats["identity"].items())},
        },
        "classes": stats["classes"],
        "exchanges": stats["exchanges"],
        "inputs": {"events.jsonl": events_sha, "tickers.csv": tickers_sha},
        "code": {
            "head": git("rev-parse HEAD"),
            "dirty": bool(git("status --porcelain")),
            "script_sha256": script_sha,
        },
        "labels": {
            "survivor_only": True,
            "pit_verified": False,
            "identity_verified": False,
            "controls": "matched ordinary symbol-days, never a hit rate for ranking every stock",
            "control_ticker_rule": "empty_relatedtickers_and_not_delisted_Q",
        },
        "files": {
            name: sha256_file(out / name)
            for name in ("events.jsonl", "controls.jsonl", "rule.md", "windows.json")
        },
    }
    write_json(out / "manifest.json", manifest)
    lines = [f"{sha256_file(out / name)}  {name}" for name in sorted(p.name for p in out.iterdir())]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return manifest

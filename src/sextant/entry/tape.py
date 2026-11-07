"""Exact private temporary SQLite history; SDK sources and lifecycle in docs/manifest.md."""

import json
import sqlite3
from decimal import Decimal
from weakref import finalize

from nautilus_trader.model import TradeTick


class Tape:
    def __init__(self):
        self.db = sqlite3.connect("", isolation_level=None)
        finalize(self, self.db.close)
        self.db.execute(
            "CREATE TABLE prints (identity TEXT UNIQUE, at INTEGER, "
            "payload TEXT, eligible INTEGER, atr TEXT)"
        )
        self.db.execute("CREATE INDEX event_order ON prints (at)")
        self.db.execute("CREATE TABLE atrs (known INTEGER PRIMARY KEY, atr TEXT)")

    def add(self, tick: TradeTick, eligible: bool, atr: Decimal | None) -> bool:
        identity = (str(tick.trade_id), tick.ts_event, tick.price.raw, tick.size.raw)
        # Reuse event (?2), eligibility (?4) and current ATR (?5) bindings.
        return bool(
            self.db.execute(
                "INSERT OR IGNORE INTO prints VALUES (?, ?, ?, ?, CASE WHEN ?4 THEN ?5 "
                "ELSE (SELECT atr FROM atrs WHERE known <= ?2 ORDER BY known DESC LIMIT 1) END)",
                (
                    json.dumps(identity),
                    tick.ts_event,
                    json.dumps(TradeTick.to_dict(tick)),
                    eligible,
                    None if atr is None else str(atr),
                ),
            ).rowcount
        )

    def rows(self, after: int = 0):
        for payload, eligible, atr in self.db.execute(
            "SELECT payload, eligible, atr FROM prints WHERE at >= ? ORDER BY at, rowid", (after,)
        ):
            yield (
                TradeTick.from_dict(json.loads(payload)),
                bool(eligible),
                None if atr is None else Decimal(atr),
            )

    def count(self, after: int, end: int) -> int:
        return self.db.execute(
            "SELECT count(*) FROM prints WHERE at > ? AND at <= ?", (after, end)
        ).fetchone()[0]

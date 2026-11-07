"""Hash-checked B export description; order summaries are not an executable/custody tape.

Adapted gross-only FIFO from northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
src/northstar_trading/research_e2e/backtests/b_gain_inputs.py:read_order_summaries/realized_fifo.
LIFO cross-check: docs/research/2026-11-03-b-exit-replay.md, carried by #49. No fee or fill
model is inferred. Missing opening inventory and still-open lots remain explicit.
"""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

EXPORT_SHA256 = "7592f70f17782fb35b38e78860db309051d4db7ab01c479e577a8c6cbef8f304"


def _match(rows: list[dict], *, lifo: bool) -> tuple[int, Decimal, list[dict], list[dict]]:
    inventory: dict[str, list[list[Decimal]]] = defaultdict(list)
    count, gross, unmatched = 0, Decimal(0), []
    for row in rows:
        quantity, price = Decimal(row["filled_qty"]), Decimal(row["filled_avg_price"])
        lots = inventory[row["symbol"]]
        if row["side"] == "buy":
            lots.append([quantity, price])
            continue
        while quantity and lots:
            lot = lots[-1 if lifo else 0]
            amount = min(quantity, lot[0])
            count += 1
            gross += amount * (price - lot[1])
            quantity -= amount
            lot[0] -= amount
            if lot[0] == 0:
                lots.pop(-1 if lifo else 0)
        if quantity:
            unmatched.append({"symbol": row["symbol"], "quantity": str(quantity)})
    opened = [
        {"symbol": symbol, "quantity": str(qty), "basis": str(px)}
        for symbol, lots in sorted(inventory.items())
        for qty, px in lots
    ]
    return count, gross, unmatched, opened


def summarize(path: Path) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPORT_SHA256:
        raise ValueError("B export SHA-256 differs from the frozen source")
    rows = [json.loads(line, parse_float=Decimal) for line in raw.splitlines() if line.strip()]
    rows.sort(key=lambda r: (datetime.fromisoformat(r["filled_at"]), r["order_id8"]))
    lots, fifo, unmatched, opened = _match(rows, lifo=False)
    _, lifo, _, _ = _match(rows, lifo=True)
    return {
        "sha256": EXPORT_SHA256,
        "orders": len(rows),
        "symbols": len({r["symbol"] for r in rows}),
        "sources": dict(Counter(r["source"] for r in rows)),
        "fifo_lots": lots,
        "fifo_gross_usd": str(fifo),
        "lifo_gross_usd": str(lifo),
        "first_fill": rows[0]["filled_at"],
        "last_fill": rows[-1]["filled_at"],
        "unmatched_sells": unmatched,
        "open_lots": opened,
        "tier": "OBSERVED_ORDER_SUMMARIES",
        "paired": False,
    }

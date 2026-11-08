"""One `sextant-codex` run's receipt from OmniRoute's own call log: metadata, never a body or key.

    python3 -I scripts/omni_receipt.py RUN_ID [--write PATH]

The launcher sends RUN_ID as the `session_id` header, which OmniRoute 3.8.53 records as each
call's client session (open-sse/services/conversationTracker.ts:488, call_logs.client_session_id);
Codex 0.167.0's own `session-id` header is not on that list. The receipt lists recent calls and
reads this run's request records through OmniRoute's own CLI, the way scripts/omni_keys.py does,
and keeps the served model, path, status, connection prefix and the record's `reasoning.effort`:
the call log's effort columns stay empty on the Responses wire (src/lib/usage/callLogs.ts:616-621).
A record whose body the size cap omitted counts as "not retained", never as an effort.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("omni_keys", ROOT / "scripts" / "omni_keys.py")
assert _SPEC and _SPEC.loader
ok = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ok)

POLICY = ROOT / "deploy" / "wsl" / "lane-runtimes" / "model-policy.json"
LIST_LIMIT = 1000  # recent calls of every runtime, newest first; the route's default page is 50
READERS = 8  # one CLI process per request record
PENDING_READS, PENDING_WAIT = 10, 0.5  # a record is written just after its row (detailState)
SETTLE = 1.0  # seconds for the last call's row to land after Codex exits
RUN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TOKEN = re.compile(r"[A-Za-z0-9/][A-Za-z0-9._:/-]{0,79}")


def _token(value: object) -> str:
    """A model, path, status or effort as a short token; anything else is withheld, unread."""
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    return text if TOKEN.fullmatch(text) else "withheld"


def _record(log_id: str) -> dict | None:
    """One request record, read again while OmniRoute is still writing it."""
    for _ in range(PENDING_READS):
        try:
            record = ok._cli("usage", "get-api-usage-call-logs-id-", "--id", log_id)
        except ok.KeyError_:
            return None
        if not isinstance(record, dict):
            return None
        if record.get("detailState") != "pending":
            return record
        time.sleep(PENDING_WAIT)
    return None


def _effort(record: dict | None) -> str:
    if record is None:
        return "unread"
    body = record.get("requestBody")
    reasoning = body.get("reasoning") if isinstance(body, dict) else None
    effort = reasoning.get("effort") if isinstance(reasoning, dict) else None
    return _token(effort) if isinstance(effort, str) else "not retained"


def receipt(run_id: str) -> dict:
    time.sleep(SETTLE)
    rows = ok._cli("usage", "get-api-usage-call-logs", "--limit", str(LIST_LIMIT))
    rows = rows if isinstance(rows, list) else []
    mine = [r for r in rows if isinstance(r, dict) and r.get("clientSessionId") == run_id]
    with ThreadPoolExecutor(READERS) as pool:
        efforts = list(pool.map(lambda row: _effort(_record(str(row.get("id")))), mine))
    pin = json.loads(POLICY.read_text())["gpt"]
    served = Counter(_token(r.get("model")) for r in mine)
    effort = Counter(efforts)
    # A record without its body is no evidence either way: the pin holds when every call was
    # served by the pinned model and every effort a record kept is the pinned one.
    kept = set(effort) - {"not retained", "unread"}
    return {
        "run": run_id,
        "calls": len(mine),
        "paths": dict(Counter(f"{_token(r.get('method'))} {_token(r.get('path'))}" for r in mine)),
        "status": dict(Counter(_token(r.get("status")) for r in mine)),
        "served_models": dict(served),
        "connections": dict(
            Counter(_token(str(r.get("connectionId") or "none")[:8]) for r in mine)
        ),
        "reasoning_effort": dict(effort),
        "pin_ok": bool(mine) and set(served) == {pin["model"]} and kept == {pin["effort"]},
        # Fewer listed calls than the limit means the window reached back past this run.
        "listed": len(rows),
        "window_full": len(rows) >= LIST_LIMIT,
        "source": "OmniRoute 3.8.53 call log rows and request records, through its own CLI",
    }


def main(argv: list[str]) -> int:
    written = len(argv) == 3 and argv[1] == "--write"
    if not (len(argv) == 1 or written) or not RUN.fullmatch(argv[0]):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        result = receipt(argv[0])
    except ok.KeyError_ as error:
        print(f"sextant-codex receipt unavailable: {error}", file=sys.stderr)
        return 1
    where = ""
    if written:
        target = Path(argv[2])
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=1) + "\n")
        where = f"; {target}"
    shown = ", ".join(
        f"{label} " + " ".join(f"{k}={n}" for k, n in result[field].items())
        for label, field in (
            ("paths", "paths"),
            ("status", "status"),
            ("served", "served_models"),
            ("connections", "connections"),
            ("reasoning.effort", "reasoning_effort"),
        )
    )
    verdict = "pin ok" if result["pin_ok"] else "pin NOT attested"
    print(
        f"sextant-codex receipt {argv[0]}: {result['calls']} calls; {shown}; {verdict}{where}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

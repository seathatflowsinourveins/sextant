"""Owner-run, single-cycle display sync; offline preset receipts need no session."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sextant.tradingview.auth import official_client
from sextant.tradingview.inputs import InputError, read_research_inputs
from sextant.tradingview.presets import preset_receipt
from sextant.tradingview.sync import OfficialTools, SyncError, sync_research

STOP = (
    "Display sync stopped. Re-inventory before retry; earlier writes may have succeeded. "
    "Owner browser consent is required each session (--authorize); "
    "no authorization is saved."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-dir", type=Path)
    parser.add_argument("--max-age", type=int, default=1200)
    parser.add_argument("--authorize", action="store_true", help="Owner browser consent, RAM-only")
    parser.add_argument("--apply", action="store_true", help="Apply named-list membership changes")
    parser.add_argument(
        "--presets", type=Path, help="Offline receipt for the reviewed Pine directory"
    )
    args = parser.parse_args(argv)
    if args.presets:
        try:
            print(
                json.dumps(
                    {"artifacts": preset_receipt(args.presets), "installed": False},
                    ensure_ascii=False,
                )
            )
            return 0
        except Exception:
            print("Local Pine receipt unavailable; no session opened or installation attempted.")
            return 2
    try:
        if args.research_dir is None:
            raise InputError("Provide --research-dir for one complete producer unit")
        inputs = read_research_inputs(
            args.research_dir, now=datetime.now(UTC), max_age=args.max_age
        )

        async def run():
            async with official_client(args.authorize) as client:
                return await sync_research(OfficialTools(client), inputs, apply=args.apply)

        print(json.dumps(asyncio.run(run()), ensure_ascii=False))
        return 0
    except InputError:
        print("Research input unavailable; no session opened and lists unchanged.")
        return 2
    except SyncError as error:
        # Only fixed literals; the message and any upstream text never reach stdout.
        label = error.label or type(error).__name__
        stage = error.stage or "sync"
        detail = f" ({error.detail})" if error.detail else ""
        print(f"{STOP} Safe diagnostic: {label} at {stage}{detail}.")
        return 2
    except Exception:
        # SDK/HTTP exceptions may embed credentials; never emit their args/tracebacks.
        print(STOP)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

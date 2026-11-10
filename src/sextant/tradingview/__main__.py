"""Owner-run display sync: one cycle, the owner-consented loop, or a preset receipt."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sextant.tradingview.auth import official_client
from sextant.tradingview.inputs import InputError, read_research_inputs
from sextant.tradingview.loop import (
    DEFAULT_REGISTRY,
    DEFAULT_STATE_ROOT,
    NO_CLAUDE_USAGE,
    run_loop,
)
from sextant.tradingview.presets import preset_receipt
from sextant.tradingview.sync import (
    OfficialTools,
    SyncError,
    sync_research,
)

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
    parser.add_argument(
        "--loop", action="store_true", help="One admitted display sync per J5 cadence tick"
    )
    parser.add_argument("--cadence-registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cadence-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--weekly-usage-pct", type=Decimal, default=Decimal(0))
    parser.add_argument("--usage-source", default=NO_CLAUDE_USAGE)
    parser.add_argument("--landed-sha", default=None)
    parser.add_argument("--enable-source", default=None)
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
    if args.loop:
        if args.research_dir is None:
            print("Provide --research-dir for the newest complete display unit")
            return 2
        return run_loop(
            research_dir=args.research_dir,
            authorize=args.authorize,
            registry=args.cadence_registry,
            state_root=args.cadence_root,
            max_age=args.max_age,
            weekly_usage_pct=args.weekly_usage_pct,
            usage_source=args.usage_source,
            landed_sha=args.landed_sha,
            enable_source=args.enable_source,
        )
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
        print(f"{STOP} Safe diagnostic: {error.stop_tail()}.")
        return 2
    except Exception:
        # SDK/HTTP exceptions may embed credentials; never emit their args/tracebacks.
        print(STOP)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

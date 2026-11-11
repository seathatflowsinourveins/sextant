# Attended paper node units

Trade step: custody and protection, then recorded paper evidence. These three user units
run the existing node entry points once, bounded by the node's own `--duration-s`.
All use `Restart=no`, with no timer or install target: a failure or normal stop
needs a new attended start. IBKR has separate lifecycle dry-run and order-sending units.

The lead installs and starts only after the separate max gate, landing, and the
owner-confirmed writer/stream handover. These files grant no trading authority.
Keep every pre-check and post-check in the approved run kits. Do not retry a denied
shell start command; use this reviewed unit path after landing.

1. From the verified merged checkout, the lead runs `bash deploy/paper/install.sh`.
   Like the TradingView installer, this renders the checkout prefix into the user
   unit directory and reloads the manager. It never enables or starts anything,
   reads a parameter file, or touches keys. Rerunning replaces the three unit files.
2. Create `$HOME/.config/sextant/paper/` and copy each needed `.params.example` there,
   dropping `.example`. Complete its blank values locally from the approved kit.
   These are required **non-secret** UTF-8 systemd assignment files, never `*.env`:
   no credential, full account identity, shell command or free-form flag list belongs
   in them. Keys stay in ADR-0028's store and enter one process through strict
   `with-keys.sh` using the fixed names in the unit. Do not source `runner.env`.
3. Use absolute paths; file values do not expand `~`, `$HOME`, other variables or
   `%h`. Quote a value with spaces using systemd.exec(5)'s assignment syntax.
   `${NAME}` in ExecStart passes the entire value as one argument, never as shell
   code. No run duration or private path is supplied by the checked-in example.
4. For B, supply the verified account-config **path**, claim list, fresh receipt
   directory, positive duration, sourced stream count/statement and non-secret
   expected-account suffix. Set `B_WRITER_LEASE_ROOT` to the old writer's existing
   locks directory and `B_STREAM_LEASE_ROOT` to the producer's existing leases
   directory, as the kit specifies. Never choose fresh per-run roots: these must
   exclude each current holder in its own location. No separate recoverable state
   directory exists: receipt-dir contains the receipt and lifecycle journal;
   restarting requires the
   node's existing flat-start checks. Clear any stale full expected-account ID in
   the manager's environment before using a suffix; a full identity takes precedence.
5. For IBKR, copy the kit's approved host, paper port, client IDs, instrument,
   quantity and duration into its local parameters and choose a fresh receipt
   directory. `IB_PAPER_ACCOUNT_ID` is a fixed key **name**, never a parameter value.
   Lease-root is compatibility-only; the node uses its shared home/cache account
   lock. The dry-run unit cannot request order sending. Both keep the default registry.

After the approved kit's handover/pre-checks, the lead starts **one** selected unit:
`systemctl --user start sextant-paper-b-stage1.service` or
`systemctl --user start sextant-paper-ibkr-dry-run.service`.
Watch with `systemctl --user status <unit> --no-pager` and
`journalctl --user -u <unit> -f`. A successful systemctl start alone does not prove
node admission; read the starting/refused receipt and follow the kit's checks.
Stop early with `systemctl --user stop <unit>`; otherwise the node's duration stops it.

B writes `order-mode-receipt.json` and `b-lifecycle-journal.jsonl` in `B_RECEIPT_DIR`.
IBKR writes its `ibkr-node-receipt.json` in `IBKR_RECEIPT_DIR`; verify `dry_run: true`
and the lifecycle profile for the dry-run unit. A missing key exits 3; parser/start
refusals remain the node's own. Neither a stop nor a receipt establishes venue-flat custody: perform
the kit's venue and lease post-checks before another writer starts.

## IBKR lifecycle orders after the dry run

Only the lead starts `sextant-paper-ibkr-lifecycle.service`, after the dry run's receipt
is good, its venue/lease post-checks pass and the reviewed handover is confirmed.
Copy `paper-ibkr-lifecycle.params.example` to the same non-secret parameter directory
as `paper-ibkr-lifecycle.params`; complete the approved choices and a fresh receipt
directory. Quantity and duration remain explicit `IBKR_ORDER_QTY` and `IBKR_DURATION_S`
values, with no checked-in defaults. This unit adds the node's fixed `--send-orders`
second opt-in and selects only `lifecycle`; it does not request resting SELLs.

The lead runs `systemctl --user start sextant-paper-ibkr-lifecycle.service` and uses
the same status, journal and stop commands above with that unit name. Read
`IBKR_RECEIPT_DIR/ibkr-node-receipt.json`: verify `dry_run: false` and `lifecycle`,
then follow the kit's venue and lease post-checks. A duration stop does not prove flatness.

Sources (**BUILD ON**, searched all deploy units and both node parsers):
Sextant@`7252b0f5c7ccdb416356aaddd9b53fa9a33bd405`
`deploy/paper/sextant-paper-ibkr-dry-run.service:1-13`, `deploy/paper/install.sh:23-28`,
`tests/proofs/test_paper_units.py:34-138,185-209` (unit and renderer contracts);
**USE AS IS** `src/sextant/paper/node_ibkr.py:77-110,169,275-313`
(the lifecycle profile, second opt-in and refusal of resting SELL profiles);
Sextant@`7a5b42312cc4a10ee9991ae94f914049a3c78b4a`
`deploy/tradingview/install.sh:49-70`, `sextant-tradingview-prestage.service:6-16`,
`tests/proofs/test_tradingview_units.py:35-97,262-285`,
`src/sextant/paper/node_ibkr.py:141-175`, ADR-0028;
Sextant@`d617cf8e91fbf4b5f57a12faa1ae339259e2e9a1`
`src/sextant/paper/node_order.py:200-247,606-628` (the kit's two lease roots);
nautilus_trader@`d53849b216e20f2c122ca01b4dd0da377638b186`
`docs/concepts/live.md:119-121,186-189` (native run/signal/shutdown ownership);
[systemd.service(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
(`ExecStart=`, `${VAR}`, `Restart=`) and
[systemd.exec(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
(`EnvironmentFile=`, `WorkingDirectory=`), read 2026-11-11.

# TradingView display units

Trade step: ranking, shown to the owner. These units keep the newest ranked movers in TradingView's two named lists, `NS movers` and `NS focus`, without a hand-started process. They are display only (ADR-0021). The producer reads slot 2's REST bars and opens no stream. The sync writes those two lists and nothing else. Neither places an order or touches Pine, presets, alerts or the Desktop port.

- `sextant-tradingview-prestage.service` runs the producer, `python -m sextant.tradingview.prestage`, as a long-running service. It sleeps across closed windows on its own, refreshes the unit on the J5 cadence, and moves to the next segment. `Restart=on-failure` uses systemd's default limits, so a repeated refusal ends in `failed`. Slot 2's two paper data names, `ALPACA_PAPER_2_API_KEY` and `ALPACA_PAPER_2_SECRET_KEY`, reach that one command through `scripts/with-keys.sh --strict`. No value is in a unit, an environment file, argv or a log.
- `sextant-tradingview-sync.service` runs `python -m sextant.tradingview --loop --authorize` for one session. `sextant-tradingview-sync.timer` starts it on weekdays at 04:00 New York time, the cadence registry's `display_start_minute_et`. The loop exits at the 20:00 display close. The service has no `Restart=`: every nonzero exit is either a latched run, which needs a reviewed reconciliation, or a missed owner consent.

## Install (the lead, after merge)

1. Stage the producer's inputs under `$HOME/sextant-data/tradingview-prestage/`: `nasdaqlisted.txt`, `otherlisted.txt` and `symbol_map.json`. The map must cover the whole filtered universe.
2. From the merged checkout, run:

   `bash deploy/tradingview/install.sh --gap-bound G --rvol-bound R --bounds-max-age-s S --producer-memory-max M --sync-memory-max N`

   None of the five values has a default authority, so each is required. The installer refuses a value or checkout path that would need systemd quoting. It writes the units under `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user`, substitutes only the checkout prefix (the data directories stay under `$HOME/sextant-data`) and reloads the user manager. **It enables and starts nothing**, and never invokes the keyed job. Rerunning it replaces the units.
3. Producer: run `systemctl --user enable --now sextant-tradingview-prestage.service`, but only once `lanes/tradingview/prestage-parameters.json` holds a measured `prestage_request_budget` row. Until then the producer refuses at the first display segment.
4. Sync:
   - Start it with `systemctl --user start sextant-tradingview-sync.service` when the owner is at a browser. Or run `systemctl --user enable --now sextant-tradingview-sync.timer` for the 04:00 start; on a missed consent, start the service again.
   - Read the authorize address with `journalctl --user -u sextant-tradingview-sync.service -o cat -n 5 --no-pager` and give the owner the plain address line. The owner opens it in the Windows browser within 300 s.
   - The address is printed only once the sign-in printing change lands. Until then the service may find no browser and stop.
   - Never run a hand loop while the unit is active, because the loop has no cross-process lock.

## Refusals

Read `systemctl --user status <unit>` and `journalctl --user -u <unit>`. No monitor rule covers these units yet.

- **Producer.** A missing key exits 3. A missing budget, map or registry exits 2 with "TV producer stopped". A skipped segment or tick is paged on stdout.
- **Sync.** A disabled registry, no landed SHA, or a latched, failed or page-pending state exits 2 before any consent. Stale input pages once on stderr and leaves the lists unchanged.
- **Stopping the sync service in the middle of an apply** latches that run. It must be reconciled before the next start.

The stored login (`--keep-login`) is not used: its branch refuses it with `--loop`, and loop support is a later change.

Sources: `deploy/calibration/` (adapted), `deploy/openviking/openviking.service` (long-running user service), and [systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html), [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html), [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html), [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) and [systemd.resource-control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html), read 2026-11-11 from the installed systemd 259 man pages. [Python `PYTHONUNBUFFERED`](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONUNBUFFERED) was read 2026-11-11. The manifest row is "TradingView producer and display sync as user units".

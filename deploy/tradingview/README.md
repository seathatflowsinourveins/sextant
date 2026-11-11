# TradingView display units

Trade step: ranking, shown to the owner. These units keep the newest ranked movers in TradingView's two named lists, `NS movers` and `NS focus`, without a hand-started process. They are display only (ADR-0021). The producer reads slot 2's REST bars and opens no stream. The sync writes those two lists and nothing else. Neither places an order or touches Pine, presets, alerts or the Desktop port.

- `sextant-tradingview-prestage.service` runs the producer, `python -m sextant.tradingview.prestage`, as a long-running service. It sleeps across closed windows on its own, refreshes the unit on the J5 cadence, and moves to the next segment. `Restart=on-failure` uses systemd's default limits, so a repeated refusal ends in `failed`. Slot 2's two paper data names, `ALPACA_PAPER_2_API_KEY` and `ALPACA_PAPER_2_SECRET_KEY`, reach that one command through `scripts/with-keys.sh --strict`. No value is in a unit, an environment file, argv or a log.
- `sextant-tradingview-sync.service` runs `python -m sextant.tradingview --loop --keep-login` for one display session. The loop loads the owner's stored sign-in from the encrypted key store (ADR-0028) and never opens a browser; a missing or refused sign-in is refused and paged. `sextant-tradingview-sync.timer` starts it on weekdays at 04:00 New York time, the cadence registry's `display_start_minute_et`. `Restart=on-failure`: the loop exits 0 at the 20:00 display close by design, which is never restarted, and it refuses a latched run before any session opens, so a restart can only resume a crashed session or end in `failed`.

## Install (the lead, after merge)

1. Stage the producer's three required files under `$HOME/sextant-data/tradingview-prestage/`: `nasdaqlisted.txt`, `otherlisted.txt` and `symbol_map.json`. The map must cover the whole filtered universe. Their sources are recorded in `docs/tradingview.md`'s producer section by the producer-configuration change (the NASDAQ Trader directory addresses; the symbol map stays an operator input).
2. From the merged checkout, run:

   `bash deploy/tradingview/install.sh --gap-bound G --rvol-bound R --bounds-max-age-s S --producer-memory-max M --sync-memory-max N`

   Each of the five values is required. The three bounds' sourced values are recorded in `lanes/tradingview/display-bounds.params.json`, which the producer-configuration change adds; pass those rows' values. The two memory limits have no measurement, so the lead chooses them. The installer refuses a value or checkout path that would need systemd quoting. It writes the units under `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user`, substitutes only the checkout prefix (the data directories stay under `$HOME/sextant-data`) and reloads the user manager. **It enables and starts nothing**, and never invokes the keyed job. Rerunning it replaces the units.
3. Producer: run `systemctl --user enable --now sextant-tradingview-prestage.service`, but only once `lanes/tradingview/prestage-parameters.json` holds a measured `prestage_request_budget` row. Until then the producer refuses at the first display segment.
4. Sync: once the stored-login loop change is on main and the owner's stored sign-in is set, run `systemctl --user enable --now sextant-tradingview-sync.timer`; inside the display window also run `systemctl --user start sextant-tradingview-sync.service` to start today's session. No browser is involved. Never run a hand loop while the unit is active: the loop has no cross-process lock.

## Refusals

Read `systemctl --user status <unit>` and `journalctl --user -u <unit>`. No monitor rule covers these units yet.

- **Producer.** A missing key exits 3. A missing budget, map or registry exits 2 with "TV producer stopped". A skipped segment or tick is paged on stdout.
- **Sync.** A disabled registry, no landed SHA, a missing or refused stored sign-in, or a latched, failed or page-pending state exits 2; repeated, it ends in `failed (start-limit-hit)`. Stale input pages once on stderr and leaves the lists unchanged.
- **Stopping the sync service in the middle of an apply** latches that run. It must be reconciled before the next start.

Sources: `deploy/calibration/` (adapted), `deploy/openviking/openviking.service` (long-running user service), and [systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html), [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html), [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html), [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) and [systemd.resource-control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html), read 2026-11-11 from the installed systemd 259 man pages. [Python `PYTHONUNBUFFERED`](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONUNBUFFERED) was read 2026-11-11. The manifest row is "TradingView producer and display sync as user units".

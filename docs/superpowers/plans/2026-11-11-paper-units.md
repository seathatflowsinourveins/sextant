# Attended paper units implementation plan

> **For agentic workers:** Use superpowers:executing-plans, native execution only.

**Goal:** Provide manual, bounded Paper B stage 1 and IBKR dry-run user units.

**Architecture:** Build on systemd's process supervision and parameter-file expansion,
the existing TradingView unit installer and proofs, and the existing node entry points.
No new runner, broker call, timer, state recovery or order implementation.

**Tech Stack:** systemd user units, Bash, pytest, the pinned Nautilus Python nodes.

**Spec:** LEAD-1329, dated 2026-11-11; supervised-units brief verified at dispatch.

## Global constraints

- Native worker only; local commits, no push or PR, no unit installation or start.
- No key reads, broker access, TradingView access, or edits to the private run kits.
- Both units use `with-keys.sh --strict`, key names only, and `Restart=no`.
- IBKR dry-run unit contains no order-sending flag.
- Non-secret `.params` files only; blank examples require operator choices.
- Raw diff must remain below 44,000 bytes before handoff.
- Independent max review and attended operation remain the coordinator's next steps.

## Upstream first

**BUILD ON:** [systemd.service(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
(`Restart=`, `ExecStart=`, `${VAR}` single-argument substitution), and
[systemd.exec(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
(`EnvironmentFile=`, `WorkingDirectory=`), read 2026-11-11.
NautilusTrader@`d53849b216e20f2c122ca01b4dd0da377638b186`
`docs/concepts/live.md:119-121,186-189` supplies run/signal/stop ownership.
Sextant@`7a5b42312cc4a10ee9991ae94f914049a3c78b4a`
`deploy/tradingview/install.sh:49-70`, `sextant-tradingview-prestage.service:6-16`,
`tests/proofs/test_tradingview_units.py:35-97,262-285` supply rendering and offline proofs;
`scripts/with-keys.sh:12-29,48-51` and ADR-0028 supply command-scoped keys.
Searched all `deploy/` units, those proofs, both node parsers and the official docs.
Only paper-specific unit configuration, installer selection and proofs are added.

## Review focus

- Renamed/obsolete CLI flags: parse rendered arguments with each real node parser.
- Whitespace or argument-looking parameters: `${VAR}` keeps one argument.
- Accidental restart/order sending: pin explicit no-restart and IBKR dry-run arguments.
- Installer checkout substitution: preserve data paths; reject systemd metacharacters.
- Credential exposure: fixed key-name injection; parameter examples contain no identities.

### Task 1: units, installation artifacts and operator instructions

**Files:** Create `deploy/paper/` services, `.params.example` files, `install.sh`, README;
create `tests/proofs/test_paper_units.py`; update `docs/manifest.md`,
`docs/handbook/ibkr-tester.md` and generated `llms.txt`.

**Interfaces:** Existing `node_order.parse` and `node_ibkr.parse`; existing with-keys CLI.
Land on N3 part 4, Sextant@`d617cf8e91fbf4b5f57a12faa1ae339259e2e9a1`:
`node_order.py:200-247,606-628` supplies the kit's two holder-specific lease roots.
There is no separate recoverable state directory option. Receipts/journal live in receipt-dir.

- [ ] Write unit contracts, parser integration and fake-manager installer proofs.
- [ ] Run focused pytest and save RED: missing artifacts, no broker or key access.
- [ ] Add units with fixed key names, required non-secret parameter files, no restart;
  adapt the existing literal checkout renderer to reload only, never enable/start.
- [ ] Add operator start/watch/stop/receipt instructions and one manifest row.
- [ ] Run focused GREEN, static copied-unit verification, shellcheck and ci-local;
  save counts and any unrelated failures in the private handoff report.
- [ ] Commit locally; hand off exact SHA and evidence for the separate max review.

Skills applied: orchestration; writing-plans; test-driven-development; executing-plans;
verification-before-completion; requesting-code-review (review handoff only, no helper
workers authorized); finishing-a-development-branch (retain branch as instructed).

# ADR-0028: Local keys live in an encrypted store, and the old host's keys move across once, sealed

- **Status:** accepted.
- **Date:** 2026-11-06
- **Harvested from:** northstar@b384d298d217:docs/decisions/0063-linux-secrets-systemd-creds.md
- **Harvested from:** northstar@b384d298d217:scripts/keys.sh
- **Harvested from:** northstar@b384d298d217:scripts/key-systemd.sh
- **Harvested from:** northstar@b384d298d217:scripts/with-keys.sh
- **Harvested from:** northstar@b384d298d217:scripts/sealed-key-transfer.sh

## Context
GitHub Environment secrets reach jobs on GitHub. They can't reach a native tab in the clean distro, so dsh, Jev and the research tools had no way to get a key there. The owner, asked whether to paste each one at a hidden prompt, 2026-11-06: "we need all the keys seamless transfer into it  the access of key is fine weneed seamless automation".

## Decision
- **Store:** the old harness's Linux store, carried with only its name changed. Each value is encrypted with `systemd-creds --with-key=host` under `~/.config/sextant/credentials`, one file per name, mode 600. It is the practice ADR-0063 reached by convergence ([systemd/systemd@v259.9](https://github.com/systemd/systemd/blob/v259.9/man/systemd-creds.xml)).
- **Use:** `scripts/with-keys.sh --strict -k NAME -- CMD` puts a key in one command's environment only. Nothing exports a key into a shell or a session. `ANTHROPIC_API_KEY` never reaches an interactive `claude`, which stays on the owner's subscription.
- **The move, once:** the old host's store reads each name, and the value goes straight down a named pipe under `/mnt/wsl/sextant/keys` into `scripts/keys.sh set NAME --sealed-stdin`. It is never on a command line, in a file, a log, an environment dump or a terminal. The framing is the old transfer's: value, completion line, end of file. `deploy/wsl/receive-keys.sh` is the receiving end, and it goes once the move is done. Verification is by name only, with `scripts/keys.sh list`.
- **What moves:** `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `EXA_API_KEY`, `CONTEXT7_API_KEY`, `TYPESAFE_API_KEY`, the three Alpaca paper accounts and the IBKR paper login.
- **What doesn't:** `SIGNOZ_ROOT_PASSWORD`, which belongs to the old host's own service. Live broker keys are not in the old store and are refused here by name. Native sign-ins stay with each tool, so the owner signs in. This transfer is not a standing permission to read another store.
- **Jobs on GitHub** still take their keys from Environment secrets, `paper` and `live` included, as ADR-0001 sets out.

## Consequences
- **Any tab in the distro can decrypt a key.** Tabs run as the store's own user, and that user has passwordless sudo. The store keeps keys out of the repo, logs and environment dumps, and it doesn't isolate them from an agent here. The owner accepted that in the words above. It rules out live keys here, not paper ones.
- **One writer per account is unchanged.** Holding a paper key is not permission to use it. No lane places a paper order on an account before a handover the owner confirms, with the old writer stopped first.
- **A market-data stream can cost an old lane its slot.** Alpaca's docs say "most users can have only 1 active stream connection". The same rule applies until the owner has Alpaca's answer for this account.
- **The old harness's rule names only `northstar-g2` for such a move.** This one rests on the owner's words above, and it was reported to that harness's lead.

## Revisit when
- **A paper handover:** that account's keys move to the `paper` environment, and the local copy goes.
- **A device with live keys:** owner, Phase 7. Choose one with no agents, as the plan says.
- **The new Mac:** it needs the Keychain path from the same source, added then.
- **An agent reads or misuses a key:** rotate at the vendor, and put the affected keys behind a sandbox.

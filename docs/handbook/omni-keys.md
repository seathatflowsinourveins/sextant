# OmniRoute key renewal

Authenticate a replacement before publishing its sealed value. A probe after
`keys.sh set --sealed-stdin` cannot recover the previous secret: the store has
already atomically replaced that entry. Keeping an old router ID is insufficient
when the old secret is no longer available for the runtime's next launch.

The renewal order is mint, authenticate the returned value in memory, seal through
the existing stdin frame, then revoke the previous router IDs. A rejected probe,
timeout or connection failure revokes only the candidate; the previous sealed
bytes and router key remain available. A failed seal also revokes the candidate.

Sources: [OmniRoute key creation at the existing pin](https://github.com/cheaper-inference/OmniRoute/blob/191dce8d534ceb56c28a08e71381284a9a87838f/src/app/api/keys/route.ts)
returns the candidate value and ID; its
[OpenAPI contract](https://github.com/cheaper-inference/OmniRoute/blob/191dce8d534ceb56c28a08e71381284a9a87838f/docs/openapi.yaml)
documents model discovery with bearer authentication. The store's atomic
publication comes from
[northstar's key-systemd.sh](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/scripts/key-systemd.sh),
carried here unchanged apart from its store name.

[PR #100's P1](https://github.com/seathatflowsinourveins/sextant-archive/pull/100#discussion_r4495068497)
exposed a test that asserted only the surviving router IDs. The regression
`test_failed_replacement_probe_preserves_the_old_sealed_value` uses distinct
previous and candidate values and checks the previous bytes as well as its ID
after authentication rejection, a timeout and a connection failure. This proof
also belongs in `just ci`, so the required check exercises it.

## Hermes: relaunch and restart before revoking

Hermes 0.22.5 runs one persistent gateway per home. It keeps the environment it was
launched with, and each client session keeps the credential it was created with:
"Missing or changed credentials fail closed rather than selecting a different key"
([gateway-internals.md](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/website/docs/developer-guide/gateway-internals.md),
Frozen local launch credentials). Revoking the old key first would strand every
running Hermes session. For Hermes, `renew` therefore runs these steps in order:

1. Mint the key, probe it in memory and seal it, as for every runtime.
2. Relaunch each Hermes client started before the mint. It finds them by the public
   `HERMES_HOME`, `ORCA_TERMINAL_HANDLE` and `ORCA_WORKTREE_ID` entries of each
   process environment, and drops every other entry unread. It runs
   `orca agent launch --agent hermes --surface terminal` in the same worktree, which
   starts `hermes` through the per-runtime launcher and `with-keys.sh`. It then runs
   `orca terminal close` on the old pane.
3. Restart the gateway the upstream way: `hermes gateway restart --detach`, through
   the same launcher. With no service installed, the replacement starts in the
   background with the restarting process's credentials (`spawn_unmanaged_gateway`,
   `inherit_credentials=True`). Without `--yes` and with no terminal, Hermes refuses
   while turns are running ([cli-commands.md](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/website/docs/reference/cli-commands.md)),
   so a busy gateway is retried, never interrupted.
4. Revoke the old ID only after `gateway_state.json` names a new gateway PID that
   started after the mint.

If any step fails, the old key stays. The next run sees the newest scripted key
sealed, current and authenticating, so it finishes steps 2 to 4 without minting
again. It also refuses to restart unless the launcher injects `OMNIROUTE_KEY_HERMES`.
No key is ever written to a file or put on argv.

## Python helpers and CI

Importing the helper creates `scripts/__pycache__` under normal Python settings;
the container's bytecode-disabled default hid this from the endpoint proof.
Read regular files with the existing Python `Path.is_file()` API before scanning
their contents. The regression includes a cache directory and checks that a
script containing a live endpoint is still rejected. Reproduce CI with bytecode
enabled when the container normally disables it.

Inspect the checkout commit when CI reports older test code. On a conflicted PR,
[this run](https://github.com/seathatflowsinourveins/sextant-archive/actions/runs/42271089972)
checked out a merge of `11c1d51` while the published head was `9209eb4`.
Confirm that the merge checkout includes the published head before attributing
its test results to that head.

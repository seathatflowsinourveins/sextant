# Native lane runtimes

Issue [#62](https://github.com/seathatflowsinourveins/sextant/issues/62). [Evidence, limits and the devc proposal](../../../docs/research/2026-11-06-native-lane-runtimes.md). `pins.json` records release dates, full upstream commits and binary digests. The runtime pins are the newest releases at least two weeks old at the recorded read; the owner's later instruction explicitly selects the current OmniRoute release.

In the clean Sextant distro, run `just lane-runtimes`. This installs under `~/.local/share/sextant-lane-runtimes`, with commands in `~/.local/bin`. It keeps the existing encrypted store and router data on a repeat install. It checks the owner's 20 GB **MemAvailable** floor before installation. Do not reinstall packages while a router sign-in is in progress.

The npm lock covers Pi and OpenCode v2; Pi's documented `--ignore-scripts` install is followed by OpenCode's required, version-checking postinstall. OMP and Antigravity are release binaries verified against GitHub's SHA-256 digests. Hermes uses its own installer at the full commit, including its TUI build. OpenHands SDK and tools are the matched 1.58.1 pair, with a separate hashed Python lock. No `srt` wrapper is installed. Gemini CLI was removed on the owner's 2026-11-06 instruction, verbatim: **"drop gemini, it was not working"**; its pin remains only in retirement history.

## Fresh router

Run `just omniroute` for the durable user service, or `just omniroute status` for its state. `service.sh` uses OmniRoute 3.8.53's own systemd unit generator, retaining notify, watchdog and restart behavior; its startup wrapper injects internal secrets through `with-keys.sh`, and its working directory is the stable main checkout. It binds only `127.0.0.1:22128` and uses its own `router-data`. It never uses the old campaign's :20128–20130 lanes. Provider connections are the owner's browser steps in OmniRoute's upstream credential store, encrypted with the injected storage key. Do not start a second bootstrap server on the service's port.

Open `http://127.0.0.1:22128/dashboard/providers` in an Orca browser tab. The owner sets the dashboard password during onboarding and connects the **GPT/Codex** provider. Never connect a Claude subscription. The installer removes only upstream's public `CHANGEME` first-boot placeholder; it never supplies an owner password.

Create the route once, using the same installed launcher for upstream CLI commands:

```bash
~/.local/share/sextant-lane-runtimes/router-start.sh combo create sextant-gpt --strategy auto --models codex/gpt-6.1-sol-max
~/.local/share/sextant-lane-runtimes/router-start.sh combo list --json
```

`routing.json` declares the combo and endpoint; `model-policy.json` records the owner's model rule, dated Artificial Analysis/vendor sources and the lead-approved Google interim. OmniRoute owns scoring, connection quota and health behavior. The single target pins **gpt-6.1-sol, max** across the five GPT runtimes. Recorded request artifacts show max on the successful calls; this is not a task-quality benchmark or a measurement of private provider compute. Native Codex subscription headroom is separate from the router's connected accounts.

## Native tabs

Use Orca's known agents, with no task prompt while opening a sign-in tab:

```bash
orca agent launch --agent pi --surface terminal
orca agent launch --agent omp --surface terminal
orca agent launch --agent opencode2 --surface terminal
orca agent launch --agent hermes --surface terminal
orca agent launch --agent antigravity --surface terminal
```

Pi has no per-tool approval flag. The launcher supplies OMP's `--yolo` and OpenCode's `--auto`; Orca 1.4.251 does not supply those two itself. Hermes receives `--yolo`; Orca supplies Antigravity's `--dangerously-skip-permissions`. Explicit upstream denies still apply. These are native processes with the user's filesystem/network access.

Pi, OMP, OpenCode, Hermes and OpenHands each receive their own #94 encrypted-store key, renamed on injection to **`OMNIROUTE_API_KEY`**, and use the profiles generated from `routing.json`. The names are `OMNIROUTE_KEY_PI`, `_OMP`, `_OPENCODE`, `_HERMES` and `_OPENHANDS`; #94 owns minting and renewal. Wrapping `orca agent launch` in `with-keys.sh` would key only the CLI client, so the installed runtime command is the injection point. The source shape is the old roster's `ns-native.sh`, with none of its jail or custom inference transport.

Hermes runs turns in its upstream shared gateway. A pre-key client can reconnect and restart that daemon with its old launch environment: close or relaunch those clients, then run `hermes gateway restart --detach` through the installed per-runtime command. The daemon keeps its launch key until restarted; coordinate this with #94's key renewal. Never put a key in `--api-key`, a config file or a URL. OpenCode's one-shot flags belong after its subcommand: `opencode2 run --format json 'task'` is expanded to `run --standalone --auto`, not root flags followed by `run`.

The Google family uses native, owner-authenticated **Antigravity** and OmniRoute's **agy** and **antigravity** provider connections. ADR-0030's model policy applies to those surfaces: **interim: Carbon not in this account's catalog (Google staged trusted-partner rollout)**, with `gemini-4-argon-high` at High until the account lists Carbon. The native launcher selects `--model gemini-4-argon-high --effort high` and documented `AGY_CLI_DISABLE_AUTO_UPDATE=true`; Antigravity reads project `AGENTS.md` directly. If an owner browser step is required, title its tab **SIGN-IN: Antigravity**; the current owner session is already authenticated. The freshness detector owns the later Carbon switch.

OpenHands is programmatic: Orca 1.4.251 rejects `--agent openhands-sdk`. The installed `openhands-sdk 'task message'` command uses upstream's SDK example, project `AGENTS.md` loading, `NeverConfirm` and `Conversation.close()` cleanup; it runs in a plain Orca terminal. It receives its own `_OPENHANDS` key at the same endpoint. Only a bounded routing smoke task was dispatched during acceptance.

Use the main cockpit workspace for persistent runtime/router tabs after the owner finishes sign-ins; the lane worktree can then follow the usual post-merge cleanup. The lead owns that handover, so cleanup must not interrupt a pending browser flow.

## Verification

`uv run --frozen pytest tests/proofs/test_lane_runtimes.py` checks the retained roster, release pins, profile contracts and runtime-side injection without real secrets. `uv run --frozen pytest tests/host/test_native_runtime_host.py` checks installed versions, SDK pair, durable service, local bind and memory floor. [smoke-receipts.json](smoke-receipts.json) records the separate real-call evidence for all six retained runtimes, including failed attempts and instrumentation limits. None of these is a task-quality benchmark.

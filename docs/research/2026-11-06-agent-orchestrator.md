# AO for lane PRs' fix-CI and review loops

Issue #57, from #47. The owner asked to adopt AO and to see it running. Read 2026-11-06.

## The pin

- [OrchestratorInc/agent-orchestrator](https://github.com/OrchestratorInc/agent-orchestrator) (formerly ComposioHQ) **v0.14.10**, a lightweight tag on `033d597032e448a0ea16c298350e36b099f74106`, released 2026-11-06T11:55:49Z as `Latest`, not a prerelease. Apache-2.0, 14,168 stars, not archived, pushed the same day.
- The Linux release asset `agent-orchestrator-linux-x64.AppImage` has the published digest `sha256:4253488aadfb75dbcfccd4b82e1e7bb126348220edc32d6a2942d0490c8b20ff`. AO's installer checks it.
- Installed here: `ao version` prints `0.14.10 commit 033d597032e4 built 2026-11-06T11:18:40Z`.

## Install path and runtime needs

- AO is now a desktop app (Electron) that supervises a Go daemon. Its headless path is [`scripts/setup-self-hosted.sh`](https://github.com/OrchestratorInc/agent-orchestrator/blob/033d597032e448a0ea16c298350e36b099f74106/scripts/setup-self-hosted.sh), which pulls the daemon, its bundled tmux and its ACP Node runtime out of the AppImage.
- **What it needs:** Linux x86_64, `git`, `python3`, `curl`, and systemd user services unless `--install-only`. It needs no sudo with `--install-only`. The `bootstrap-self-hosted.sh` wrapper adds apt packages, linger and `cloudflared`. This distro already has the first two and needs no tunnel.
- **What it writes:** `~/.ao/host/releases/<stamp>/` with a `current` symlink (227 MB here), `~/.local/bin/ao`, `~/.ao/running.json` and its SQLite store under `~/.ao/data`. Without `--install-only` it also writes `~/.config/systemd/user/ao-self-hosted.service` and turns on `ao remote-host`, a LAN listener on plain HTTP, or a Cloudflare tunnel.
- **The pin, enforced:** the script takes the latest stable release, so `deploy/wsl/ao.sh` runs it from the pinned commit and then refuses any `ao version` but the pin. When upstream releases again, the pin moves by PR.

## Choices here, and why

- **`--install-only`, run in an Orca tab:** AO's own option "for another service manager" (`docs/cli/README.md`, "`ao daemon` under a service manager"). The owner sees the daemon in Orca. It also skips the remote-host listener, which would sit in the network namespace the old lanes share.
- **`AO_PORT=3301`:** AO's default loopback port, 3001, was already bound on 2026-11-06 with no process in this distro, so another distro holds it. Agents never connect to the old lanes' services. Measured: the daemon listens only on `127.0.0.1:3301` and `[::1]:3301`.
- **No remote telemetry:** `docs/telemetry.md` says daemons started directly send none by default; `AO_TELEMETRY_REMOTE=off` makes it explicit (`backend/internal/config/config.go`, `parseTelemetryRemote`).
- **Its own clone:** AO creates a worktree per session (`ao spawn --help`: "Git projects use worktrees"). git checks a branch out in one worktree at a time, and Orca's lane worktree may still hold the lane branch. So AO's project is `~/.ao/repos/sextant`, a separate clone, and it stays outside Orca's worktrees and its lifecycle sweep.
- **Worker agent: Codex,** signed in natively (`codex login status`: ChatGPT). No key passes through AO. AO would need Claude only through Claude Code itself or `ANTHROPIC_API_KEY`. Its chat mode runs Claude through `@agentclientprotocol/claude-agent-acp`, a third-party runtime, and that may not carry the owner's Claude sign-in. So no AO session here runs Claude.

## One dispatcher per job

The old campaign closed AO because it "would add a second dispatcher" (northstar ADR-0041:56). Here Orca dispatches every lane. AO has one job: a lane PR's fix-CI and answer-review loop, after the hand-off.

- **AO's own claim mechanism exists:** `ao session claim-pr` and `ao spawn --claim-pr`, with `--no-takeover` to refuse a PR another live session owns (`docs/cli/README.md`; `docs/scm-observer.md`, "Explicit claim"; `backend/internal/service/session/claim_pr.go`). A claim records ownership only and checks out nothing, so the worker's first step is to check out the PR head and confirm the SHA, as the docs say.
- **Hand-off:** `just ao claim <PR>` refuses a PR unless it is open, not a draft, based on `main`, set to squash auto-merge, and has a settled `ci` check. The lead runs it after the lane worker's `worker_done`. From then on, AO's session is the branch's only writer.
- **What AO then does:** its observer polls every 30 s. `lifecycle.Manager.ApplyPRObservation` sends the owning session failed checks (`AutoInjectCI`, on by default), unresolved review comments, changes requested and merge conflicts (`backend/internal/lifecycle/reactions.go`). It only sends messages. A merge happens only through an explicit `ao pr merge --expected-head-sha`, and the worker's prompt forbids that.
- **Off by default, and left off:** AO's own reviewer (`autoReview`, `backend/internal/domain/projectconfig.go`), issue intake (`trackerIntake.enabled`, `backend/internal/domain/tracker.go`) and AO's orchestrator. So AO starts no work by itself and doesn't review. `review` stays gh-aw's.
- **The hard guard is GitHub's:** the rulesets require `ci`, `source` and `review`, which run from the base branch. Nothing an AO worker pushes can merge past them or change them.

## Not verified

- Whether `ao spawn --branch` with an existing remote branch checks it out, or starts a new local branch from `main`. The prompt covers both cases by resetting to `origin/<head>`.
- A full loop end to end, from a red check to AO's nudge to a pushed fix to a green check. #57 reports the first live run.

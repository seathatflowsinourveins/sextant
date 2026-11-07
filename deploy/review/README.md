# Local ephemeral checks

Private Sextant keeps GitHub scheduling, logs, required checks and token permissions, and uses local ephemeral compute, because hosted jobs stopped for billing at 04:32Z on 2026-11-07. This supersedes the hosted-compute decision in ADR-0001.

The owner's answer is recorded on [#58](https://github.com/seathatflowsinourveins/sextant/issues/58#issuecomment-6707587169): "go local or go public", and on a follow-up, "you decide with highest quality convergence". Two risks are accepted:
- The lead accepted, under that delegation, that passwordless-sudo agents on this host can forge a verdict.
- The owner accepted that ci can read its own runner's one-job credentials ("Accept + add exit cleanup", [Credentials](#credentials)).

Native job logs and summaries provide tamper evidence, not an independent attestation; local blind multi-family review is the mitigation. The upgrade is this same setup on an agent-free host. Public hosting was rejected because release assets contain vendor bars and owner fills, and the research history would be exposed.

## Lifecycle and sources

- actions/runner@v2.338.2 `d1eb12d4b115c301201de27d667284e1a80f2ab5`:
  - `images/Dockerfile`: the non-root `runner` user;
  - `src/Runner.Listener/{CommandSettings,Runner}.cs`, `src/Runner.Worker/JobHookProvider.cs`: native JIT input and lifecycle, native logs, hooks and environment files.
- GitHub docs, read 2026-11-07:
  - [Repository JIT REST endpoint](https://docs.github.com/en/rest/actions/self-hosted-runners#create-configuration-for-a-just-in-time-runner-for-a-repository);
  - [ephemeral lifecycle](https://docs.github.com/en/actions/reference/runners/self-hosted-runners);
  - [hardening](https://docs.github.com/en/actions/reference/security/secure-use);
  - [job hooks](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts);
  - [label routing](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job): "jobs will be queued on runners that have all the labels that you specify".
- actions/scaleset@v0.5.0 `af394d86c0d5024225238b0209043c70193bcfe6`, `examples/dockerscaleset/scaler.go::startRunner`: a fresh Docker container with the supported environment input.
  - It is a Public Preview, and its example warns it is not production-ready.
  - We adopt its container/JIT lifecycle, but use the documented repository REST endpoint and serial systemd slots rather than importing its independent scale-set listener and admin credential into the executor account.
- github/gh-aw@v1.0.1 `0627fdbe4beb5f3b71aa569f8d97150b87f2111a`, `reference/self-hosted-runners.md` and `reference/arc-dind-copilot-agent.md`:
  - covers all three runner surfaces, self-hosted enforcement, the split-filesystem topology, the shared work directory and Docker socket overrides;
  - its arc-dind probe treats only a `tcp://` `DOCKER_HOST` as DinD (`self-hosted-runners.md:43-44`), so the daemon keeps its loopback TCP API for the docker profile;
  - the chroot identity is the runner's UID and GID (`arc-dind-copilot-agent.md:106`);
  - non-root runner users are supported (`:160`).
  - Locks are compiled, never patched.
  - Container pins come from v1.0.1's own table (`pkg/actionpins/data/action_pins.json`), including gh-aw-node `2c2ea524`. `build-tools:0.29.0`, which arc-dind needs and that table lacks, is pinned to ghcr.io's index digest `sha256:10a5c7107f4e8fb18029acbcda5005bcea5aa45007f8eac281688961928bc1dc` (anonymous registry read, 2026-11-07).
- [Docker rootless mode](https://docs.docker.com/engine/security/rootless/) and the installed Docker 29.9.3 `dockerd-rootless.sh` (`DOCKERD_ROOTLESS_ROOTLESSKIT_DETACH_NETNS=false`, default `--disable-host-loopback`).
- rootless-containers/rootlesskit@v3.3.0 `888c3189e9cdf34dcdb19011e1c7c34eb94b5393`: native `--port-driver=none`. With `--disable-host-loopback`, the gvisor-tap-vsock driver omits its `10.0.2.1` to host `127.0.0.1` NAT (`pkg/network/gvisortapvsock/gvisortapvsock.go:140-145`), although `cmd/rootlesskit/main.go:598` still warns the flag "is not yet supported"; from the daemon's namespace, a host loopback listener answers at none of `10.0.2.1`-`10.0.2.3` (measured 2026-11-07).
- More Docker docs, read 2026-11-07:
  - [bridge networks](https://docs.docker.com/engine/network/drivers/bridge/);
  - [port publishing](https://docs.docker.com/engine/network/port-publishing/): "Setting the default bind address for containers";
  - [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/): `DOCKER-USER`;
  - [rootless troubleshooting](https://docs.docker.com/engine/security/rootless/troubleshoot/): "Entering into dockerd namespaces";
  - [container memory resource constraints](https://docs.docker.com/engine/containers/resource_constraints/): `--memory` and `--memory-swap` hard limits;
  - [prune label filters](https://docs.docker.com/reference/cli/docker/system/prune/);
  - the CLI's `DOCKER_CONFIG`;
  - [build variables](https://docs.docker.com/build/building/variables/): `BUILDX_CONFIG`.
- RFC 1918, RFC 6598 and RFC 3927 for the private, shared and link-local ranges.
- Installed manuals, read 2026-11-07:
  - systemd's `systemd.service(5)` (`Restart=always`, `SuccessExitStatus=`) and `systemd.unit(5)` (`StartLimitBurst=`, template instances `%i`);
  - `systemd.resource-control(5)` (`MemoryMax`, `MemorySwapMax`);
  - `systemd.exec(5)` (`PrivateTmp=`: in a user manager it implies `PrivateUsers=`);
  - `loginctl(1)` lingering: "a user manager is spawned for the user at boot";
  - util-linux `setpriv(1)`.
  - Values and authorities are in `limits.json`; the per-slot limit and concurrency are uncalibrated starts, and the whole-account cap is measured from both slots plus the rootless daemon.

## Two profiles

GitHub routes each job by label, and each profile is its own serial slot: one instance of `sextant-jit@.service`. In both profiles:
- **Jobs run as the image's non-root `runner`,** as on GitHub-hosted runners. The entrypoint prepares the job root as container root, then drops to `runner` with `setpriv`.
- **The job root is private** (0700), and job files inside it use umask 022.

### sealed (`sextant-jit-sealed`)
This profile runs `ci`, which runs PR code, plus `source` and `dependabot-automerge`, which need no daemon. The container gets no Docker socket, no `DOCKER_HOST` and no daemon address.
- **Network:** each job runs on its own user-defined bridge, `sealed_subnet` in `limits.json`, created and removed per job. Neither the default bridge, where gh-aw's MCP gateway runs, nor RootlessKit's namespace, where the TCP API listens, is reachable from it.
- **Egress:** goes through a `DOCKER-USER` chain that drops private, shared and link-local destinations except the namespace's DNS forwarder. The sealed job therefore reaches the internet but not the LAN, the tailnet or a host listener; #201 measured the difference before and after.
- **Linting:** ci uses the actionlint and shellcheck release binaries instead of a Docker action.

### docker (`sextant-jit-docker`)
This profile runs the gh-aw reviewers, whose AWF sandbox needs the daemon, and the scoreboard with its smokes.
- **Shared paths:** the runner and the daemon share the job root and the host's `/tmp`. The job's `$HOME` is its root, as the official image's home is the runner directory and ARC's work directory sits under it; AWF's agent writes its Claude settings to `/host$HOME` (`containers/agent/entrypoint.sh:241`), which exists only as the parent of the job's own mounts. gh-aw expects a runner and its daemon to share one `/tmp`: its setup removes and recreates `/tmp/gh-aw` (`actions/setup/setup.sh:105-130`), the daemon mounts literal `/tmp/gh-aw` sources such as the DIFC proxy's TLS directory (`start_cli_proxy.sh:107-164`), and its MCP gateway mounts `/tmp` itself (`-v /tmp:/tmp:rw`). This daemon's `/tmp` is the host's. RootlessKit refuses to copy up `/tmp`, and systemd's `PrivateTmp=` on the daemon's user unit implies `PrivateUsers=`, under which RootlessKit cannot map UID 1501's subordinate range ("newuidmap: write to uid_map failed: Operation not permitted", measured 2026-11-07). So docker jobs share the host's `/tmp`. AWF also mounts that `/tmp` into its agent sandbox, read-write (`src/services/agent-volumes/system-mounts.ts:29`). Around every job the slot removes `/tmp/gh-aw` and every `/tmp` entry, at any depth, owned by UID 1501's subordinate range, which only this daemon's containers use. Someone else's `/tmp/gh-aw` stops the slot.
- **Socket group:** gh-aw detects the socket's group itself (`resolve_docker_socket_gid.sh`); inside the daemon's namespace it is the `docker` group, not 0, so the non-root MCP gateway gets `--group-add` with that group.
- **The agent never sees the socket:**
  - AWF v0.29.0 masks `/var/run/docker.sock` and `/run/docker.sock` with `/dev/null` unless DinD is enabled (`src/services/agent-volumes/docker-socket.ts:33-49`), and the locks don't enable it.
  - gh-aw stages system binaries into a named volume instead of bind-mounting the runner's filesystem (`arc-dind-copilot-agent.md:104`), so `/run/user/1501` is never mounted.
  - The forwarded `tcp://127.0.0.1:2375` is the agent's own loopback, on AWF's internal network.
- **Trust boundary:** a job here controls UID 1501's daemon and can reach everything that UID can, including the files and the socket, and it shares the host's `/tmp`. So does the gh-aw agent, which reads untrusted PR text: AWF mounts the daemon's `/tmp`, here the host's, into every agent sandbox. The lead accepted, under the owner's delegation (2026-11-07, verbatim: "auto proceed with those sessions actions confirm etc with as you are the lead"), that AWF mounts the daemon's /tmp, which is the host's, read-write into every gh-aw agent sandbox (gh-aw-firewall v0.29.0 system-mounts.ts:29). Measured: about 1,605 world-readable top-level files and 5 world-writable directories; a gitleaks scan found no credential. Limits: the AWF egress allow-list, configured safe outputs only, agent scratch 0700, and the slot's any-depth sweep of subordinate-range entries after every job. The upgrade is an agent-free host. So the repository's own docker jobs are main-gated:
  - the review locks run under `pull_request_target`, which always takes the base branch's files;
  - every other docker job carries an exact `github.ref == 'refs/heads/main'` condition, pinned by a proof.
- **Upstream limits:**
  - GitHub restricts runners to selected workflows only through organization and enterprise runner groups ([manage access](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access), read 2026-11-07).
  - A job-started hook cannot refuse a job reliably: actions/runner still evaluates `if: always()` steps after a failed pre-job step (`StepsRunner.cs:200-231`), whatever the docs' "the job will not run" says.
  - So a new branch workflow can still request this label.
- **Collaborators:** the repository has no collaborator (lead, 2026-11-07), and none is added first. Before any collaborator joins, the docker profile moves to an organization runner group limited to selected workflows, or to an agent-free host.

### Shared by both slots
- **Daemon:** both slots share the daemon and the whole-UID memory cap. A daemon lock serializes cleanup, seed load and container creation. The docker slot's network prune spares the sealed slot's live network.
- **Published ports:** ports published without a host address bind to loopback on every bridge (`dockerd --ip` and `default-network-opts` `host_binding_ipv4`). Without that, AWF's squid, published as `3128:3128`, answered a sealed bridge's gateway, as measured on #201.
- **Fail-closed check:** before each start, a slot checks the live RootlessKit and dockerd arguments against the drop-in: no detached namespace, no port driver, no host loopback, loopback publishing. It refuses to start on any difference, so a job that rewrites UID 1501's drop-in cannot weaken the network unnoticed.
- **Host-side Docker CLI:** the slot's own CLI reads a root-owned, empty `DOCKER_CONFIG`, so no plugin or credential helper in UID 1501's `~/.docker` runs on the host. Buildx would keep its state under that directory, so the build-cache prune gets its own fresh, empty `BUILDX_CONFIG`, removed afterwards.

## Credentials

`jit.sh` runs as the credential producer, UID 1500, and calls GitHub with that account's `gh` login: `~/.config/gh/hosts.yml`, mode 0600, scopes `repo`, `workflow`, `read:org`, `gist`, `user`. The JIT REST endpoint needs repository admin access.

Producer credential: the lead decided, under the owner's explicit delegation (2026-11-07, verbatim: "please decide with sota convergenced and recommand"), to keep the existing gh login as the JIT producer's credential for now. It predates #201. Every agent session on this host already holds it. With passwordless sudo, no on-host placement hides a credential from agents. Upgrade, when an agent-free host exists: a dedicated GitHub App with only Administration (read and write) and Metadata (read) on this repository ('Authenticating ARC to the GitHub API', read 2026-11-07), minting short-lived installation tokens ('To use the API on behalf of an organization or another user, you should create a GitHub App', 'Keeping your API credentials secure', read 2026-11-07). Rotate the gh token on any suspected exposure. The #138 re-check's reconciliation may supersede this.

The token never enters UID 1501 or a container. Only the one-job JIT blob crosses, over stdin, so it is absent from argv, Docker `Config.Env` and logs.

**What a job can read.**
- The entrypoint exports the blob as `ACTIONS_RUNNER_INPUT_JITCONFIG` and execs `run.sh`.
- The listener stores it and removes it only from its own managed environment (`CommandSettings.cs:133-138`). The initial environments of `run.sh` (PID 1), `run-helper.sh` and the listener keep it in `/proc/<pid>/environ` for the container's life.
- `Runner.cs:239-253` decodes it into the job root as `.runner`, `.credentials` (OAuth `clientId`, `authorizationUrl`) and `.credentials_rsaparams`, the runner's RSA private key. The key is plaintext on Linux and re-read for every token request, so the files must stay.
- Job steps run as the runner's own user, with no upstream user switch. So every job, ci's PR code included, can read all of these for its own runner, and nothing of any other job.
- `run:` steps get no runtime or GitHub token in their environment (`NodeScriptActionHandler.cs:54-74`, `GitHubContext.cs:9-50`).
- ARC's default and DinD modes inject the same variable; only its Kubernetes mode moves job code into another pod.

**How long the key works.** It mints that one runner's OAuth tokens until GitHub de-registers it after its single job ([self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners): "automatically de-register the runner after it has processed one job").

**Deregistration at every teardown.** Each teardown deletes the runner's registration with the producer's login ([REST](https://docs.github.com/en/rest/actions/self-hosted-runners#delete-a-self-hosted-runner-from-a-repository), "Forces the removal of a self-hosted runner", read 2026-11-07).
- A runner can exit 0 without finishing its job (actions/runner `run-helper.sh`; ARC gha-runner-scale-set-0.15.1 `runner_unregistration.go`).
- Like ARC's `removeRunnerOfLivePod`, a 404 counts as already removed.
- A refusal, such as a job the service still holds, is kept and retried at the next start.
- A stop during the POST is covered by looking the runner up by name. After a SIGKILL, the next start removes the recorded id.
- A runner that exits without starting a job counts as a failure.

The owner accepted this residual on 2026-11-07 (#201): "Accept + add exit cleanup".

## Install and prove

1. Build `Dockerfile` with the dedicated rootless daemon. Save the image to root-owned `/var/lib/sextant-jit/runner.tar`, and record `docker image inspect --format '{{.Id}}'` in root-owned `/usr/local/lib/sextant-jit/runner-image`.
2. Under `/usr/local/lib/sextant-jit/`, install `jit.sh` and `limits.json`, and create the root-owned empty `docker-config` directory.
3. Install `user-1501-limits.conf` as `/etc/systemd/system/user-1501.slice.d/sextant-jit.conf` and apply the 13 GiB/zero-swap cap.
4. Install `docker-jit.conf` as the dedicated user's Docker drop-in, and restart that daemon only.
5. Install `sextant-jit@.service` under the producer's user manager, never as the old runner unit, and enable both instances: `systemctl --user enable --now sextant-jit@sealed sextant-jit@docker`.

Lingering is on for both accounts, so both managers, the daemon and both slots start at boot. Each slot waits up to `boot_wait_seconds` (`limits.json`) for the daemon and for GitHub.

Admission needs 33 GiB `MemAvailable`: the 20 GiB floor plus the 13 GiB cap.

Restarts follow `Restart=always`: a slot restarts after each job and after a failure, at most `start_limit` times (`limits.json`), so a transient failure recovers and a persistent one leaves the slot down for operator attention.

**Check the installed slot against a commit.** At landing, and after any reinstall, check that the host equals the merged head byte for byte: `cmp` each file under `deploy/review/` against its installed copy, plus the drop-in and unit paths above, and record the head SHA.

**After a WSL restart, verify:**
- `loginctl show-user sextant -p Linger` and the same for `sextant-review` both print `Linger=yes`.
- `systemctl --user is-enabled sextant-jit@sealed sextant-jit@docker` prints `enabled` twice, and `is-active` prints `active` twice.
- `sudo -u sextant-review XDG_RUNTIME_DIR=/run/user/1501 systemctl --user is-active docker` prints `active`.
- `gh api repos/seathatflowsinourveins/sextant/actions/runners --jq '.runners[] | [.name, .status] | @tsv'` lists one online `sextant-jit-sealed.*` and one online `sextant-jit-docker.*` runner.

If a slot is down, read `journalctl --user -u sextant-jit@<profile>`, fix the cause, then run `systemctl --user restart sextant-jit@<profile>`.

**Branch proof.** Use the existing dispatchable scoreboard workflow: `gh workflow run scoreboard.yml --ref <PR-branch> -f jit_smoke=true`.
- GitHub uses that branch's workflow file, so only `jit-sealed-smoke` runs. It checks that the sealed profile has no socket, no `DOCKER_HOST` and no API on 127.0.0.1, its gateway or 10.0.2.2, then runs ci's heaviest steps.
- From `main`, the same dispatch also runs `jit-smoke`, which checks the docker profile's daemon, tmpfs and a sibling bind, and `jit-cleanup-smoke`, which checks that both earlier roots, the sealed network and a named volume are gone.
- Native hooks add the receipt. No protected review, provider or broker secret is required.

The branch-dispatch receipt for the reviewed head is posted as a comment on #201; this file holds no run URL.

**Routed checks.** The routed `ci`, `source` and `review` checks cannot run on their own PR, because `pull_request_target` takes the base branch's workflows. The first PR after landing is their end-to-end witness.

If the machine or a slot is off, jobs queue, and eventually time out under GitHub's 24-hour routing rule. There is no automatic hosted fallback: restore the slot, or bring a sourced hosted-routing PR through the lead, and do not waive checks. Open a PR that changes this routing with `just pr "<title>" <body-file> false`, which leaves auto-merge off.

## Model effort

ADR-0030 bans V4 Pro, and `review.md` selects `anthropic/deepseek-flash`. [Artificial Analysis](https://artificialanalysis.ai/providers/deepseek), read 2026-11-07, ranks Flash max 33 versus Pro max 23.

**Pricing.** AWF v0.29.0's API proxy rejects any model missing from its own pricing tables with HTTP 400 (review-proof run 4). It prices `claude-opus-5-5`, which both pinned Claude Code versions send for `opus` (measured), but not DeepSeek's API name `deepseek-flash`. So `review.md` sets gh-aw's documented `models.default-ai-credits-pricing` to DeepSeek's published peak rates for it: input 0.3, output 1.2, cache read 0.006 per 1M tokens ([Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing), read 2026-11-07).

**dsh.** The pinned gh-aw dsh sample sends no effort, and DeepSeek defaults to `high` ([thinking mode](https://api-docs.deepseek.com/guides/thinking_mode), read 2026-11-07).
- The shared engine's patch therefore sets dsh 0.2.2-rc.1's documented keys: `agent-default-model.reasoningEffort`, the route's `reasoning`, and the model's `reasoningEfforts` and `compat.forceAdaptiveThinking`. Their source is the npm tarballs, matching their registry integrity, from tag `dsh-v0.2.2-rc.1` `66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db`.
- With these keys, pi-ai's `anthropic-messages` sends `output_config.effort: max`, which DeepSeek's [Anthropic API guide](https://api-docs.deepseek.com/guides/anthropic_api), read 2026-11-07, supports.
- A probe of the compiled harness with dsh 0.2.2-rc.1 recorded `reasoningEffort: max` in dsh's request header and got a 200 with a thinking block.
- AWF's api-proxy v0.29.0 rejects an effort only when the provider's model listing excludes it, and DeepSeek's Anthropic endpoint has no listing (404).

**Claude.** `review-claude.md` runs `model: opus` with `CLAUDE_CODE_EFFORT_LEVEL: max`, Claude Code's documented effort setting ([model configuration](https://code.claude.com/docs/en/model-config), read 2026-11-07).
- gh-aw's `?effort=` suffix applies only in routed mode (`claude_harness.cjs:421-428`). Otherwise alias resolution keeps it in the model id (`resolve_model_alias.cjs:452-465`), which Anthropic does not know.
- A request-sink probe of Claude Code 2.1.310, the lock's pin, and 2.1.318 recorded `claude-opus-5-5` at effort `max` with the variable, and `medium` without it.

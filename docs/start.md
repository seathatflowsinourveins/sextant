# Starting clean

A dedicated WSL distro with none of the old campaign's rules, hooks or tabs, loaded from GitHub (owner, 2026-11-06).

## What the owner does once
In PowerShell on Windows. It can't be started from the old WSL, because Windows access is off there.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.cloud-init" | Out-Null; Copy-Item "\\wsl.localhost\northstar\home\choreo\Developer\sextant\deploy\wsl\sextant.user-data" "$env:USERPROFILE\.cloud-init\sextant.user-data"; wsl --install Ubuntu-26.04 --name sextant --location Z:\WSL\sextant --vhd-size 200GB --no-launch; wsl -d sextant --user root --exec cloud-init status --wait; wsl --terminate sextant; wsl -d sextant
```

Then follow the new distro's first login: sign in to GitHub, add the Orca server in your Orca app when it shows the link (`Settings > Remote Orca Servers > Add Server`, see **Pairing Orca** below), and sign in to Claude and Codex. dsh asks for its key the first time it starts. Nothing else is typed. On another machine, copy `deploy/wsl/sextant.user-data` to that `.cloud-init` folder from a clone of this repo.

## What happens
1. `wsl --install` creates the distro without opening it, and cloud-init reads the user-data file named after it ([Ubuntu's guide](https://documentation.ubuntu.com/wsl/stable/howto/cloud-init/), read 2026-11-06). It creates the user and installs the GitHub CLI and Orca. The restart is what makes `/etc/wsl.conf` take effect, as on the old host.
2. The first login signs in to GitHub, clones this repo, and runs `deploy/wsl/setup.sh`.
3. `setup.sh` installs uv, Node, just, Claude Code, Codex and dsh at this repo's pins. It pairs Orca's headless server on its own port, 6771, by Orca's pairing flow, then runs it as Orca's own per-user service (`orca serve service install`, with this repo's terminal limits as a drop-in). It adds this project and a Claude lead in a tab, and runs `just accept`. This machine's `.wslconfig` has `guiApplications=false`, so Orca opens no window here: your Orca app connects to the server.
4. The lead's first steps: read the owner's research package, from this repo's release `seed-research-2026-10-09` or the Windows Desktop, as a start point only; then `docs/design.md`'s build order.

**Pairing Orca.** If your Orca app runs on this Windows PC, give `127.0.0.1` as the address: Windows reaches WSL on localhost with no firewall rule. The app then says the link points back to this device; tick **I reach this address through an SSH tunnel**, because WSL's localhost is the tunnel here. The tick only permits a loopback link: Orca still contacts the server and checks its key before saving it ([its pairing check](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/src/main/ipc/runtime-environments/runtime-environment-pairing-verification.ts#L52-L106)). From another computer, Windows' Hyper-V firewall blocks the port unless a rule admits it, as the old host's runbook does for 6768 (`northstar@b384d298d217:docs/handoff/workstation/phase-0-legacy.md`, section 7a). Run this once in an Administrator PowerShell, then accept the suggested tailnet address:

```powershell
New-NetFirewallHyperVRule -Name 'Sextant-Orca-6771' -DisplayName 'Sextant Orca TCP 6771' -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 6771
```

**Updating Orca.** The app's *Update Orca on the server host* can't update this server, because Orca leaves a `.deb` install to its host ([its updater](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/src/main/updater/lifecycle/updater-remote-status.ts#L33-L45)). A PR moves the pin in `deploy/wsl/sextant.user-data`; then `just orca-update` in the distro installs that package and reinstalls Orca's service, which restarts the server. Tabs keep running, since the terminal host outlives a server restart ([Orca's docs](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/docs/site/content/docs/remote-servers.mdx#L187)).

If a step stops, the window says so and waits. A session outside the distro can read what happened in `/mnt/wsl/sextant/first-login.log`, which never holds the pairing link or a sign-in, and fix it on GitHub. You press Enter to pull the fix and try again, and you don't type a command.

## What it is and is not
- **Clean:** the distro has its own home, so no old `~/.claude` rules or hooks load. Its Orca server lists only this project. Your Orca app shows it as a separate server, and can remove the old ones whenever you like.
- **Settings:** New York time, not the Windows clock; systemd on; services outlive a logout; Ubuntu's metrics off, so it asks nothing at first login. `.wslconfig` is shared by every distro and already tuned, so this leaves it alone. `just accept` proves each of these in the distro.
- **Windows access stays on,** so the lead can read the Desktop and open a folder for the owner by its full path (`/mnt/c/Windows/explorer.exe`), without asking. Windows programs are off `PATH`, so none shadows a Linux tool.
- **What that exposes:** a tab could also reach every distro's disk on `Z:` or run `wsl.exe --shutdown`, which would stop the old paper nodes. `AGENTS.md` forbids both, as a rule rather than a wall. `[interop] enabled=false` in `/etc/wsl.conf` and a restart make it a wall, at the cost of opening nothing on Windows and clicking each sign-in link by hand.
- **Shared with the old lanes until they retire:** RAM, and one WSL network namespace, so a tab here can reach loopback ports on the old distro. `/mnt/wsl` mounts are visible too. Those folders belong to uid 1000, the old lanes' user, so this distro's user is uid 1500 and can't write to them.
- **Outside the container:** native Orca tabs have neither its firewall nor its read-only binds. That is the owner's call for this distro, which holds nothing else: "QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING". Unattended agents still run through `devc`.
- **The debug port:** TradingView Desktop's `127.0.0.1:29222` is reachable from this distro, unauthenticated, with brokers connected. The owner accepted that on the condition that agents never connect to it (`docs/adr/0021-tradingview-display.md`), so that is a rule in `AGENTS.md`, not a wall.
- **Not here yet:** Orca's dsh tab needs `dsh-tui`, which the enhanced-dsh PR adds; until then `dsh` runs in a plain tab. The local secret-scan hook needs `gitleaks`; `ci` still scans every PR.
- **Nothing here waits on a prompt** (owner, 2026-11-06: "can you launch the login bypasspremiss so your future workflow will not be gated"). Orca launches every agent with its bypass flag by default ([its docs](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/docs/site/content/docs/agents/supported.mdx)), `setup.sh` answers Claude's own dialog up front, the GitHub login carries the `workflow` and `user` scopes, and the user has passwordless sudo. Root can also write the old lanes' folders, which is why `AGENTS.md` forbids that as a rule.
- **Docker comes later, and rootless:** all distros share one network namespace, and the old host's rule is one rootful daemon on it (`docs/decisions/0074-host-baseline.md`).
- **Size:** 200 GB at most, so it can never outgrow `Z:`'s free room, the old host's capacity rule. Its lead saw this and has no objection, and asks to start it after g2's install groups have applied, or with a word first, because all distros share memory.
- **On `Z:`:** a `Z:` reset takes this distro with it unless the owner names it as kept. Nothing is lost that isn't on GitHub, except sign-ins, which the owner redoes.
- **One writer:** the new lanes start on research and sim. A paper account moves only in a handover the owner confirms, with its old writer stopped first.

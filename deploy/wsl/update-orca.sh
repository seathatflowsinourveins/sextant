#!/usr/bin/env bash
# Brings this distro's Orca to the pin in sextant.user-data, then runs its server as Orca's own service.
# Safe to run again: a package and unit that are already current are left alone. Setup runs it, and so
# does `just orca-update` after a PR moves the pin.
#   - Orca's updater leaves a .deb install to its host (`manual-service-update-required`):
#     stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:src/main/updater/lifecycle/updater-remote-status.ts.
#   - `orca serve service install` writes Orca's own systemd user unit, which runs `orca serve --supervise
#     --no-pairing`. Reinstalling replaces the unit and restarts it: src/cli/specs/serve.ts and
#     src/cli/handlers/serve-service.ts. Terminals keep running through that restart:
#     docs/site/content/docs/remote-servers.mdx, the terminal limits.
# usage: update-orca.sh [PORT]   (without one, the port the installed unit already serves on)
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

user_data=deploy/wsl/sextant.user-data
limits=deploy/wsl/orca-serve-limits.conf
unit="$HOME/.config/systemd/user/orca-serve.service"

# The pin lives once, in the user-data that installs Orca at the distro's first boot.
url=$(sed -n 's|^- wget -nv -O /tmp/orca-ide\.deb \(https://[^ ]*\)$|\1|p' "$user_data")
sum=$(sed -n 's|^- echo "\([0-9a-f]\{64\}\)  /tmp/orca-ide\.deb".*|\1|p' "$user_data")
want=$(sed -n 's|.*/orca-ide_\([0-9.]*\)_amd64\.deb$|\1|p' <<< "$url")
[[ -n "$url" && -n "$sum" && -n "$want" ]] || { echo "No Orca pin found in $user_data." >&2; exit 1; }

have=$(orca-ide --version 2> /dev/null || echo none)
changed=0
if [[ "$have" != "$want" ]]; then
  deb=$(mktemp --suffix=.deb "${TMPDIR:-/tmp}/orca-ide.XXXXXX")
  trap 'rm -f "$deb"' EXIT
  wget -nv -O "$deb" "$url"
  echo "$sum  $deb" | sha256sum -c -
  # apt reads a local package as its own _apt user.
  chmod a+r "$deb"
  sudo apt-get install -y "$deb"
  changed=1
fi

port=${1:-}
if [[ -z "$port" && -f "$unit" ]]; then
  port=$(sed -n 's/^ExecStart=.* --port \([0-9][0-9]*\).*/\1/p' "$unit")
fi
if [[ -z "$port" ]]; then
  echo "Orca $have -> $(orca-ide --version). No server here yet: setup pairs one first."
  exit 0
fi

mkdir -p "$unit.d"
if ! cmp -s "$limits" "$unit.d/limits.conf"; then
  cp "$limits" "$unit.d/limits.conf"
  changed=1
fi
# Orca writes the caller's PATH into its unit, and a tab's differs from setup's, so that line isn't compared.
without_path() { grep -v '^Environment=PATH=' || true; }
want_unit=$(orca-ide serve service install --port "$port" --dry-run --json | jq -r '.result.content' | without_path)
have_unit=""
if [[ -f "$unit" ]]; then have_unit=$(without_path < "$unit"); fi
verdict=$(orca-ide serve service status --json 2> /dev/null | jq -r '.result.verdict // empty' || true)
if ((changed)) || [[ "$want_unit" != "$have_unit" || "$verdict" != live ]]; then
  # Every Orca tab inherits the unit's PATH, so ~/.local/bin's keyed lane launchers (parity.sh)
  # come ahead of setup's agent bins, whose own dsh carries no key.
  PATH="$HOME/.local/bin:$PATH" orca-ide serve service install --port "$port"
fi
echo "Orca $have -> $(orca-ide --version), served on $port by Orca's own service."

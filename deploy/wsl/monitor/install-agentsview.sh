#!/usr/bin/env bash
# Install the pinned AgentsView binary, wrappers and usage-only config on the clean
# distro. Run from main after merge (the lead's apply step); this script only writes
# files under ~/.local/share/sextant/monitor and ~/.local/bin and starts nothing.
# Download then checksum, in deploy/wsl/setup.sh's shape; the Orca Codex account
# homes present at install time join the lane home in the config's one homes line
# (upstream alternate homes, docs/configuration.md:1481-1511).
set -euo pipefail
set +x
here=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
prefix="$HOME/.local/share/sextant/monitor"
data_dir="${AGENTSVIEW_DATA_DIR:-$HOME/.local/share/sextant/monitor/agentsview-data}"
version=$(jq -r .agentsview.version "$here/agentsview-pins.json")
url=$(jq -r .agentsview.url "$here/agentsview-pins.json")
checksum=$(jq -r .agentsview.sha256 "$here/agentsview-pins.json")
asset=$(jq -r .agentsview.asset "$here/agentsview-pins.json")
mkdir -p "$prefix" "$data_dir" "$HOME/.local/bin"
target="$prefix/agentsview-$version"
if [[ ! -x "$target/agentsview" ]]; then
  download="$prefix/$asset.download"
  curl -fsSL "$url" -o "$download"
  printf '%s  %s\n' "$checksum" "$download" | sha256sum -c -
  mkdir -p "$target"
  tar -xzf "$download" -C "$target"
  rm -f "$download"
  chmod 755 "$target/agentsview"
fi
cp "$here/agentsview.sh" "$here/agentsview-usage.sh" "$here/agentsview-pins.json" "$prefix/"
chmod 755 "$prefix/agentsview.sh" "$prefix/agentsview-usage.sh"
ln -sfn "$prefix/agentsview.sh" "$HOME/.local/bin/agentsview"
ln -sfn "$prefix/agentsview-usage.sh" "$HOME/.local/bin/agentsview-usage"
if [[ -e "$data_dir/config.toml" ]]; then
  echo "install-agentsview: kept existing $data_dir/config.toml"
else
  homes='"~/.local/share/sextant-lane-runtimes/codex-home"'
  for account in "$HOME"/.config/orca/codex-accounts/*/home; do
    [[ -d "$account" ]] || continue
    homes+=", \"~/.config/orca/codex-accounts/$(basename "$(dirname "$account")")/home\""
  done
  sed "s|^homes = .*|homes = [$homes]|" "$here/agentsview-config.toml" >"$data_dir/config.toml"
  echo "install-agentsview: wrote $data_dir/config.toml"
fi
echo "install-agentsview: done; query with agentsview-usage, refresh with agentsview sync"

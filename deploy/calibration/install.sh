#!/usr/bin/env bash
# Adapt deploy/monitor/systemd/install.sh at Sextant@89c2317f3bec26945ca25854ebb7808b4f17317f.
# The lead runs this after merge; the installer never invokes the keyed job.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${SEXTANT_REPO:-$(cd "$here/../.." && pwd)}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"

# Upstream's literal sed replacement; restrict the prefix so the data home stays put.
escaped="${repo//\\/\\\\}"
escaped="${escaped//&/\\&}"
escaped="${escaped//|/\\|}"
for unit in sextant-calibration-data.service sextant-calibration-data.timer; do
  sed -e "s|%h/sextant/|$escaped/|g" -e "s|%h/sextant\$|$escaped|" \
    "$here/$unit" >"$unit_dir/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now sextant-calibration-data.timer
systemctl --user list-timers sextant-calibration-data.timer --no-pager

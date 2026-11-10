#!/usr/bin/env bash
# Install the Sextant monitor bridges as a per-user systemd timer.
set -euo pipefail

repo="${SEXTANT_REPO:-$HOME/sextant}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"

for unit in sextant-monitor.service sextant-monitor.timer; do
  sed "s|%h/sextant|$repo|g" "$here/$unit" >"$unit_dir/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now sextant-monitor.timer
systemctl --user list-timers sextant-monitor.timer --no-pager

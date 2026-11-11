#!/usr/bin/env bash
# Install the Sextant monitor bridges as a per-user systemd timer.
set -euo pipefail

repo="${SEXTANT_REPO:-$HOME/sextant}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"

# Escape sed's replacement metacharacters so a checkout path is literal.
# POSIX sed: '&' is the match, the delimiter ends the replacement, and a
# backslash escapes; https://pubs.opengroup.org/onlinepubs/9799919799/utilities/sed.html
# read 2026-11-10.
escaped="${repo//\\/\\\\}"
escaped="${escaped//&/\\&}"
escaped="${escaped//|/\\|}"

for unit in sextant-monitor.service sextant-monitor.timer; do
  sed "s|%h/sextant|$escaped|g" "$here/$unit" >"$unit_dir/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now sextant-monitor.timer
systemctl --user list-timers sextant-monitor.timer --no-pager

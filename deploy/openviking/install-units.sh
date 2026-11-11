#!/usr/bin/env bash
# Installs the research retrieval's user units from this checkout: the server and the index timer. Safe to
# run again. `enable --now` starts a stopped unit and leaves a running one as it is (systemctl(1)), so a
# changed server ExecStart takes effect at its next restart, never from here.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
units="$HOME/.config/systemd/user"
mkdir -p "$units"
for unit in openviking.service openviking-index.service openviking-index.timer; do
  sed "s|%h/sextant/deploy/|$PWD/deploy/|g" "deploy/openviking/$unit" > "$units/sextant-$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now sextant-openviking.service sextant-openviking-index.timer

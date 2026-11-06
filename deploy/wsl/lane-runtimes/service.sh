#!/usr/bin/env bash
# OmniRoute@191dce8d534ceb56c28a08e71381284a9a87838f: bin/cli/tray/autostart.mjs,
# buildLinuxSystemdUnitContent and enableLinux. Preserve its notify/watchdog/restart contract;
# adapt ExecStart to with-keys and omit plaintext EnvironmentFile.
set -euo pipefail
prefix="$HOME/.local/share/sextant-lane-runtimes"
unit="$HOME/.config/systemd/user/omniroute.service"
action=${1:-start}
case "$action" in
  install|start)
    mkdir -p "$(dirname "$unit")"
    node --input-type=module - "$prefix" > "$unit.tmp" <<'JS'
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const prefix = process.argv[2];
const { buildLinuxSystemdUnitContent } = await import(pathToFileURL(
  `${prefix}/router/node_modules/omniroute/bin/cli/tray/autostart.mjs`));
const repository = readFileSync(`${prefix}/repository-path`, 'utf8').trim();
const body = buildLinuxSystemdUnitContent(`${prefix}/router/node_modules/omniroute/bin/omniroute.mjs`)
  .split('\n').filter(line => !line.startsWith('EnvironmentFile='))
  .map(line => line.startsWith('ExecStart=') ? `ExecStart=${prefix}/router-start.sh` : line)
  .join('\n').replace('[Service]\n', `[Service]\nWorkingDirectory=${repository}\n`);
process.stdout.write(body);
JS
    mv "$unit.tmp" "$unit"
    systemctl --user daemon-reload
    systemctl --user enable omniroute.service
    if [[ "$action" == install ]]; then echo 'Service installed; bootstrap handover before start.'; exit 0; fi
    if ! systemctl --user is-active --quiet omniroute.service &&
       [[ -n $(ss -Hltn 'sport = :22128') ]]; then
      echo 'Port 22128 is occupied: hand over the bootstrap process before starting the service.' >&2
      exit 3
    fi
    systemctl --user start --no-block omniroute.service
    ;;
  status) systemctl --user show omniroute.service -p ActiveState -p SubState -p MainPID ;;
  *) echo 'usage: service.sh [install|start|status]' >&2; exit 2 ;;
esac

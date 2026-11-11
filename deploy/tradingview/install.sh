#!/usr/bin/env bash
# Adapt deploy/calibration/install.sh at Sextant@abcf121ebd6a76fae3e720c18ced5df03404d462.
# The lead runs this after merge. It writes the three user units and reloads the user manager;
# it never invokes the keyed job and enables or starts nothing. The values below have no default
# authority (docs/tradingview.md, the producer section), so each is a required argument.
set -euo pipefail

usage() {
  echo "usage: install.sh --gap-bound DEC --rvol-bound DEC --bounds-max-age-s INT" \
    "--producer-memory-max BYTES --sync-memory-max BYTES" >&2
  exit 2
}

gap="" rvol="" max_age="" producer_memory="" sync_memory=""
while (($#)); do
  (($# >= 2)) || usage
  case "$1" in
    --gap-bound) gap="$2" ;;
    --rvol-bound) rvol="$2" ;;
    --bounds-max-age-s) max_age="$2" ;;
    --producer-memory-max) producer_memory="$2" ;;
    --sync-memory-max) sync_memory="$2" ;;
    *) usage ;;
  esac
  shift 2
done

# Refuse rather than quote: each value must need no systemd quoting, specifier or sed escape.
decimal='^[0-9]+(\.[0-9]+)?$'
whole='^[1-9][0-9]*$'
bytes='^[1-9][0-9]*[KMGT]?$'
[[ "$gap" =~ $decimal && "$rvol" =~ $decimal ]] || usage
[[ "$max_age" =~ $whole ]] || usage
[[ "$producer_memory" =~ $bytes && "$sync_memory" =~ $bytes ]] || usage

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${SEXTANT_REPO:-$(cd "$here/../.." && pwd)}"
# An unquoted ExecStart splits at whitespace and expands % and $ (systemd.service(5)).
if [[ "$repo" =~ [[:space:]%\$\"\'\\] ]]; then
  echo "install.sh: the checkout path needs systemd quoting; use a plain path" >&2
  exit 2
fi
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"

# Upstream's literal sed replacement; restrict the prefix so the data home stays put.
escaped="${repo//\\/\\\\}"
escaped="${escaped//&/\\&}"
escaped="${escaped//|/\\|}"
for unit in sextant-tradingview-prestage.service sextant-tradingview-sync.service \
  sextant-tradingview-sync.timer; do
  sed -e "s|%h/sextant/|$escaped/|g" -e "s|%h/sextant\$|$escaped|" \
    -e "s|@GAP_BOUND@|$gap|g" -e "s|@RVOL_BOUND@|$rvol|g" \
    -e "s|@BOUNDS_MAX_AGE_S@|$max_age|g" \
    -e "s|@PRODUCER_MEMORY_MAX@|$producer_memory|g" \
    -e "s|@SYNC_MEMORY_MAX@|$sync_memory|g" \
    "$here/$unit" >"$unit_dir/$unit"
done
systemctl --user daemon-reload
echo "Installed; nothing enabled or started. See deploy/tradingview/README.md for the lead's steps."

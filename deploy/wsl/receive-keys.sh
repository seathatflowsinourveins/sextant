#!/usr/bin/env bash
# Once, on the clean distro: take the old host's keys from named pipes into scripts/keys.sh.
# It waits until the old lead, watching for READY, sends them one at a time, and it stops at the first
# refused frame. It writes names, exit codes and counts only, here and to status, which the old lead
# reads. Every pipe is closed when it ends, done or not. See docs/adr/0028-local-keys.md.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

dir=/mnt/wsl/sextant/keys
status="$dir/status"
# The old host's user group. Only it may write a frame, and only this user can read one.
sender_gid=1000
# Slot 1 is the owner's Peregrine account (2026-11-07): never receive ALPACA_PAPER_1_*.
names=(
  ANTHROPIC_API_KEY DEEPSEEK_API_KEY EXA_API_KEY CONTEXT7_API_KEY TYPESAFE_API_KEY
  ALPACA_PAPER_2_API_KEY ALPACA_PAPER_2_SECRET_KEY
  ALPACA_PAPER_3_API_KEY ALPACA_PAPER_3_SECRET_KEY
  IB_PAPER_USERNAME IB_PAPER_PASSWORD IB_PAPER_ACCOUNT_ID
)

counts() { scripts/keys.sh list | awk '{n[$1]++} END {printf "set %d, missing %d", n["set"], n["missing"]}'; }
report() { printf '%s\n' "$*" | tee -a "$status"; }
close_all() { rm -f "$dir/READY" "${names[@]/#/$dir/}"; }
trap close_all EXIT

sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 755 "$dir" || exit 1
printf 'before: %s\n' "$(counts)" > "$status"
for name in "${names[@]}"; do
  mkfifo -m 600 "$dir/$name" && sudo chgrp "$sender_gid" "$dir/$name" && chmod 620 "$dir/$name" || exit 1
done
printf '%s\n' "${names[@]}" > "$dir/READY"

for name in "${names[@]}"; do
  scripts/keys.sh set "$name" --sealed-stdin < "$dir/$name" > /dev/null 2>&1
  rc=$?
  rm -f "$dir/$name"
  report "$name exit $rc"
  if ((rc != 0)); then
    report "stopped"
    exit 1
  fi
done
report "after: $(counts)"
report "done"

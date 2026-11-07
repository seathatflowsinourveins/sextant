#!/usr/bin/env bash
# CommandSettings.cs at actions/runner d1eb12d4 reads, masks and removes this supported input.
set +x
set -euo pipefail
ulimit -c 0
: "${SEXTANT_JIT_ROOT:?}"
drop=()
if (( EUID == 0 )); then
  # Jobs run as the image's own non-root `runner`, as in actions/runner's images/Dockerfile and on
  # GitHub-hosted runners; gh-aw's arc-dind chroot identity is the runner's UID and GID. Only this
  # preparation runs as container root. The job root stays private to `runner` (0700).
  drop=(setpriv --reuid=runner --regid=runner --init-groups)
  chown runner:runner "$SEXTANT_JIT_ROOT"
  install -d -o runner -g runner "${HOME:?}"
fi
# Inside that private root, job files use the usual 022 so sibling containers can read the workspace.
umask 022
"${drop[@]}" cp -a /opt/runner-dist/. "$SEXTANT_JIT_ROOT/"
chmod 0700 "$SEXTANT_JIT_ROOT"  # after cp -a, which copies the distribution directory's 0777
cd "$SEXTANT_JIT_ROOT"
# stdin is not Docker's Config.Env or argv. Never echo or persist the encoded configuration.
IFS= read -r ACTIONS_RUNNER_INPUT_JITCONFIG
[[ -n "$ACTIONS_RUNNER_INPUT_JITCONFIG" && "$ACTIONS_RUNNER_INPUT_JITCONFIG" != null ]]
export ACTIONS_RUNNER_INPUT_JITCONFIG
unset ACTIONS_RUNNER_PRINT_LOG_TO_STDOUT
exec "${drop[@]}" ./run.sh

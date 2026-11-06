#!/usr/bin/env bash
# GitHub's documented self-hosted runner install, under a dedicated OS user. Run as an administrator
# with sudo and a gh login. Source: docs.github.com/en/actions/how-tos/manage-runners/
# self-hosted-runners (add-runners, configure-the-application-as-a-service, run-scripts), read
# 2026-11-05.
#   RUNNER_HOME     puts the runner on another disk (default /var/lib/sextant-runner).
#   RUNNER_ROOTLESS=1 uses Docker's documented rootless mode, under that user, instead of the
#                   host's Docker. docs.docker.com/engine/security/rootless, read 2026-11-05.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
. "$here/runner.env"

repo=seathatflowsinourveins/sextant
user=sextant-runner
home=${RUNNER_HOME:-/var/lib/sextant-runner}
dir=$home/actions-runner
as_runner() { sudo -u "$user" -H "$@"; }

id "$user" >/dev/null 2>&1 || sudo useradd --create-home --home-dir "$home" --shell /bin/bash "$user"
sudo install -D -m 0755 -o root -g root "$here/job-guard.sh" /opt/sextant-runner/job-guard.sh

env_file=$(mktemp "${TMPDIR:-/tmp}/ns.XXXXXX")
echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/sextant-runner/job-guard.sh" > "$env_file"
if [[ ${RUNNER_ROOTLESS:-0} == 1 ]]; then
  uid=$(id -u "$user")
  sudo loginctl enable-linger "$user"
  # --force only skips the check for a rootful daemon, which stays untouched.
  as_runner env XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    dockerd-rootless-setuptool.sh install --force
  printf 'DOCKER_HOST=unix:///run/user/%s/docker.sock\nXDG_RUNTIME_DIR=/run/user/%s\n' "$uid" "$uid" >> "$env_file"
else
  sudo usermod -aG docker "$user"
fi

if ! as_runner test -x "$dir/config.sh"; then
  as_runner mkdir -p "$dir"
  as_runner curl -fsSL "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz" -o "$dir/runner.tgz"
  as_runner bash -c "echo '$RUNNER_SHA256  $dir/runner.tgz' | sha256sum -c - && tar -xzf '$dir/runner.tgz' -C '$dir' && rm '$dir/runner.tgz'"
fi
sudo bash -c "cd '$dir' && ./bin/installdependencies.sh" >/dev/null
sudo install -m 0644 -o "$user" -g "$user" "$env_file" "$dir/.env"
rm -f "$env_file"

if ! as_runner test -f "$dir/.runner"; then
  # The runner reads ACTIONS_RUNNER_INPUT_* (actions/runner CommandSettings.cs), which keeps the
  # registration token off the command line.
  ACTIONS_RUNNER_INPUT_TOKEN=$(gh api -X POST "repos/$repo/actions/runners/registration-token" --jq .token)
  export ACTIONS_RUNNER_INPUT_TOKEN
  sudo --preserve-env=ACTIONS_RUNNER_INPUT_TOKEN -u "$user" -H bash -c \
    "cd '$dir' && ./config.sh --unattended --url 'https://github.com/$repo' --name '$(hostname)-sextant' --labels sextant --replace"
  unset ACTIONS_RUNNER_INPUT_TOKEN
fi

sudo bash -c "cd '$dir' && { ./svc.sh install '$user' 2>/dev/null || true; ./svc.sh start; ./svc.sh status; }" | grep -E 'Active:'

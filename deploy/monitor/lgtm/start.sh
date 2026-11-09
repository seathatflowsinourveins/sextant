#!/usr/bin/env bash
# Start the local LGTM store (rootless Docker, loopback only). Passwordless:
# anonymous Viewer access is the only UI path (compose.yaml); the Grafana
# admin password ([security] admin_password, grafana/grafana v13.2.4
# conf/defaults.ini) is still required by Grafana on first run, so a random
# throwaway value is generated here and passed to this one compose command
# through its environment only. It is never stored, printed or logged, and
# nobody needs it: basic auth and the login form are disabled.
set -euo pipefail
cd "$(dirname "$0")"
export LGTM_CONTAINER_MEMORY="${LGTM_CONTAINER_MEMORY:-2G}"
GF_SECURITY_ADMIN_PASSWORD="$(head -c 48 /dev/urandom | base64 | tr -d '\n')"
export GF_SECURITY_ADMIN_PASSWORD
exec docker compose up -d

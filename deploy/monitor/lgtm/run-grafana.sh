#!/usr/bin/env bash
# Sextant override of docker/run-grafana.sh from grafana/docker-otel-lgtm
# @9c57b1400ccdb8920e1a2b6083134cc5ef244a8f, mounted read-only over
# /otel-lgtm/run-grafana.sh by compose.yaml. Two deliberate changes, nothing
# else: (1) the block that forced GF_PLUGINS_PREINSTALL=grafana-llm-app (a
# grafana.com download on every start, even when the variable was set empty)
# is removed, so Grafana starts with zero outbound calls; (2) the anonymous
# org-role default is Viewer, not Admin (compose also pins Viewer).

# shellcheck disable=SC1091 # Flint 0.20.3 runs ShellCheck without source following.
source ./common.sh
source_sibling logging.sh
source_sibling grafana-plugins.sh

# Respect user-provided environment variables and apply defaults only if unset
export GF_AUTH_ANONYMOUS_ENABLED="${GF_AUTH_ANONYMOUS_ENABLED:-true}"

# Only set anonymous org role when anonymous auth is enabled
if [ "${GF_AUTH_ANONYMOUS_ENABLED}" != "false" ]; then
	export GF_AUTH_ANONYMOUS_ORG_ROLE="${GF_AUTH_ANONYMOUS_ORG_ROLE:-Viewer}"
fi

export GF_PATHS_HOME=/data/grafana
export GF_PATHS_DATA=/data/grafana/data
export GF_PATHS_PLUGINS=/data/grafana/plugins

# When upgrading Grafana on a persisted /data volume, drop managed plugins
# that were downloaded for a previous Grafana version so compatible builds
# are re-downloaded. Without this, stale app builds are served by a newer
# Grafana until a second restart. See grafana-plugins.sh.
refresh_stale_managed_plugins

cd /otel-lgtm/grafana || exit 1
run_with_logging "Grafana ${GRAFANA_VERSION}" "${ENABLE_LOGS_GRAFANA:-false}" ./bin/grafana server

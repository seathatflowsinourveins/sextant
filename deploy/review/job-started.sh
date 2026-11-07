#!/usr/bin/env bash
# Native runner job hook; telemetry through GitHub's environment files.
set -euo pipefail
date -u +%FT%TZ > "${SEXTANT_JIT_ROOT:?}/.job-started"

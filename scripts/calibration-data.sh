#!/usr/bin/env bash
# Invoked only by the reviewed user unit; this script never reads stored keys.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="${1:?usage: calibration-data.sh DATA_DIR}"
cd "$root"
exec uv run --frozen python -m sextant.data.calibration_job \
  --data-dir "$data_dir" --universe "$data_dir/universe.json" \
  --parameters "$root/deploy/calibration/parameters.json"

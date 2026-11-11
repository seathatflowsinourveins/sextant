#!/usr/bin/env bash
# Invoked only by the reviewed calibration unit after its job; this script never reads stored keys.
# It writes the ranking mode's prior closes and asset types beside the baselines (N2b-3).
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="${1:?usage: ranking-inputs.sh DATA_DIR LISTINGS_DIR}"
listings_dir="${2:?usage: ranking-inputs.sh DATA_DIR LISTINGS_DIR}"
session="$(TZ=America/New_York date +%F)"
cd "$root"
exec uv run --frozen python -m sextant.data.ranking_inputs \
  --out "$data_dir/ranking-inputs" --universe-artifact "$data_dir/universe.json" \
  --listings-dir "$listings_dir" --session "$session" \
  --api-key-env APCA_API_KEY_ID --api-secret-env APCA_API_SECRET_KEY \
  --parameters "$root/deploy/calibration/parameters.json"
